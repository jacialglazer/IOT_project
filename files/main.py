# =============================================================================
# main.py — Node orchestrator
# Runs on every Pico W node. Change NODE_ID in config.py per device.
# =============================================================================

import time
import _thread
import json
import config
import wifi_link
import ble_link
import lora_link
import routing
import metrics
import telemetry
import stats_sender

# ---------------------------------------------------------------------------
# Packet router — called by all link listeners when a packet arrives
# ---------------------------------------------------------------------------

_last_rebroadcast = 0
REBROADCAST_COOLDOWN_MS = 3000  # max one re-broadcast per 3 seconds

def on_packet_received(packet: dict, sender_addr: str, link_type: str):
    global _last_rebroadcast
    ptype = packet.get("type") or packet.get("t")
    proto = packet.get("proto") or packet.get("p") or "DSDV"

    # Record latency from embedded timestamp
    # Max latency sanity bounds per link type to prevent misclassification
    MAX_LATENCY = {"wifi": 2000, "ble": 5000, "lora": 30000}
    if "ts" in packet:
        ts = packet["ts"]
        if ts and ts > 0:
            latency = time.ticks_diff(time.ticks_ms(), ts)
            if 0 < latency < MAX_LATENCY.get(link_type, 5000):
                metrics.record_received_timestamp(link_type, ts, packet.get("_rssi", 0))

    if ptype == "HELLO" and proto == "DSDV":
        changed = routing.receive_dsdv_hello(packet, link_type)
        now = time.ticks_ms()
        if changed and time.ticks_diff(now, _last_rebroadcast) > REBROADCAST_COOLDOWN_MS:
            _last_rebroadcast = now
            wifi_link.broadcast(routing.make_hello_packet())

    elif ptype == "HELLO" and proto == "OLSR":
        routing.receive_olsr_hello(packet, link_type)

    elif ptype == "TC" and proto == "OLSR":
        routing.receive_olsr_tc(packet, link_type)
        if int(packet.get("from", 0)) in routing.MPR_SET:
            wifi_link.broadcast(packet)

    elif ptype == "TELEMETRY":
        if config.NODE_ID == config.GATEWAY_NODE_ID:
            telemetry.receive_and_forward(packet)

    elif ptype == "PING":
        sender_node = packet.get("from")
        if sender_node:
            wifi_link.send(int(sender_node), {
                "type":    "PONG",
                "from":    config.NODE_ID,
                "seq_no":  packet.get("seq_no"),
                "orig_ts": packet.get("ts"),
                "ts":      time.ticks_ms(),
            })

    elif ptype == "PONG":
        seq_no = packet.get("seq_no")
        if seq_no:
            metrics.record_received(seq_no, link_type, packet.get("_rssi", 0))


# ---------------------------------------------------------------------------
# Combined listener thread — mesh (5000) + telemetry (6000) on core1
# ---------------------------------------------------------------------------

def combined_listener_thread():
    import socket

    mesh_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mesh_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mesh_sock.bind(("0.0.0.0", config.MESH_PORT))
    mesh_sock.listen(5)
    mesh_sock.settimeout(0.1)
    print(f"[WiFi] Listening on port {config.MESH_PORT}")

    telem_sock = None
    if config.NODE_ID == config.GATEWAY_NODE_ID:
        telem_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        telem_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        telem_sock.bind(("0.0.0.0", config.TELEMETRY_PORT))
        telem_sock.listen(5)
        telem_sock.settimeout(0.1)
        print(f"[Telemetry] Gateway listening on port {config.TELEMETRY_PORT}")

    while True:
        # Check mesh port
        try:
            conn, addr = mesh_sock.accept()
            data = conn.recv(512)
            conn.close()
            if data:
                try:
                    on_packet_received(json.loads(data.decode()), addr[0], "wifi")
                except Exception as e:
                    print(f"[WiFi] Parse error: {e}")
        except OSError:
            pass

        # Check telemetry port (gateway only)
        if telem_sock:
            try:
                conn, addr = telem_sock.accept()
                conn.settimeout(0.5)
                data = b""
                try:
                    while len(data) < 2048:
                        chunk = conn.recv(256)
                        if not chunk:
                            break
                        data += chunk
                except OSError:
                    pass
                conn.close()
                if data:
                    try:
                        packet = json.loads(data.decode())
                        telemetry.receive_and_forward(packet)
                        print(f"[Telemetry] Received from node {packet.get('node_id')}")
                    except Exception as e:
                        print(f"[Telemetry] Parse error: {e}")
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    print(f"\n{'='*40}")
    print(f"  Node {config.NODE_ID} starting up")
    print(f"{'='*40}\n")

    # Init hardware
    stats_sender.init()
    lora_link.init()
    ble_link.init()

    # Register BLE callback and start continuous background scan
    ble_link.set_receive_callback(on_packet_received)
    ble_link.start_scan(0)   # 0 = continuous non-blocking, 10% duty cycle
    print("[BLE] Continuous scan started")

    # Connect WiFi
    if not wifi_link.connect():
        print("[Main] Wi-Fi failed — some features disabled")

    # Init routing + telemetry
    routing.init(config.NODE_ID, config.ROUTING_OBJECTIVE)
    telemetry.init(config.NODE_ID == config.GATEWAY_NODE_ID)

    # Start ONE combined listener on core1
    started = False
    for attempt in range(5):
        try:
            _thread.start_new_thread(combined_listener_thread, ())
            print("[Main] Listener thread started on core1")
            started = True
            break
        except OSError:
            print(f"[Main] core1 busy, waiting... ({attempt+1}/5)")
            time.sleep(2)

    if not started:
        print("[Main] ERROR: Could not start listener. Hard resetting...")
        import machine
        machine.reset()

    print("[Main] All systems up. Entering main loop.\n")

    last_hello_time    = 0
    last_ble_adv_time  = 0
    last_telemetry_time = 0
    last_display_time  = 0

    hello_interval     = config.HELLO_INTERVAL_S * 1000
    ble_adv_interval   = 500    # BLE advertises every 500ms independently
    telemetry_interval = 7_000
    display_interval   = 3_000

    while True:
        now = time.ticks_ms()

        # --- WiFi + LoRa HELLO (every hello_interval) ---------------------
        if time.ticks_diff(now, last_hello_time) >= hello_interval:
            last_hello_time = now

            # WiFi HELLO
            seq = metrics.record_sent("wifi")
            hello = routing.make_hello_packet()
            hello["seq_no_metric"] = seq
            wifi_link.broadcast(hello)

            # LoRa HELLO
            seq = metrics.record_sent("lora")
            hello_lora = routing.make_hello_packet()
            hello_lora["seq_no_metric"] = seq
            lora_link.broadcast(hello_lora)

            routing.purge_stale_routes()

            print(f"[Main] HELLO sent | Routes: {len(routing.ROUTING_TABLE)} "
                  f"| WiFi lat: {metrics.get_avg_latency('wifi'):.0f}ms "
                  f"| BLE lat:  {metrics.get_avg_latency('ble'):.0f}ms "
                  f"| LoRa lat: {metrics.get_avg_latency('lora'):.0f}ms "
                  f"| Samples: wifi={len(metrics._stats['wifi']['latencies'])} "
                  f"ble={len(metrics._stats['ble']['latencies'])}")

        # --- BLE advertise (every 500ms — separate from HELLO interval) ---
        if time.ticks_diff(now, last_ble_adv_time) >= ble_adv_interval:
            last_ble_adv_time = now
            seq = metrics.record_sent("ble")
            ble_link.advertise({
                "from": config.NODE_ID,
                "ts":   time.ticks_ms(),
                "s":    seq,
            })

        # --- Telemetry report (every 7s) ----------------------------------
        if time.ticks_diff(now, last_telemetry_time) >= telemetry_interval:
            last_telemetry_time = now
            telemetry.send_report()

        # --- M5StickC+ display update (every 3s) -------------------------
        if time.ticks_diff(now, last_display_time) >= display_interval:
            last_display_time = now
            stats_sender.send_stats(
                metrics.get_snapshot(),
                routing.ROUTING_TABLE,
                config.ROUTING_OBJECTIVE
            )

        time.sleep_ms(100)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
main()
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

def on_packet_received(packet: dict, sender_addr: str, link_type: str):
    """Central handler for all incoming packets regardless of link type."""
    ptype = packet.get("type")
    proto = packet.get("proto", "DSDV")

    if "ts" in packet:
        rssi = packet.get("_rssi", 0)
        metrics.record_received_timestamp(link_type, packet["ts"], rssi)

    if ptype == "HELLO" and proto == "DSDV":
        changed = routing.receive_dsdv_hello(packet, link_type)
        if changed:
            hello = routing.make_hello_packet()
            wifi_link.broadcast(hello)

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
        pong = {
            "type":    "PONG",
            "from":    config.NODE_ID,
            "seq_no":  packet.get("seq_no"),
            "orig_ts": packet.get("ts"),
            "ts":      time.ticks_ms(),
        }
        sender_node = packet.get("from")
        if sender_node:
            wifi_link.send(int(sender_node), pong)

    elif ptype == "PONG":
        seq_no = packet.get("seq_no")
        if seq_no:
            metrics.record_received(seq_no, link_type, packet.get("_rssi", 0))


# ---------------------------------------------------------------------------
# Combined listener thread — handles BOTH ports on core1
# Mesh traffic (MESH_PORT) + Telemetry (TELEMETRY_PORT, gateway only)
# Only ONE thread is started to stay within Pico W's 2-core limit
# ---------------------------------------------------------------------------

def combined_listener_thread():
    import socket

    # Mesh socket (all nodes)
    mesh_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mesh_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    mesh_sock.bind(("0.0.0.0", config.MESH_PORT))
    mesh_sock.listen(3)
    mesh_sock.settimeout(0.5)
    print(f"[WiFi] Listening on port {config.MESH_PORT}")

    # Telemetry socket (gateway only)
    telem_sock = None
    if config.NODE_ID == config.GATEWAY_NODE_ID:
        telem_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        telem_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        telem_sock.bind(("0.0.0.0", config.TELEMETRY_PORT))
        telem_sock.listen(3)
        telem_sock.settimeout(0.5)
        print(f"[Telemetry] Gateway listening on port {config.TELEMETRY_PORT}")

    while True:
        # Check mesh port
        try:
            conn, addr = mesh_sock.accept()
            data = conn.recv(512)
            conn.close()
            if data:
                try:
                    packet = json.loads(data.decode())
                    on_packet_received(packet, addr[0], "wifi")
                except Exception as e:
                    print(f"[WiFi] Parse error: {e}")
        except OSError:
            pass

        # Check telemetry port (gateway only)
        # Check telemetry port (gateway only)
        if telem_sock:
            try:
                conn, addr = telem_sock.accept()
                conn.settimeout(3)
                # Read ALL data until connection closes
                data = b""
                while True:
                    chunk = conn.recv(256)
                    if not chunk:
                        break
                    data += chunk
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

    stats_sender.init()
    lora_link.init()
    ble_link.init()

    connected = wifi_link.connect()
    if not connected:
        print("[Main] Wi-Fi failed — some features disabled")

    routing.init(config.NODE_ID, config.ROUTING_OBJECTIVE)

    is_gateway = (config.NODE_ID == config.GATEWAY_NODE_ID)
    telemetry.init(is_gateway)

    # Start ONE combined listener thread on core1
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

    last_hello_time     = 0
    last_telemetry_time = 0
    last_display_time   = 0
    hello_interval      = config.HELLO_INTERVAL_S * 1000
    telemetry_interval  = 7_000
    display_interval    = 3_000

    while True:
        now = time.ticks_ms()

        if time.ticks_diff(now, last_hello_time) >= hello_interval:
            last_hello_time = now

            seq = metrics.record_sent("wifi")
            hello_dsdv = routing.make_hello_packet()
            hello_dsdv["seq_no_metric"] = seq
            wifi_link.broadcast(hello_dsdv)

            seq = metrics.record_sent("ble")
            hello_ble = routing.make_hello_packet()
            hello_ble["seq_no_metric"] = seq
            ble_link.broadcast(hello_ble)

            seq = metrics.record_sent("lora")
            hello_lora = routing.make_hello_packet()
            hello_lora["seq_no_metric"] = seq
            lora_link.broadcast(hello_lora)

            routing.purge_stale_routes()

            print(f"[Main] HELLO sent | Routes: {len(routing.ROUTING_TABLE)} "
                  f"| WiFi lat: {metrics.get_avg_latency('wifi'):.0f}ms "
                  f"| BLE lat: {metrics.get_avg_latency('ble'):.0f}ms "
                  f"| LoRa lat: {metrics.get_avg_latency('lora'):.0f}ms")

        if time.ticks_diff(now, last_telemetry_time) >= telemetry_interval:
            last_telemetry_time = now
            telemetry.send_report()

        if time.ticks_diff(now, last_display_time) >= display_interval:
            last_display_time = now
            snap = metrics.get_snapshot()
            stats_sender.send_stats(snap, routing.ROUTING_TABLE, config.ROUTING_OBJECTIVE)

        time.sleep_ms(100)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
main()
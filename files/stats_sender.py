# =============================================================================
# m5_display.py — Push live stats to the M5StickC+ over UART
# M5StickC+ runs a companion script that reads this and renders it
# =============================================================================

from machine import UART, Pin
import json
import config

_uart = None


def init():
    global _uart
    try:
        _uart = UART(
            config.M5_UART_ID,
            baudrate=config.M5_BAUD_RATE,
            tx=Pin(config.M5_UART_TX),
            rx=Pin(config.M5_UART_RX),
        )
        print(f"[M5] UART ready (TX=GP{config.M5_UART_TX}, RX=GP{config.M5_UART_RX})")
    except Exception as e:
        print(f"[M5] UART init failed: {e}")
        _uart = None


def send_stats(metrics_snapshot: dict, routing_table: dict, objective: str):
    """Send a compact stats packet to M5StickC+ for display."""
    if not _uart:
        return

    # Build a compact summary to fit on the small screen
    best_link = _get_best_link(metrics_snapshot, objective)

    payload = {
        "node":      config.NODE_ID,
        "obj":       objective[:3].upper(),   # LAT / REL / ENE
        "best":      best_link,
        "wifi_lat":  metrics_snapshot.get("wifi", {}).get("avg_latency_ms", 0),
        "ble_lat":   metrics_snapshot.get("ble",  {}).get("avg_latency_ms", 0),
        "lora_lat":  metrics_snapshot.get("lora", {}).get("avg_latency_ms", 0),
        "wifi_pdr":  metrics_snapshot.get("wifi", {}).get("pdr_pct", 0),
        "ble_pdr":   metrics_snapshot.get("ble",  {}).get("pdr_pct", 0),
        "lora_pdr":  metrics_snapshot.get("lora", {}).get("pdr_pct", 0),
        "routes":    len(routing_table),
    }

    try:
        line = json.dumps(payload) + "\n"
        _uart.write(line.encode())
    except Exception as e:
        print(f"[M5] Send error: {e}")


def _get_best_link(metrics_snapshot: dict, objective: str) -> str:
    """Determine which link is currently performing best for the objective."""
    if objective == "latency":
        # Lowest latency wins
        scores = {
            lt: metrics_snapshot.get(lt, {}).get("avg_latency_ms", 9999)
            for lt in ["wifi", "ble", "lora"]
        }
        return min(scores, key=scores.get)

    elif objective == "reliability":
        # Highest PDR wins
        scores = {
            lt: metrics_snapshot.get(lt, {}).get("pdr_pct", 0)
            for lt in ["wifi", "ble", "lora"]
        }
        return max(scores, key=scores.get)

    elif objective == "energy":
        # Fixed energy ranking: BLE best, LoRa mid, Wi-Fi worst
        pdrs = {lt: metrics_snapshot.get(lt, {}).get("pdr_pct", 0)
                for lt in ["wifi", "ble", "lora"]}
        # Only consider links with >50% PDR
        viable = [lt for lt, pdr in pdrs.items() if pdr > 50]
        priority = ["ble", "lora", "wifi"]
        for lt in priority:
            if lt in viable:
                return lt
        return "wifi"

    return "wifi"

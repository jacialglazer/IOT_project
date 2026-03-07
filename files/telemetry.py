import json
import time
import sys
import config
import metrics
import routing

_is_gateway = False

def init(is_gateway: bool = False):
    global _is_gateway
    _is_gateway = is_gateway
    if _is_gateway:
        print("[Telemetry] This node is the GATEWAY")

def build_report() -> dict:
    snap = metrics.get_snapshot()
    # Send only essential fields to reduce packet size
    slim_metrics = {
        lt: {
            "lat": round(snap[lt]["avg_latency_ms"], 1),
            "pdr": round(snap[lt]["pdr_pct"], 1),
            "jit": round(snap[lt]["jitter_ms"], 1),
            "rss": round(snap[lt]["avg_rssi_dbm"], 1),
        }
        for lt in snap
    }
    return {
        "type":      "TELEMETRY",
        "node_id":   config.NODE_ID,
        "ts":        time.ticks_ms(),
        "metrics":   slim_metrics,
        "routes":    routing.get_table_summary(),
        "objective": config.ROUTING_OBJECTIVE,
    }

def send_report():
    report = build_report()
    if _is_gateway:
        _write_to_uart(report)
    else:
        import wifi_link
        success = wifi_link.send_telemetry(report)
        if not success:
            print("[Telemetry] Failed to reach gateway — logging locally")

def receive_and_forward(packet: dict):
    """Gateway only: forward received telemetry to laptop."""
    _write_to_uart(packet)

def _write_to_uart(data: dict):
    """Write JSON line to USB serial for analytics_engine.py to read."""
    try:
        line = json.dumps(data) + "\n"
        sys.stdout.write(line)
    except Exception as e:
        print(f"[Telemetry] Write error: {e}")
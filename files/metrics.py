# =============================================================================
# metrics.py — Per-link performance measurement
# Tracks latency, PDR, jitter, RSSI per protocol
# =============================================================================

import time

# Structure: { link_type: { "latencies": [], "sent": 0, "received": 0, ... } }
_stats = {
    "wifi": {"latencies": [], "sent": 0, "received": 0, "rssi_values": []},
    "ble":  {"latencies": [], "sent": 0, "received": 0, "rssi_values": []},
    "lora": {"latencies": [], "sent": 0, "received": 0, "rssi_values": []},
}

# Pending pings: { seq_no: (link_type, send_time_ms) }
_pending = {}
_seq_counter = 0


def record_sent(link_type: str) -> int:
    """
    Call when a HELLO/ping is sent.
    Returns seq_no to embed in the packet.
    """
    global _seq_counter
    _seq_counter += 1
    _pending[_seq_counter] = (link_type, time.ticks_ms())
    _stats[link_type]["sent"] += 1
    return _seq_counter


def record_received(seq_no: int, link_type: str, rssi: int = 0):
    """
    Call when a reply/echo is received.
    Calculates one-way latency from the round-trip.
    """
    if seq_no not in _pending:
        return

    orig_link, send_time = _pending.pop(seq_no)
    rtt_ms = time.ticks_diff(time.ticks_ms(), send_time)
    one_way_ms = rtt_ms / 2

    _stats[link_type]["received"] += 1
    _stats[link_type]["latencies"].append(one_way_ms)
    if rssi:
        _stats[link_type]["rssi_values"].append(rssi)

    # Keep only last 50 samples to save memory
    if len(_stats[link_type]["latencies"]) > 50:
        _stats[link_type]["latencies"].pop(0)
    if len(_stats[link_type]["rssi_values"]) > 50:
        _stats[link_type]["rssi_values"].pop(0)


def record_received_timestamp(link_type: str, sent_timestamp_ms: int, rssi: int = 0):
    """
    Calculate latency from embedded timestamp.
    Sanity check: reject impossibly large or negative latencies.
    """
    latency = time.ticks_diff(time.ticks_ms(), sent_timestamp_ms)
    
    # Sanity bounds per link type
    MAX_LATENCY = {
        "wifi": 2000,    # WiFi should never exceed 2 seconds
        "ble":  5000,    # BLE can be slower
        "lora": 30000,   # LoRa can be very slow
    }
    
    if latency < 0 or latency > MAX_LATENCY.get(link_type, 5000):
        return   # reject — likely a misclassified or stale packet

    _stats[link_type]["received"] += 1
    _stats[link_type]["latencies"].append(latency)
    if rssi:
        _stats[link_type]["rssi_values"].append(rssi)

    if len(_stats[link_type]["latencies"]) > 50:
        _stats[link_type]["latencies"].pop(0)


def get_avg_latency(link_type: str) -> float:
    lats = _stats[link_type]["latencies"]
    return sum(lats) / len(lats) if lats else 0.0


def get_jitter(link_type: str) -> float:
    """
    Jitter = average of absolute differences between consecutive latencies.
    RFC 3550 definition.
    """
    lats = _stats[link_type]["latencies"]
    if len(lats) < 2:
        return 0.0
    diffs = [abs(lats[i] - lats[i-1]) for i in range(1, len(lats))]
    return sum(diffs) / len(diffs)


def get_pdr(link_type: str) -> float:
    """Packet Delivery Ratio as a percentage (0–100)."""
    sent = _stats[link_type]["sent"]
    recv = _stats[link_type]["received"]
    return (recv / sent * 100) if sent > 0 else 0.0


def get_avg_rssi(link_type: str) -> float:
    vals = _stats[link_type]["rssi_values"]
    return sum(vals) / len(vals) if vals else 0.0


def get_snapshot() -> dict:
    """Return a full metrics snapshot for all link types."""
    return {
        lt: {
            "avg_latency_ms": round(get_avg_latency(lt), 2),
            "jitter_ms":      round(get_jitter(lt), 2),
            "pdr_pct":        round(get_pdr(lt), 1),
            "avg_rssi_dbm":   round(get_avg_rssi(lt), 1),
            "samples":        len(_stats[lt]["latencies"]),
        }
        for lt in _stats
    }


def reset(link_type: str = None):
    """Reset stats for one link type, or all if None."""
    targets = [link_type] if link_type else list(_stats.keys())
    for lt in targets:
        _stats[lt] = {"latencies": [], "sent": 0, "received": 0, "rssi_values": []}

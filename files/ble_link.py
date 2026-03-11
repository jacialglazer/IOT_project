# =============================================================================
# ble_link.py — BLE send/receive using compact binary advertisement
# Avoids JSON truncation by encoding only essential fields in 8 bytes
# =============================================================================

import bluetooth
import struct
import time
import config

_ble              = None
_receive_callback = None

# Magic byte to identify our mesh BLE packets vs other nearby BLE devices
MESH_MAGIC = 0xAB


# ---------------------------------------------------------------------------
# Binary encode/decode
# ---------------------------------------------------------------------------

def _encode_adv(node_id: int, ts_ms: int, seq: int) -> bytearray:
    """
    Encode mesh HELLO as compact 8-byte binary advertisement.
    Format: magic(1) + node_id(1) + ts_ms(4) + seq(2) = 8 bytes
    Total adv packet = 3 (flags) + 10 (manufacturer data) = 13 bytes
    Well within 31 byte BLE limit.
    """
    payload = struct.pack(">BBLH",
                          MESH_MAGIC,
                          node_id  & 0xFF,
                          ts_ms    & 0xFFFFFFFF,
                          seq      & 0xFFFF)
    adv  = bytearray()
    adv += bytes([2, 0x01, 0x06])            # standard BLE flags
    adv += bytes([len(payload) + 1, 0xFF])   # manufacturer specific type
    adv += payload
    return adv


def _decode_adv(adv_data: bytes):
    raw = bytes(adv_data)
    for i in range(len(raw) - 7):
        if raw[i] == MESH_MAGIC:
            try:
                magic, node_id, ts_ms, seq = struct.unpack(">BBLH", raw[i:i+8])
                if magic == MESH_MAGIC and node_id != config.NODE_ID:
                    # Validate node_id is within expected range
                    if 1 <= node_id <= 10:   # ← add this check
                        return node_id, ts_ms, seq
            except Exception:
                pass
    return None



# ---------------------------------------------------------------------------
# IRQ handler
# ---------------------------------------------------------------------------

def _irq_handler(event, data):
    """Handle BLE scan results asynchronously."""
    if event == 5:  # SCAN_RESULT
        addr_type, addr, adv_type, rssi, adv_data = data
        result = _decode_adv(bytes(adv_data))
        if result and _receive_callback:
            node_id, ts_ms, seq = result
            # Reconstruct packet dict from binary fields
            packet = {
                "type":  "HELLO",
                "proto": "DSDV",
                "from":  node_id,
                "ts":    ts_ms,
                "s":     seq,
                "table": {},
                "_rssi": rssi,
            }
            _receive_callback(packet, str(node_id), "ble")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init():
    """Initialise BLE and register IRQ handler."""
    global _ble
    _ble = bluetooth.BLE()
    _ble.active(True)
    _ble.irq(_irq_handler)
    print("[BLE] Initialised")


def set_receive_callback(callback):
    global _receive_callback
    _receive_callback = callback


def advertise(payload: dict):
    if not _ble:
        print("[BLE] advertise called but _ble is None!")
        return
    try:
        node_id  = payload.get("from") or payload.get("f") or config.NODE_ID
        ts_ms    = payload.get("ts", 0)
        seq      = payload.get("s") or payload.get("seq_no_metric", 0)
        adv_data = _encode_adv(node_id, ts_ms, seq)
        _ble.gap_advertise(config.BLE_INTERVAL_MS * 1000, adv_data)
        print(f"[BLE] Advertising node={node_id} ts={ts_ms} seq={seq} interval={config.BLE_INTERVAL_MS}ms")
    except Exception as e:
        print(f"[BLE] Advertise error: {e}")


def stop_advertise():
    if _ble:
        _ble.gap_advertise(None)


def start_scan(duration_ms=0):
    """
    Start BLE scan.
    duration_ms=0 = continuous background scan (non-blocking).
    10% duty cycle to reduce WiFi interference.
    """
    if _ble:
        # interval=100ms, window=10ms → 10% duty cycle
        _ble.gap_scan(duration_ms, 100000, 10000)
        if duration_ms == 0:
            print("[BLE] Continuous background scan started (10% duty cycle)")
        else:
            print(f"[BLE] Scanning for {duration_ms}ms...")


def stop_scan():
    if _ble:
        _ble.gap_scan(None)


def broadcast(payload: dict):
    """Advertise only — scanning runs continuously in background."""
    advertise(payload)
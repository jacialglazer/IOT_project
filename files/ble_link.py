# =============================================================================
# ble_link.py — BLE send/receive for mesh traffic using Pico W BLE
# Uses MicroPython ubluetooth module
# =============================================================================

import bluetooth
import json
import struct
import time
import config

_ble = None
_receive_callback = None
_scan_results = {}    # {addr_str: last_payload}

# Custom service/characteristic UUIDs for mesh packets
_MESH_SERVICE_UUID  = bluetooth.UUID("12345678-1234-5678-1234-56789abcdef0")
_MESH_CHAR_UUID     = bluetooth.UUID("12345678-1234-5678-1234-56789abcdef1")

# Advertisement flags
_ADV_TYPE_FLAGS             = 0x01
_ADV_TYPE_COMPLETE_LOCAL_NAME = 0x09
_ADV_TYPE_MANUFACTURER      = 0xFF


def _encode_adv(node_id: int, payload_str: str) -> bytearray:
    """
    Encode a short payload into a BLE advertisement packet.
    BLE adv is limited to 31 bytes — keep payload small.
    """
    name = f"N{node_id}:{payload_str[:20]}"   # truncate to fit
    name_bytes = name.encode()
    adv = bytearray()
    # Flags
    adv += bytes([2, _ADV_TYPE_FLAGS, 0x06])
    # Local name
    adv += bytes([len(name_bytes) + 1, _ADV_TYPE_COMPLETE_LOCAL_NAME])
    adv += name_bytes
    return adv


def _irq_handler(event, data):
    """Handle BLE IRQ events."""
    # Event 5 = SCAN_RESULT
    if event == 5:
        addr_type, addr, adv_type, rssi, adv_data = data
        addr_str = ":".join(f"{b:02x}" for b in bytes(addr))
        try:
            raw = bytes(adv_data).decode("utf-8", "ignore")
            # Find our mesh packet prefix "N<id>:"
            if "N" in raw and ":" in raw:
                idx = raw.index("N")
                payload_str = raw[idx:]
                _scan_results[addr_str] = {
                    "raw":  payload_str,
                    "rssi": rssi,
                    "time": time.ticks_ms(),
                }
                if _receive_callback:
                    # Try to decode as JSON if possible
                    try:
                        colon = payload_str.index(":")
                        json_str = payload_str[colon + 1:]
                        packet = json.loads(json_str)
                        _receive_callback(packet, addr_str, "ble")
                    except Exception:
                        pass
        except Exception:
            pass


def init():
    """Initialise BLE and register IRQ handler."""
    global _ble
    _ble = bluetooth.BLE()
    _ble.active(True)
    _ble.irq(_irq_handler)
    print("[BLE] Initialised")


def advertise(payload: dict):
    """
    Broadcast a payload via BLE advertisement.
    Other nodes will pick this up during their scan window.
    """
    if not _ble:
        return
    try:
        payload_str = json.dumps(payload)
        adv_data = _encode_adv(config.NODE_ID, payload_str)
        _ble.gap_advertise(config.BLE_INTERVAL_MS * 1000, adv_data)
    except Exception as e:
        print(f"[BLE] Advertise error: {e}")


def stop_advertise():
    if _ble:
        _ble.gap_advertise(None)


def start_scan(duration_ms=5000):
    """
    Scan for BLE advertisements from other nodes.
    Results are handled by _irq_handler → _receive_callback.
    """
    if _ble:
        _ble.gap_scan(duration_ms, 30000, 30000)
        print(f"[BLE] Scanning for {duration_ms}ms...")


def stop_scan():
    if _ble:
        _ble.gap_scan(None)


def broadcast(payload: dict):
    """Advertise payload then scan briefly to receive others."""
    advertise(payload)
    time.sleep_ms(200)
    start_scan(2000)


def set_receive_callback(callback):
    """Register function to call when a BLE packet is received."""
    global _receive_callback
    _receive_callback = callback

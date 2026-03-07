# =============================================================================
# wifi_link.py — Wi-Fi send/receive for mesh traffic
# =============================================================================

import network
import socket
import json
import time
import config

_wlan = None
_server_socket = None
_receive_callback = None   # set by main.py


def connect():
    """Connect to the shared mesh Wi-Fi AP."""
    global _wlan
    _wlan = network.WLAN(network.STA_IF)
    _wlan.active(True)

    if _wlan.isconnected():
        return True

    print(f"[WiFi] Connecting to {config.WIFI_SSID}...")
    _wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)

    timeout = 15
    while not _wlan.isconnected() and timeout > 0:
        time.sleep(1)
        timeout -= 1

    if _wlan.isconnected():
        print(f"[WiFi] Connected. IP: {_wlan.ifconfig()[0]}")
        return True
    else:
        print("[WiFi] Connection failed.")
        return False


def get_ip():
    if _wlan and _wlan.isconnected():
        return _wlan.ifconfig()[0]
    return None


def send(dest_node_id: int, payload: dict) -> bool:
    dest_ip = config.NODE_IPS.get(dest_node_id)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect((dest_ip, config.MESH_PORT))
        s.send(json.dumps(payload).encode())
        s.close()
        print(f"[WiFi] ✓ Sent to node {dest_node_id} ({dest_ip})")  # ← add this
        return True
    except Exception as e:
        print(f"[WiFi] Send to {dest_node_id} failed: {e}")
        return False



def broadcast(payload: dict):
    """Send payload to ALL other nodes via Wi-Fi."""
    for node_id in config.NODE_IPS:
        if node_id != config.NODE_ID:
            send(node_id, payload)


def send_telemetry(payload: dict) -> bool:
    gateway_ip = config.NODE_IPS.get(config.GATEWAY_NODE_ID)
    if not gateway_ip:
        return False
    
    for attempt in range(3):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((gateway_ip, config.TELEMETRY_PORT))
            data = json.dumps(payload).encode()
            s.send(data)
            s.close()   # ← explicit close signals end of transmission
            print(f"[WiFi] Telemetry sent to gateway")
            return True
        except Exception as e:
            print(f"[WiFi] Telemetry attempt {attempt+1} failed: {e}")
            time.sleep(1)
    
    return False

def start_listener(callback):
    global _server_socket, _receive_callback
    _receive_callback = callback

    while True:  # ← outer loop restarts listener if it crashes
        try:
            _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            _server_socket.bind(("0.0.0.0", config.MESH_PORT))
            _server_socket.listen(5)
            _server_socket.settimeout(1)
            print(f"[WiFi] Listening on port {config.MESH_PORT}")

            while True:
                try:
                    conn, addr = _server_socket.accept()
                    data = conn.recv(512)
                    conn.close()
                    if data:
                        try:
                            packet = json.loads(data.decode())
                            _receive_callback(packet, addr[0], "wifi")
                        except Exception as e:
                            print(f"[WiFi] Parse error: {e}")
                except OSError:
                    pass  # timeout, loop again

        except Exception as e:
            print(f"[WiFi] Listener crashed: {e} — restarting")
            time.sleep(1)  # brief pause before restart

# def start_listener(callback):
#     """
#     Start a blocking TCP listener on MESH_PORT.
#     Calls callback(packet_dict, sender_ip) for each received packet.
#     Run this in a thread or as the main loop.
#     """
#     global _server_socket, _receive_callback
#     _receive_callback = callback
# 
#     _server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#     _server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#     _server_socket.bind(("0.0.0.0", config.MESH_PORT))
#     _server_socket.listen(5)
#     print(f"[WiFi] Listening on port {config.MESH_PORT}")
# 
#     while True:
#         try:
#             conn, addr = _server_socket.accept()
#             data = conn.recv(512)
#             conn.close()
#             if data:
#                 try:
#                     packet = json.loads(data.decode())
#                     _receive_callback(packet, addr[0], "wifi")
#                 except Exception as e:
#                     print(f"[WiFi] Parse error: {e}")
#         except Exception as e:
#             print(f"[WiFi] Listener error: {e}")


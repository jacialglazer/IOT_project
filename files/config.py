# =============================================================================
# config.py — Per-node configuration
# EDIT THESE VALUES for each physical node before flashing
# =============================================================================

# --- CHANGE THIS PER NODE (1 through 5) --------------------------------------
NODE_ID = 1

# --- GATEWAY NODE ------------------------------------------------------------
# Set to the NODE_ID of whichever node is physically connected to the laptop
GATEWAY_NODE_ID = 5

# --- Wi-Fi -------------------------------------------------------------------
# All nodes + gateway join the same AP (use a router or one node in AP mode)
WIFI_SSID = "Javiersphone"
WIFI_PASSWORD = "imcool123"

# Static IPs per node — must match your router's DHCP reservations
NODE_IPS = {
    1: "192.168.4.101",
    2: "192.168.4.102",
    3: "192.168.4.103",
    4: "192.168.4.104",
    5: "192.168.4.105",
}

# Ports
MESH_PORT      = 5000   # inter-node mesh traffic
TELEMETRY_PORT = 6000   # telemetry reports to gateway

# --- BLE ---------------------------------------------------------------------
BLE_INTERVAL_MS = 100   # advertisement interval

# --- LoRa RFM (SPI pins on Pico W) ------------------------------------------
LORA_SCK  = 10
LORA_MOSI = 11
LORA_MISO = 12
LORA_CS   = 13
LORA_RST  = 14
LORA_IRQ  = 15
LORA_FREQ = 915.0       # MHz — change to 868.0 for EU

# --- Routing -----------------------------------------------------------------
HELLO_INTERVAL_S  = 5   # how often to broadcast HELLO packets
ROUTE_TIMEOUT_S   = 30  # remove stale routes after this many seconds

# Routing objectives — set which metric to optimise
# Options: "latency" | "reliability" | "energy"
ROUTING_OBJECTIVE = "latency"

# --- Measured link costs (Phase 1 results — update after experiments) --------
# These start as estimates; replace with your real measured values
LINK_COSTS = {
    "latency": {
        "wifi": 10,
        "ble":  50,
        "lora": 800,
    },
    "reliability": {     # lower = more reliable (inverse PDR loss %)
        "wifi": 5,
        "ble":  20,
        "lora": 15,
    },
    "energy": {          # relative energy cost per packet
        "wifi": 80,
        "ble":  10,
        "lora": 20,
    },
}

# --- M5StickC+ ---------------------------------------------------------------
# M5StickC+ connects to Pico W via UART
M5_UART_ID   = 1
M5_UART_TX   = 4        # Pico W GP4 → M5StickC+ RX
M5_UART_RX   = 5        # Pico W GP5 ← M5StickC+ TX
M5_BAUD_RATE = 115200

# --- Telemetry (gateway node only) -------------------------------------------
LAPTOP_BAUD_RATE = 115200   # USB serial to laptop

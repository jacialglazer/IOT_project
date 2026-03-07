# =============================================================================
# m5stick_display.py — Runs ON the M5StickC+
# Reads stats from Pico W via UART and renders them on the screen
# Flash this separately onto each M5StickC+
# Uses UIFlow MicroPython (M5Stack's MicroPython build)
# =============================================================================

from m5stack import *
from m5ui import *
from uiflow import *
import uart
import json

# Screen setup (M5StickC+ is 135×240)
setScreenColor(0x000000)

# --- UI Labels ---------------------------------------------------------------
lbl_title   = M5TextBox(5,   5,  "NODE --",       lcd.FONT_Ubuntu,  0x00BFFF, rotate=0)
lbl_obj     = M5TextBox(5,  30,  "OBJ: ---",      lcd.FONT_Default, 0xFFFFFF, rotate=0)
lbl_best    = M5TextBox(5,  50,  "BEST: ---",     lcd.FONT_Default, 0x00FF00, rotate=0)

lbl_wifi    = M5TextBox(5,  80,  "WiFi",          lcd.FONT_Default, 0x4FC3F7, rotate=0)
lbl_wifi_l  = M5TextBox(5,  95,  "  Lat: --ms",   lcd.FONT_Default, 0xFFFFFF, rotate=0)
lbl_wifi_p  = M5TextBox(5, 110,  "  PDR: --%",    lcd.FONT_Default, 0xFFFFFF, rotate=0)

lbl_ble     = M5TextBox(5, 130,  "BLE",           lcd.FONT_Default, 0xA5D6A7, rotate=0)
lbl_ble_l   = M5TextBox(5, 145,  "  Lat: --ms",   lcd.FONT_Default, 0xFFFFFF, rotate=0)
lbl_ble_p   = M5TextBox(5, 160,  "  PDR: --%",    lcd.FONT_Default, 0xFFFFFF, rotate=0)

lbl_lora    = M5TextBox(5, 180,  "LoRa",          lcd.FONT_Default, 0xFFCC80, rotate=0)
lbl_lora_l  = M5TextBox(5, 195,  "  Lat: --ms",   lcd.FONT_Default, 0xFFFFFF, rotate=0)
lbl_lora_p  = M5TextBox(5, 210,  "  PDR: --%",    lcd.FONT_Default, 0xFFFFFF, rotate=0)

lbl_routes  = M5TextBox(5, 230,  "Routes: -",     lcd.FONT_Default, 0xCCCCCC, rotate=0)

LINK_COLOURS = {
    "wifi": 0x4FC3F7,   # blue
    "ble":  0xA5D6A7,   # green
    "lora": 0xFFCC80,   # orange
}

# UART from Pico W (RX on M5StickC+ = GPIO33 in UIFlow)
uart1 = uart.Uart(1, 115200)
buf   = ""


def update_display(data: dict):
    node_id  = data.get("node", "?")
    obj      = data.get("obj", "---")
    best     = data.get("best", "---").upper()
    best_col = LINK_COLOURS.get(data.get("best", "wifi"), 0xFFFFFF)

    lbl_title.setText(f"NODE {node_id}")
    lbl_obj.setText(f"OBJ: {obj}")
    lbl_best.setText(f"BEST: {best}")
    lbl_best.setColor(best_col)

    lbl_wifi_l.setText(f"  Lat: {data.get('wifi_lat', '--'):.0f}ms")
    lbl_wifi_p.setText(f"  PDR: {data.get('wifi_pdr', '--'):.0f}%")

    lbl_ble_l.setText(f"  Lat: {data.get('ble_lat', '--'):.0f}ms")
    lbl_ble_p.setText(f"  PDR: {data.get('ble_pdr', '--'):.0f}%")

    lbl_lora_l.setText(f"  Lat: {data.get('lora_lat', '--'):.0f}ms")
    lbl_lora_p.setText(f"  PDR: {data.get('lora_pdr', '--'):.0f}%")

    lbl_routes.setText(f"Routes: {data.get('routes', '-')}")


# Main loop — read UART line by line
while True:
    if uart1.available():
        char = uart1.read(1).decode("utf-8", "ignore")
        if char == "\n":
            try:
                data = json.loads(buf.strip())
                update_display(data)
            except Exception as e:
                pass   # malformed line, ignore
            buf = ""
        else:
            buf += char

    wait_ms(10)

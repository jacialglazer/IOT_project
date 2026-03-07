# =============================================================================
# lora_link.py — Real LoRa RFM95/96 via SPI on Pico W
# Compatible with RFM95W (SX1276) shield
# =============================================================================

from machine import SPI, Pin
import json
import time
import config

# SX1276 Register addresses
_REG_FIFO                = 0x00
_REG_OP_MODE             = 0x01
_REG_FRF_MSB             = 0x06
_REG_FRF_MID             = 0x07
_REG_FRF_LSB             = 0x08
_REG_PA_CONFIG           = 0x09
_REG_LNA                 = 0x0C
_REG_FIFO_ADDR_PTR       = 0x0D
_REG_FIFO_TX_BASE_ADDR   = 0x0E
_REG_FIFO_RX_BASE_ADDR   = 0x0F
_REG_FIFO_RX_CURRENT_ADDR= 0x10
_REG_IRQ_FLAGS           = 0x12
_REG_RX_NB_BYTES         = 0x13
_REG_PKT_SNR_VALUE       = 0x19
_REG_PKT_RSSI_VALUE      = 0x1A
_REG_MODEM_CONFIG_1      = 0x1D
_REG_MODEM_CONFIG_2      = 0x1E
_REG_PREAMBLE_MSB        = 0x20
_REG_PREAMBLE_LSB        = 0x21
_REG_PAYLOAD_LENGTH      = 0x22
_REG_MODEM_CONFIG_3      = 0x26
_REG_DETECTION_OPTIMIZE  = 0x31
_REG_DETECTION_THRESHOLD = 0x37
_REG_SYNC_WORD           = 0x39
_REG_DIO_MAPPING_1       = 0x40
_REG_VERSION             = 0x42

# Operating modes
_MODE_LONG_RANGE = 0x80
_MODE_SLEEP      = 0x00
_MODE_STDBY      = 0x01
_MODE_TX         = 0x03
_MODE_RX_CONT    = 0x05

# IRQ flags
_IRQ_TX_DONE    = 0x08
_IRQ_RX_DONE    = 0x40
_IRQ_CRC_ERROR  = 0x20

_spi = None
_cs  = None
_rst = None
_irq = None
_receive_callback = None


def _write_reg(reg, value):
    _cs.value(0)
    _spi.write(bytes([reg | 0x80, value]))
    _cs.value(1)


def _read_reg(reg) -> int:
    _cs.value(0)
    _spi.write(bytes([reg & 0x7F]))
    result = _spi.read(1)
    _cs.value(1)
    return result[0]


def _set_frequency(freq_mhz: float):
    frf = int((freq_mhz * 1e6) / 61.03515625)
    _write_reg(_REG_FRF_MSB, (frf >> 16) & 0xFF)
    _write_reg(_REG_FRF_MID, (frf >> 8)  & 0xFF)
    _write_reg(_REG_FRF_LSB,  frf        & 0xFF)


def init():
    """Initialise the RFM95 LoRa module over SPI."""
    global _spi, _cs, _rst, _irq

    _spi = SPI(1,
               baudrate=1_000_000,
               polarity=0,
               phase=0,
               sck=Pin(config.LORA_SCK),
               mosi=Pin(config.LORA_MOSI),
               miso=Pin(config.LORA_MISO))

    _cs  = Pin(config.LORA_CS,  Pin.OUT)
    _rst = Pin(config.LORA_RST, Pin.OUT)
    _irq = Pin(config.LORA_IRQ, Pin.IN)

    # Hardware reset
    _rst.value(0)
    time.sleep_ms(10)
    _rst.value(1)
    time.sleep_ms(10)

    version = _read_reg(_REG_VERSION)
    if version != 0x12:
        print(f"[LoRa] WARNING: Unexpected chip version 0x{version:02X} (expected 0x12)")
    else:
        print("[LoRa] SX1276 detected OK")

    # Switch to sleep mode to configure
    _write_reg(_REG_OP_MODE, _MODE_LONG_RANGE | _MODE_SLEEP)
    time.sleep_ms(10)

    _set_frequency(config.LORA_FREQ)

    # FIFO base addresses
    _write_reg(_REG_FIFO_TX_BASE_ADDR, 0x00)
    _write_reg(_REG_FIFO_RX_BASE_ADDR, 0x00)

    # LNA max gain, boost on
    _write_reg(_REG_LNA, _read_reg(_REG_LNA) | 0x03)

    # Modem config: BW=125kHz, CR=4/5, explicit header
    _write_reg(_REG_MODEM_CONFIG_1, 0x72)
    # SF=7, CRC on
    _write_reg(_REG_MODEM_CONFIG_2, 0x74)
    # AGC on
    _write_reg(_REG_MODEM_CONFIG_3, 0x04)

    # Max output power
    _write_reg(_REG_PA_CONFIG, 0x8F)

    # Sync word (0x12 = private network)
    _write_reg(_REG_SYNC_WORD, 0x12)

    # Standby
    _write_reg(_REG_OP_MODE, _MODE_LONG_RANGE | _MODE_STDBY)
    print(f"[LoRa] Ready at {config.LORA_FREQ} MHz")


def send(payload: dict) -> bool:
    """
    Transmit a JSON payload over LoRa.
    Blocking — waits for TX done IRQ.
    Returns True on success.
    """
    try:
        data = json.dumps(payload).encode()
        if len(data) > 255:
            print("[LoRa] Payload too large")
            return False

        # Standby mode
        _write_reg(_REG_OP_MODE, _MODE_LONG_RANGE | _MODE_STDBY)

        # Reset FIFO pointer
        _write_reg(_REG_FIFO_ADDR_PTR, 0x00)

        # Write payload to FIFO
        _cs.value(0)
        _spi.write(bytes([_REG_FIFO | 0x80]))
        _spi.write(data)
        _cs.value(1)

        _write_reg(_REG_PAYLOAD_LENGTH, len(data))

        # Map DIO0 to TX done
        _write_reg(_REG_DIO_MAPPING_1, 0x40)

        # TX mode
        _write_reg(_REG_OP_MODE, _MODE_LONG_RANGE | _MODE_TX)

        # Wait for TX done (timeout 5s)
        timeout = 5000
        while timeout > 0:
            if _read_reg(_REG_IRQ_FLAGS) & _IRQ_TX_DONE:
                break
            time.sleep_ms(1)
            timeout -= 1

        # Clear IRQ flags
        _write_reg(_REG_IRQ_FLAGS, 0xFF)
        return timeout > 0

    except Exception as e:
        print(f"[LoRa] Send error: {e}")
        return False


def broadcast(payload: dict) -> bool:
    """LoRa is inherently broadcast — just send."""
    return send(payload)


def receive_once(timeout_ms=5000) -> dict | None:
    """
    Listen for a single LoRa packet.
    Returns parsed dict or None on timeout/error.
    """
    try:
        # Clear IRQ flags
        _write_reg(_REG_IRQ_FLAGS, 0xFF)

        # Map DIO0 to RX done
        _write_reg(_REG_DIO_MAPPING_1, 0x00)

        # Continuous RX mode
        _write_reg(_REG_OP_MODE, _MODE_LONG_RANGE | _MODE_RX_CONT)

        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            flags = _read_reg(_REG_IRQ_FLAGS)

            if flags & _IRQ_RX_DONE:
                if flags & _IRQ_CRC_ERROR:
                    _write_reg(_REG_IRQ_FLAGS, 0xFF)
                    return None

                nb_bytes    = _read_reg(_REG_RX_NB_BYTES)
                current_addr = _read_reg(_REG_FIFO_RX_CURRENT_ADDR)
                _write_reg(_REG_FIFO_ADDR_PTR, current_addr)

                _cs.value(0)
                _spi.write(bytes([_REG_FIFO & 0x7F]))
                raw = _spi.read(nb_bytes)
                _cs.value(1)

                _write_reg(_REG_IRQ_FLAGS, 0xFF)

                rssi = _read_reg(_REG_PKT_RSSI_VALUE) - 157
                snr  = _read_reg(_REG_PKT_SNR_VALUE) / 4.0

                packet = json.loads(bytes(raw).decode())
                packet["_rssi"] = rssi
                packet["_snr"]  = snr
                return packet

            time.sleep_ms(10)

        # Standby after listen
        _write_reg(_REG_OP_MODE, _MODE_LONG_RANGE | _MODE_STDBY)
        return None

    except Exception as e:
        print(f"[LoRa] Receive error: {e}")
        return None


def start_continuous_receive(callback):
    """
    Continuously receive LoRa packets and call callback(packet, "lora").
    Run this in a thread.
    """
    global _receive_callback
    _receive_callback = callback
    print("[LoRa] Starting continuous receive loop")

    while True:
        packet = receive_once(timeout_ms=10000)
        if packet and _receive_callback:
            sender = packet.get("from", "unknown")
            _receive_callback(packet, sender, "lora")

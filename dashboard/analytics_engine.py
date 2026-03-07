#!/usr/bin/env python3
# =============================================================================
# analytics_engine.py — Laptop-side engine
# Reads telemetry from Node 5 (gateway) via USB serial → stores in SQLite
# Run this before opening the dashboard
#
# Install dependencies:
#   pip install pyserial
#
# Usage:
#   python analytics_engine.py --port /dev/ttyUSB0   (Linux/Mac)
#   python analytics_engine.py --port COM3            (Windows)
# =============================================================================

import serial
import sqlite3
import json
import time
import argparse
import sys
import os
from datetime import datetime

DB_PATH = "mesh_metrics.db"


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            wall_time   TEXT,
            node_id     INTEGER,
            ts_ms       INTEGER,
            objective   TEXT
        );

        CREATE TABLE IF NOT EXISTS link_metrics (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telemetry_id    INTEGER REFERENCES telemetry(id),
            link_type       TEXT,
            avg_latency_ms  REAL,
            jitter_ms       REAL,
            pdr_pct         REAL,
            avg_rssi_dbm    REAL,
            samples         INTEGER
        );

        CREATE TABLE IF NOT EXISTS routes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telemetry_id    INTEGER REFERENCES telemetry(id),
            dest_node       INTEGER,
            next_hop        INTEGER,
            link_type       TEXT,
            cost            REAL
        );
    """)
    conn.commit()
    print(f"[DB] Initialised at {DB_PATH}")


def insert_telemetry(conn, packet):
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO telemetry (wall_time, node_id, ts_ms, objective)
        VALUES (?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        packet.get("node_id"),
        packet.get("ts"),
        packet.get("objective", "latency"),
    ))
    tel_id = cur.lastrowid

    # Handle both full and slim metric formats
    for link_type, m in packet.get("metrics", {}).items():
        cur.execute("""
            INSERT INTO link_metrics
              (telemetry_id, link_type, avg_latency_ms, jitter_ms,
               pdr_pct, avg_rssi_dbm, samples)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            tel_id, link_type,
            m.get("avg_latency_ms") or m.get("lat", 0),
            m.get("jitter_ms")      or m.get("jit", 0),
            m.get("pdr_pct")        or m.get("pdr", 0),
            m.get("avg_rssi_dbm")   or m.get("rss", 0),
            m.get("samples", 0),
        ))

    for dest_str, route in packet.get("routes", {}).items():
        cur.execute("""
            INSERT INTO routes
              (telemetry_id, dest_node, next_hop, link_type, cost)
            VALUES (?, ?, ?, ?, ?)
        """, (
            tel_id, int(dest_str),
            route.get("next_hop"),
            route.get("link"),
            route.get("cost", 0),
        ))

    conn.commit()


# ---------------------------------------------------------------------------
# Serial reader
# ---------------------------------------------------------------------------

def find_port() -> str:
    """Try to auto-detect the Pico W serial port."""
    candidates = []

    if sys.platform == "win32":
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            if "USB" in p.description or "Pico" in p.description:
                candidates.append(p.device)
    else:
        import glob
        candidates = (
            glob.glob("/dev/ttyUSB*") +
            glob.glob("/dev/ttyACM*") +
            glob.glob("/dev/cu.usbmodem*")
        )

    if candidates:
        print(f"[Serial] Auto-detected ports: {candidates}")
        return candidates[0]

    return None


def run(port: str, baud: int = 115200):
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    print(f"[Serial] Opening {port} at {baud} baud...")
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except serial.SerialException as e:
        print(f"[Serial] ERROR: {e}")
        print("  Check your port with: python -m serial.tools.list_ports")
        sys.exit(1)

    print(f"[Serial] Listening. Press Ctrl+C to stop.\n")
    buf = ""
    packet_count = 0

    try:
        while True:
            raw = ser.read(256)
            if not raw:
                continue

            buf += raw.decode("utf-8", errors="ignore")

            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                try:
                    packet = json.loads(line)

                    if packet.get("type") == "TELEMETRY":
                        insert_telemetry(conn, packet)
                        packet_count += 1
                        node = packet.get("node_id", "?")
                        obj  = packet.get("objective", "?")
                        m    = packet.get("metrics", {})
                        print(
                            f"[{datetime.now().strftime('%H:%M:%S')}] "
                            f"Node {node} | {obj} | "
                            f"WiFi {m.get('wifi',{}).get('avg_latency_ms',0):.0f}ms | "
                            f"BLE {m.get('ble',{}).get('avg_latency_ms',0):.0f}ms | "
                            f"LoRa {m.get('lora',{}).get('avg_latency_ms',0):.0f}ms | "
                            f"Total packets: {packet_count}"
                        )
                    else:
                        # Print non-telemetry packets as debug info
                        print(f"[Debug] {line}")

                except json.JSONDecodeError:
                    print(f"[Parse] Bad line: {line[:80]}")

    except KeyboardInterrupt:
        print(f"\n[Engine] Stopped. {packet_count} packets logged to {DB_PATH}")
    finally:
        ser.close()
        conn.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mesh analytics engine")
    parser.add_argument("--port", help="Serial port (e.g. /dev/ttyUSB0 or COM3)")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    port = args.port or find_port()
    if not port:
        print("ERROR: Could not find serial port. Specify with --port")
        sys.exit(1)

    run(port, args.baud)

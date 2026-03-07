#!/usr/bin/env python3
# =============================================================================
# dashboard_server.py — Serves dashboard data from SQLite over HTTP
# Run alongside analytics_engine.py
#
# Install dependencies:
#   pip install flask flask-cors
#
# Usage:
#   python dashboard_server.py
#   Then open dashboard.html in your browser
# =============================================================================

from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import json
import os

DB_PATH = "mesh_metrics.db"

app = Flask(__name__)
CORS(app)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/latest")
def latest():
    """Latest metrics snapshot for all nodes."""
    conn = get_db()
    rows = conn.execute("""
        SELECT t.node_id, t.objective, t.wall_time,
               lm.link_type, lm.avg_latency_ms, lm.jitter_ms,
               lm.pdr_pct, lm.avg_rssi_dbm, lm.samples
        FROM telemetry t
        JOIN link_metrics lm ON lm.telemetry_id = t.id
        WHERE t.id IN (
            SELECT MAX(id) FROM telemetry GROUP BY node_id
        )
        ORDER BY t.node_id, lm.link_type
    """).fetchall()
    conn.close()

    # Group by node
    nodes = {}
    for r in rows:
        nid = r["node_id"]
        if nid not in nodes:
            nodes[nid] = {"node_id": nid, "objective": r["objective"],
                          "wall_time": r["wall_time"], "links": {}}
        nodes[nid]["links"][r["link_type"]] = {
            "avg_latency_ms": r["avg_latency_ms"],
            "jitter_ms":      r["jitter_ms"],
            "pdr_pct":        r["pdr_pct"],
            "avg_rssi_dbm":   r["avg_rssi_dbm"],
            "samples":        r["samples"],
        }
    return jsonify(list(nodes.values()))


@app.route("/api/history")
def history():
    """Time-series data for a specific node and link type."""
    node_id   = request.args.get("node", 1, type=int)
    link_type = request.args.get("link", "wifi")
    limit     = request.args.get("limit", 50, type=int)

    conn = get_db()
    rows = conn.execute("""
        SELECT t.wall_time, lm.avg_latency_ms, lm.jitter_ms,
               lm.pdr_pct, lm.avg_rssi_dbm
        FROM telemetry t
        JOIN link_metrics lm ON lm.telemetry_id = t.id
        WHERE t.node_id = ? AND lm.link_type = ?
        ORDER BY t.id DESC
        LIMIT ?
    """, (node_id, link_type, limit)).fetchall()
    conn.close()

    return jsonify([dict(r) for r in reversed(rows)])


@app.route("/api/routes")
def routes():
    """Latest routing table snapshot for all nodes."""
    conn = get_db()
    rows = conn.execute("""
        SELECT r.dest_node, r.next_hop, r.link_type, r.cost,
               t.node_id, t.objective
        FROM routes r
        JOIN telemetry t ON t.id = r.telemetry_id
        WHERE t.id IN (
            SELECT MAX(id) FROM telemetry GROUP BY node_id
        )
        ORDER BY t.node_id, r.dest_node
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/comparison")
def comparison():
    """Average metrics per link type across all nodes and time."""
    conn = get_db()
    rows = conn.execute("""
        SELECT lm.link_type,
               AVG(lm.avg_latency_ms) as avg_lat,
               AVG(lm.jitter_ms)      as avg_jitter,
               AVG(lm.pdr_pct)        as avg_pdr,
               AVG(lm.avg_rssi_dbm)   as avg_rssi,
               COUNT(*)               as data_points
        FROM link_metrics lm
        GROUP BY lm.link_type
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats")
def stats():
    """Overall database stats."""
    conn = get_db()
    total    = conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    nodes    = conn.execute("SELECT COUNT(DISTINCT node_id) FROM telemetry").fetchone()[0]
    earliest = conn.execute("SELECT MIN(wall_time) FROM telemetry").fetchone()[0]
    latest_t = conn.execute("SELECT MAX(wall_time) FROM telemetry").fetchone()[0]
    conn.close()
    return jsonify({
        "total_packets": total,
        "active_nodes":  nodes,
        "earliest":      earliest,
        "latest":        latest_t,
    })


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        print(f"WARNING: {DB_PATH} not found.")
        print("Start analytics_engine.py first to collect data.")
        print("Starting server anyway for testing...\n")
    print("Dashboard server running at http://localhost:5050")
    print("Open dashboard.html in your browser.\n")
    app.run(host="0.0.0.0", port=5050, debug=False)

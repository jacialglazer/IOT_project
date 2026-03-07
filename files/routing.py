# =============================================================================
# routing.py — DSDV proactive routing engine
# Manages routing table and HELLO packet logic
# =============================================================================

import time
import config

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

# DSDV routing table
# { dest_node_id: {next_hop, link, cost, seq_no, last_updated} }
ROUTING_TABLE = {}

# OLSR topology table
# { node_id: { neighbour_id: {link, cost} } }
TOPOLOGY_TABLE = {}

# OLSR MPR set — neighbours WE selected as multipoint relays
MPR_SET = set()

_node_id   = None
_seq_no    = 0          # our own sequence number (DSDV)
_objective = "latency"  # current routing objective


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init(node_id: int, objective: str = None):
    global _node_id, _objective
    _node_id   = node_id
    _objective = objective or config.ROUTING_OBJECTIVE

    # Seed table with ourselves
    ROUTING_TABLE[_node_id] = {
        "next_hop":    _node_id,
        "link":        "local",
        "cost":        0,
        "seq_no":      0,
        "last_updated": time.ticks_ms(),
    }
    print(f"[Routing] Initialised node {_node_id}, objective={_objective}")


def set_objective(objective: str):
    """Change routing objective at runtime and trigger re-evaluation."""
    global _objective
    _objective = objective
    _recompute_all_costs()
    print(f"[Routing] Objective changed to {_objective}")


def _get_cost(link_type: str) -> float:
    """Look up cost for a link type under current objective."""
    return config.LINK_COSTS.get(_objective, {}).get(link_type, 999)


# ---------------------------------------------------------------------------
# DSDV
# ---------------------------------------------------------------------------

def make_hello_packet() -> dict:
    """Build a DSDV HELLO packet containing our current routing table."""
    global _seq_no
    _seq_no += 2   # DSDV uses even numbers for live updates

    # Serialise routing table — omit internal fields
    table_export = {}
    for dest, entry in ROUTING_TABLE.items():
        table_export[str(dest)] = {
            "cost":   entry["cost"],
            "seq_no": entry["seq_no"],
        }

    return {
        "type":    "HELLO",
        "proto":   "DSDV",
        "from":    _node_id,
        "seq_no":  _seq_no,
        "ts":      time.ticks_ms(),
        "table":   table_export,
    }


def receive_dsdv_hello(packet: dict, received_via_link: str) -> bool:
    """
    Process a DSDV HELLO from a neighbour.
    Updates routing table if cheaper/fresher routes are found.
    Returns True if table changed (triggers re-broadcast).
    """
    sender      = int(packet["from"])
    their_table = packet["table"]
    link_cost   = _get_cost(received_via_link)
    changed     = False

    # First, update direct route to sender
    direct_seq = packet.get("seq_no", 0)
    existing   = ROUTING_TABLE.get(sender)
    if (existing is None
            or direct_seq > existing["seq_no"]
            or (direct_seq == existing["seq_no"] and link_cost < existing["cost"])):
        ROUTING_TABLE[sender] = {
            "next_hop":     sender,
            "link":         received_via_link,
            "cost":         link_cost,
            "seq_no":       direct_seq,
            "last_updated": time.ticks_ms(),
        }
        changed = True

    # Then, update routes reachable VIA sender
    for dest_str, entry in their_table.items():
        dest    = int(dest_str)
        if dest == _node_id:
            continue

        new_cost = entry["cost"] + link_cost
        new_seq  = entry["seq_no"]
        existing = ROUTING_TABLE.get(dest)

        if (existing is None
                or new_seq > existing["seq_no"]
                or (new_seq == existing["seq_no"] and new_cost < existing["cost"])):
            ROUTING_TABLE[dest] = {
                "next_hop":     sender,
                "link":         received_via_link,
                "cost":         new_cost,
                "seq_no":       new_seq,
                "last_updated": time.ticks_ms(),
            }
            changed = True

    return changed


# # ---------------------------------------------------------------------------
# # OLSR
# # ---------------------------------------------------------------------------

# def make_olsr_hello() -> dict:
#     """Build an OLSR HELLO declaring our neighbours."""
#     neighbours = {
#         str(nid): {
#             "link": entry["link"],
#             "cost": entry["cost"],
#         }
#         for nid, entry in ROUTING_TABLE.items()
#         if nid != _node_id and entry["link"] != "local"
#     }
#     return {
#         "type":       "HELLO",
#         "proto":      "OLSR",
#         "from":       _node_id,
#         "ts":         time.ticks_ms(),
#         "neighbours": neighbours,
#         "mprs":       list(MPR_SET),
#     }


# def make_olsr_tc() -> dict:
#     """Build an OLSR Topology Control (TC) message."""
#     return {
#         "type":   "TC",
#         "proto":  "OLSR",
#         "from":   _node_id,
#         "ts":     time.ticks_ms(),
#         "links":  {
#             str(nid): {
#                 "link": entry["link"],
#                 "cost": entry["cost"],
#             }
#             for nid, entry in ROUTING_TABLE.items()
#             if nid != _node_id and entry["link"] != "local"
#         },
#     }


# def receive_olsr_hello(packet: dict, received_via_link: str):
#     """Process OLSR HELLO — update topology table and reselect MPRs."""
#     sender = int(packet["from"])
#     link_cost = _get_cost(received_via_link)

#     # Update direct link to sender
#     if sender not in TOPOLOGY_TABLE:
#         TOPOLOGY_TABLE[sender] = {}
#     TOPOLOGY_TABLE[sender][_node_id] = {
#         "link": received_via_link,
#         "cost": link_cost,
#     }

#     # Update sender's neighbour info in topology table
#     for nbr_str, info in packet.get("neighbours", {}).items():
#         nbr = int(nbr_str)
#         if sender not in TOPOLOGY_TABLE:
#             TOPOLOGY_TABLE[sender] = {}
#         TOPOLOGY_TABLE[sender][nbr] = info

#     _select_mprs()
#     _dijkstra()


# def receive_olsr_tc(packet: dict, received_via_link: str):
#     """Process OLSR TC message — update topology and recompute routes."""
#     originator = int(packet["from"])

#     if originator not in TOPOLOGY_TABLE:
#         TOPOLOGY_TABLE[originator] = {}

#     for dest_str, info in packet.get("links", {}).items():
#         dest = int(dest_str)
#         TOPOLOGY_TABLE[originator][dest] = info

#     _dijkstra()


# def _select_mprs():
#     """
#     Select minimum set of 1-hop neighbours (MPRs) that cover all 2-hop neighbours.
#     Greedy set cover algorithm.
#     """
#     one_hop = set(
#         nid for nid, entry in ROUTING_TABLE.items()
#         if nid != _node_id and entry["link"] != "local"
#     )

#     two_hop = set()
#     for n in one_hop:
#         two_hop.update(TOPOLOGY_TABLE.get(n, {}).keys())
#     two_hop -= {_node_id}
#     two_hop -= one_hop

#     MPR_SET.clear()
#     uncovered = two_hop.copy()

#     while uncovered:
#         best = max(
#             one_hop - MPR_SET,
#             key=lambda n: len(uncovered & set(TOPOLOGY_TABLE.get(n, {}).keys())),
#             default=None,
#         )
#         if best is None:
#             break
#         MPR_SET.add(best)
#         uncovered -= set(TOPOLOGY_TABLE.get(best, {}).keys())


# def _dijkstra():
#     """Run Dijkstra on topology table to rebuild full routing table."""
#     import heapq

#     dist = {_node_id: 0}
#     prev = {}
#     pq   = [(0, _node_id)]

#     while pq:
#         cost, u = heapq.heappop(pq)
#         if cost > dist.get(u, float("inf")):
#             continue
#         for v, info in TOPOLOGY_TABLE.get(u, {}).items():
#             link_cost = info.get("cost", _get_cost(info.get("link", "wifi")))
#             new_cost  = cost + link_cost
#             if new_cost < dist.get(v, float("inf")):
#                 dist[v] = new_cost
#                 prev[v] = (u, info.get("link", "wifi"))
#                 heapq.heappush(pq, (new_cost, v))

#     # Rebuild routing table from Dijkstra results
#     for dest in dist:
#         if dest == _node_id:
#             continue
#         # Trace back to find the first hop from us
#         hop  = dest
#         link = "wifi"
#         while prev.get(hop, (None,))[0] != _node_id:
#             if hop not in prev:
#                 break
#             link = prev[hop][1]
#             hop  = prev[hop][0]

#         if hop in prev or hop == dest:
#             final_link = prev.get(hop, (None, link))[1]
#             ROUTING_TABLE[dest] = {
#                 "next_hop":     hop,
#                 "link":         final_link,
#                 "cost":         dist[dest],
#                 "seq_no":       ROUTING_TABLE.get(dest, {}).get("seq_no", 0),
#                 "last_updated": time.ticks_ms(),
#             }


def _recompute_all_costs():
    """Recalculate all route costs after objective change."""
    for dest, entry in ROUTING_TABLE.items():
        if entry["link"] != "local":
            entry["cost"] = _get_cost(entry["link"])


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def get_route(dest_node_id: int) -> dict | None:
    """Look up how to reach a destination. Returns None if unknown."""
    return ROUTING_TABLE.get(dest_node_id)


def purge_stale_routes():
    """Remove routes that haven't been updated recently."""
    now      = time.ticks_ms()
    timeout  = config.ROUTE_TIMEOUT_S * 1000
    stale    = [
        dest for dest, entry in ROUTING_TABLE.items()
        if dest != _node_id
        and time.ticks_diff(now, entry["last_updated"]) > timeout
    ]
    for dest in stale:
        del ROUTING_TABLE[dest]
        print(f"[Routing] Purged stale route to node {dest}")


def get_table_summary() -> dict:
    """Return routing table in a clean format for telemetry/display."""
    return {
        str(dest): {
            "next_hop": entry["next_hop"],
            "link":     entry["link"],
            "cost":     entry["cost"],
        }
        for dest, entry in ROUTING_TABLE.items()
    }

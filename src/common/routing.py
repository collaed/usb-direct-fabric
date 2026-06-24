#!/usr/bin/env python3
"""UDF Routing — forwarding daemon & ring topology support.

Provides ring-aware routing table, neighbor liveness monitoring, and
HELLO frame construction/parsing for topology discovery.
"""
import os
import struct
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
import frame


class RoutingTable:
    def __init__(self, node_id: int, max_hops: int = 15):
        self.node_id = node_id
        self.max_hops = max_hops
        self._neighbors: dict[int, str] = {}  # neighbor_id -> port ('gadget'|'host')
        self._ring: list[int] = []             # ordered ring membership
        self._routes: dict[int, str] = {}      # dst -> port

    def add_neighbor(self, neighbor_id: int, port: str):
        """Register directly connected neighbor on given port."""
        self._neighbors[neighbor_id] = port
        self._routes[neighbor_id] = port
        if neighbor_id not in self._ring:
            self._ring = []  # invalidate until recompute

    def remove_neighbor(self, neighbor_id: int):
        """Remove a dead neighbor."""
        self._neighbors.pop(neighbor_id, None)
        self._routes.pop(neighbor_id, None)
        self._ring = [n for n in self._ring if n != neighbor_id]
        self.recompute()

    def get_next_hop(self, dst: int) -> Optional[str]:
        """Return port name for next hop toward dst, or None if unreachable."""
        if dst == 0xFF:  # broadcast: send on all ports (caller handles)
            return 'host'
        return self._routes.get(dst)

    def update_from_hello(self, hello_path: list[int]):
        """Learn ring membership from a forwarded HELLO's node list."""
        # Merge into ring: the hello_path is an ordered traversal
        seen = set(self._ring)
        for nid in hello_path:
            if nid not in seen:
                self._ring.append(nid)
                seen.add(nid)
        if self.node_id not in seen:
            self._ring.append(self.node_id)
        self.recompute()

    def recompute(self):
        """Rebuild routes. For ring: shortest direction to each destination."""
        if not self._ring:
            # Fallback: only direct neighbors known
            self._routes = dict(self._neighbors)
            return

        # Ensure self in ring
        if self.node_id not in self._ring:
            self._ring.append(self.node_id)

        ring = self._ring
        n = len(ring)
        try:
            my_idx = ring.index(self.node_id)
        except ValueError:
            return

        # Identify clockwise port and counter-clockwise port
        # Convention: 'host' = clockwise (toward next in ring), 'gadget' = counter-clockwise
        cw_port = 'host'
        ccw_port = 'gadget'

        for i, nid in enumerate(ring):
            if nid == self.node_id:
                continue
            # Clockwise distance
            cw_dist = (i - my_idx) % n
            ccw_dist = (my_idx - i) % n
            if cw_dist <= ccw_dist:
                self._routes[nid] = cw_port
            else:
                self._routes[nid] = ccw_port

    def get_ring_members(self) -> list[int]:
        """Ordered list of nodes in ring."""
        return list(self._ring)


class NeighborMonitor:
    def __init__(self, timeout_ms: int = 500):
        self.timeout_ms = timeout_ms
        self._last_seen: dict[int, float] = {}

    def heartbeat_received(self, neighbor_id: int):
        """Record heartbeat timestamp for neighbor."""
        self._last_seen[neighbor_id] = time.monotonic()

    def check_dead(self) -> list[int]:
        """Return list of neighbors that have timed out."""
        now = time.monotonic()
        threshold = self.timeout_ms / 1000.0
        return [nid for nid, ts in self._last_seen.items()
                if (now - ts) > threshold]


# -- HELLO frame helpers --

_HELLO_MAGIC = 0x48  # 'H' prefix in payload to identify HELLO

def make_hello(node_id: int, known_nodes: list[int], seq: int) -> bytes:
    """Pack a HELLO frame: regular UDF frame with special payload.

    Payload format: 1B magic('H') + 1B originator + 1B count + N×1B node_ids
    """
    count = len(known_nodes)
    payload = struct.pack('BBB', _HELLO_MAGIC, node_id, count) + bytes(known_nodes)
    return frame.pack(src=node_id, dst=0xFF, seq=seq, payload=payload)


def parse_hello(f: frame.Frame) -> tuple[int, list[int]]:
    """Extract originator + known nodes from HELLO payload."""
    if len(f.payload) < 3 or f.payload[0] != _HELLO_MAGIC:
        raise ValueError("Not a HELLO frame")
    originator = f.payload[1]
    count = f.payload[2]
    nodes = list(f.payload[3:3 + count])
    return originator, nodes


if __name__ == '__main__':
    """Self-test: create a 4-node ring, verify shortest paths."""
    print("=== Routing self-test: 4-node ring ===")
    # Ring: 1 → 2 → 3 → 4 → (back to 1)
    ring_order = [1, 2, 3, 4]

    results = []
    for nid in ring_order:
        rt = RoutingTable(nid)
        # Each node has two neighbors in the ring
        idx = ring_order.index(nid)
        cw_neighbor = ring_order[(idx + 1) % 4]
        ccw_neighbor = ring_order[(idx - 1) % 4]
        rt.add_neighbor(cw_neighbor, 'host')
        rt.add_neighbor(ccw_neighbor, 'gadget')
        # Simulate receiving HELLO with full ring
        rt.update_from_hello(ring_order)
        results.append((nid, rt))

    # Verify routing for node 1
    rt1 = results[0][1]
    # Node 1 → Node 2: clockwise (1 hop) = host
    assert rt1.get_next_hop(2) == 'host', f"1→2 got {rt1.get_next_hop(2)}"
    # Node 1 → Node 4: counter-clockwise (1 hop) = gadget
    assert rt1.get_next_hop(4) == 'gadget', f"1→4 got {rt1.get_next_hop(4)}"
    # Node 1 → Node 3: equidistant (2 hops either way) — cw wins (<=)
    assert rt1.get_next_hop(3) == 'host', f"1→3 got {rt1.get_next_hop(3)}"
    print(f"  Node 1 routes: 2→host ✓, 3→host ✓, 4→gadget ✓")

    # Verify routing for node 3
    rt3 = results[2][1]
    assert rt3.get_next_hop(4) == 'host', f"3→4 got {rt3.get_next_hop(4)}"
    assert rt3.get_next_hop(2) == 'gadget', f"3→2 got {rt3.get_next_hop(2)}"
    assert rt3.get_next_hop(1) == 'host', f"3→1 got {rt3.get_next_hop(1)}"
    print(f"  Node 3 routes: 4→host ✓, 2→gadget ✓, 1→host ✓")

    # Test HELLO pack/parse roundtrip
    hello_raw = make_hello(1, [1, 2, 3, 4], seq=0)
    hello_frame = frame.unpack(hello_raw)
    orig, nodes = parse_hello(hello_frame)
    assert orig == 1 and nodes == [1, 2, 3, 4]
    print(f"  HELLO roundtrip: originator={orig}, nodes={nodes} ✓")

    # Test NeighborMonitor
    mon = NeighborMonitor(timeout_ms=100)
    mon.heartbeat_received(2)
    assert mon.check_dead() == []
    time.sleep(0.15)
    dead = mon.check_dead()
    assert 2 in dead
    print(f"  NeighborMonitor: timeout detected ✓")

    print("\n=== All routing tests passed ===")

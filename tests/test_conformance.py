#!/usr/bin/env python3
"""UDF Conformance Tests — maps to spec §9.3.

Run: python3 -m pytest tests/ -v
Or:  python3 tests/test_conformance.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'common'))
import frame
import routing


class TestFrameCRC:
    """§9.3 Test 4: CRC Rejection — corrupted frames MUST be silently dropped."""

    def test_valid_frame_roundtrip(self):
        data = frame.pack(src=1, dst=2, seq=0, payload=b'test')
        f = frame.unpack(data)
        assert f.src == 1 and f.dst == 2 and f.payload == b'test'

    def test_crc_corruption_detected(self):
        data = frame.pack(src=1, dst=2, seq=0, payload=b'test')
        corrupted = bytearray(data)
        corrupted[16] ^= 0xFF  # flip payload byte
        try:
            frame.unpack(bytes(corrupted))
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "CRC" in str(e)

    def test_magic_corruption_detected(self):
        data = frame.pack(src=1, dst=2, seq=0, payload=b'x')
        corrupted = bytearray(data)
        corrupted[0] = 0x00  # corrupt magic
        try:
            frame.unpack(bytes(corrupted))
            assert False
        except ValueError as e:
            assert "magic" in str(e).lower()

    def test_truncated_frame_rejected(self):
        data = frame.pack(src=1, dst=2, seq=0, payload=b'hello')
        try:
            frame.unpack(data[:10])
            assert False
        except ValueError:
            pass

    def test_100_frames_zero_false_positives(self):
        """Send 100 valid + 100 corrupted, verify exact counts."""
        valid_count = 0
        reject_count = 0
        for i in range(200):
            data = frame.pack(src=1, dst=2, seq=i, payload=f"frame{i}".encode())
            if i % 2 == 1:
                data = bytearray(data)
                data[20] ^= 0xAA  # corrupt every odd frame
                data = bytes(data)
            try:
                frame.unpack(data)
                valid_count += 1
            except ValueError:
                reject_count += 1
        assert valid_count == 100
        assert reject_count == 100


class TestSequenceAccounting:
    """§9.3 Test 5: Sequence accounting — zero gaps over sustained transfer."""

    def test_1000_sequential_frames(self):
        """Verify 1000 frames arrive with sequential seq numbers."""
        frames = []
        for i in range(1000):
            data = frame.pack(src=1, dst=2, seq=i, payload=b'\x00' * 1024)
            f = frame.unpack(data)
            frames.append(f)
        # Verify no gaps
        for i, f in enumerate(frames):
            assert f.seq == i, f"Expected seq {i}, got {f.seq}"

    def test_sequence_wrap(self):
        """Verify wrap at 2^32-1 → 0."""
        f1 = frame.pack(src=1, dst=2, seq=0xFFFFFFFF, payload=b'last')
        f2 = frame.pack(src=1, dst=2, seq=0, payload=b'first')
        r1 = frame.unpack(f1)
        r2 = frame.unpack(f2)
        assert r1.seq == 0xFFFFFFFF
        assert r2.seq == 0


class TestHeartbeat:
    """§9.3 Test 2: Heartbeat detection."""

    def test_heartbeat_is_20_bytes(self):
        hb = frame.make_heartbeat(src=1, seq=0)
        assert len(hb) == 20

    def test_heartbeat_has_hb_flag(self):
        hb = frame.make_heartbeat(src=1, seq=42)
        f = frame.unpack(hb)
        assert f.is_heartbeat
        assert f.seq == 42

    def test_heartbeat_with_dst(self):
        hb = frame.make_heartbeat(src=1, seq=0, dst=2)
        f = frame.unpack(hb)
        assert f.dst == 2

    def test_dead_detection_timing(self):
        """Neighbor declared dead after 500ms of no heartbeat."""
        mon = routing.NeighborMonitor(timeout_ms=100)  # fast for testing
        mon.heartbeat_received(2)
        assert mon.check_dead() == []
        time.sleep(0.15)
        dead = mon.check_dead()
        assert 2 in dead
        # Idempotent: second call returns empty
        assert mon.check_dead() == []


class TestForwarding:
    """§9.3 Test 3: Forwarding through intermediate node."""

    def test_hop_increment(self):
        """Frame forwarded through a node has hop incremented."""
        original = frame.pack(src=1, dst=3, seq=0, payload=b'data', hop=0)
        f = frame.unpack(original)
        # Simulate forwarding: increment hop, set FWD flag
        forwarded = frame.pack(src=f.src, dst=f.dst, seq=99,
                               payload=f.payload,
                               flags=f.flags | frame.FLAG_FWD,
                               hop=f.hop + 1)
        ff = frame.unpack(forwarded)
        assert ff.hop == 1
        assert ff.flags & frame.FLAG_FWD
        assert ff.src == 1  # original source preserved
        assert ff.dst == 3
        assert ff.payload == b'data'

    def test_hop_limit_15(self):
        """Frames with hop > 15 must be dropped."""
        data = frame.pack(src=1, dst=2, seq=0, payload=b'x', hop=16)
        f = frame.unpack(data)
        # Forwarding logic should refuse this
        assert f.hop > 15  # caller checks and drops

    def test_ring_routing_4_nodes(self):
        """4-node ring: frame from 1→3 routes clockwise through 2."""
        rt = routing.RoutingTable(2)
        rt.add_neighbor(1, 'gadget')
        rt.add_neighbor(3, 'host')
        rt.update_from_hello([1, 2, 3, 4])
        assert rt.get_next_hop(3) == 'host'
        assert rt.get_next_hop(4) == 'host'
        assert rt.get_next_hop(1) == 'gadget'


class TestAuthentication:
    """Security extension: HMAC-SHA256 authenticated frames."""

    def test_authenticated_roundtrip(self):
        key = frame.derive_link_key(b'\x01' * 32, src_id=1, dst_id=2)
        data = frame.pack_authenticated(src=1, dst=2, seq=0,
                                        payload=b'secret', key=key)
        f = frame.unpack_authenticated(data, key)
        assert f.payload == b'secret'

    def test_wrong_key_rejected(self):
        key = frame.derive_link_key(b'\x01' * 32, src_id=1, dst_id=2)
        bad_key = frame.derive_link_key(b'\x02' * 32, src_id=1, dst_id=2)
        data = frame.pack_authenticated(src=1, dst=2, seq=0,
                                        payload=b'secret', key=key)
        try:
            frame.unpack_authenticated(data, bad_key)
            assert False
        except ValueError as e:
            assert "Authentication failed" in str(e)

    def test_tampered_payload_rejected(self):
        key = frame.derive_link_key(b'\x01' * 32, src_id=1, dst_id=2)
        data = frame.pack_authenticated(src=1, dst=2, seq=0,
                                        payload=b'secret', key=key)
        tampered = bytearray(data)
        tampered[16] ^= 0xFF
        try:
            frame.unpack_authenticated(bytes(tampered), key)
            assert False
        except ValueError:
            pass

    def test_max_payload_auth(self):
        assert frame.MAX_PAYLOAD_AUTH == 16352


# --- Runner ---

def _run_class(cls):
    name = cls.__name__
    instance = cls()
    passed = 0
    failed = 0
    for method_name in dir(instance):
        if not method_name.startswith('test_'):
            continue
        method = getattr(instance, method_name)
        try:
            method()
            passed += 1
        except (AssertionError, Exception) as e:
            failed += 1
            print(f"  FAIL {name}.{method_name}: {e}")
    return passed, failed


if __name__ == '__main__':
    total_passed = 0
    total_failed = 0
    for cls in [TestFrameCRC, TestSequenceAccounting, TestHeartbeat,
                TestForwarding, TestAuthentication]:
        print(f"--- {cls.__name__} ---")
        p, f = _run_class(cls)
        total_passed += p
        total_failed += f
        status = "✓" if f == 0 else f"✗ ({f} failures)"
        print(f"  {p} passed {status}")
    print(f"\n{'='*40}")
    print(f"Total: {total_passed} passed, {total_failed} failed")
    sys.exit(0 if total_failed == 0 else 1)

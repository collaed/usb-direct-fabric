"""UDF Wire Format v0.1 — frame pack/unpack.

All frames use the same 20-byte minimum structure: 16B header + 4B CRC.
Heartbeats are normal frames with HB flag set and zero-length payload.
This eliminates short-packet ambiguity at the USB transfer boundary.

Authenticated mode (v1.1): appends a 16-byte HMAC-SHA256 tag between
payload and CRC. Negotiated during CAP exchange via Features bit 3.
"""
import struct, zlib, hmac
from dataclasses import dataclass

MAGIC = b'UF'
HDR_SIZE = 16
CRC_SIZE = 4
MIN_FRAME = HDR_SIZE + CRC_SIZE  # 20 bytes (heartbeat = min frame)
MAX_PAYLOAD = 16368

# Flags
FLAG_SYN = 0x01
FLAG_FIN = 0x02
FLAG_ACK = 0x04
FLAG_FWD = 0x08
FLAG_HB  = 0x10
FLAG_CAP = 0x20


def _pad16(n: int) -> int:
    return (n + 15) & ~15 if n > 0 else 0


@dataclass
class Frame:
    flags: int
    hop: int
    seq: int
    src: int
    dst: int
    payload: bytes

    @property
    def is_heartbeat(self) -> bool:
        return bool(self.flags & FLAG_HB)

    @property
    def is_syn(self) -> bool:
        return bool(self.flags & FLAG_SYN)

    @property
    def is_fin(self) -> bool:
        return bool(self.flags & FLAG_FIN)

    @property
    def is_cap(self) -> bool:
        return bool(self.flags & FLAG_CAP)


def pack(src: int, dst: int, seq: int, payload: bytes = b'',
         flags: int = 0, hop: int = 0) -> bytes:
    """Pack a UDF frame: 16B header + padded payload + 4B CRC."""
    plen = len(payload)
    padded = _pad16(plen)
    hdr = struct.pack('<2sBBI', MAGIC, flags, hop, seq)
    routing = struct.pack('<BBH I', src, dst, plen, 0)
    body = payload.ljust(padded, b'\x00') if padded else b''
    raw = hdr + routing + body
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return raw + struct.pack('<I', crc)


def unpack(data: bytes) -> Frame:
    """Unpack raw bytes into a Frame. Raises ValueError on invalid data."""
    if len(data) < MIN_FRAME:
        raise ValueError(f"Frame too short ({len(data)} < {MIN_FRAME})")
    if data[0:2] != MAGIC:
        raise ValueError(f"Bad magic: {data[0:2]!r}")
    flags, hop, seq = struct.unpack_from('<BBI', data, 2)
    src, dst, plen, _ = struct.unpack_from('<BBH I', data, 8)
    padded = _pad16(plen)
    expected = HDR_SIZE + padded + CRC_SIZE
    if len(data) < expected:
        raise ValueError(f"Frame truncated ({len(data)} < {expected})")
    crc_stored = struct.unpack_from('<I', data, HDR_SIZE + padded)[0]
    crc_calc = zlib.crc32(data[:HDR_SIZE + padded]) & 0xFFFFFFFF
    if crc_stored != crc_calc:
        raise ValueError("CRC mismatch")
    payload = data[HDR_SIZE:HDR_SIZE + plen]
    return Frame(flags=flags, hop=hop, seq=seq, src=src, dst=dst, payload=payload)


# --- Convenience constructors ---

def make_heartbeat(src: int, seq: int, dst: int = 0) -> bytes:
    """Pack a heartbeat: normal frame with HB flag, zero payload. Always 20 bytes.
    dst defaults to 0 (unassigned) for backward compat; in ring topologies
    implementations SHOULD set dst to the neighbor's node ID."""
    return pack(src=src, dst=dst, seq=seq, flags=FLAG_HB)


def make_syn(src: int, dst: int, seq: int) -> bytes:
    return pack(src=src, dst=dst, seq=seq, flags=FLAG_SYN)


def make_ack(src: int, dst: int, seq: int) -> bytes:
    return pack(src=src, dst=dst, seq=seq, flags=FLAG_ACK)


def make_cap(src: int, dst: int, seq: int, node_name: str,
             max_frame: int = 16388, version: int = 1, features: int = 0) -> bytes:
    """CAP frame: 16-byte payload with capabilities.
    Name is truncated to 9 bytes + null terminator if longer."""
    name_bytes = node_name.encode('utf-8')[:9]  # truncate to 9, leave room for null
    name_field = name_bytes.ljust(10, b'\x00')  # 10 bytes, null-padded
    cap_payload = struct.pack('<HHBB', version, max_frame, src, features) + name_field
    return pack(src=src, dst=dst, seq=seq, payload=cap_payload, flags=FLAG_CAP)


def parse_cap(payload: bytes) -> dict:
    """Parse a CAP frame payload into its fields."""
    if len(payload) < 16:
        raise ValueError("CAP payload too short")
    version, max_frame, node_id, features = struct.unpack_from('<HHBB', payload)
    name_raw = payload[6:16]
    name = name_raw.split(b'\x00', 1)[0].decode('utf-8', errors='replace')
    return {'version': version, 'max_frame': max_frame, 'node_id': node_id,
            'features': features, 'name': name}


# --- Legacy tuple-based API (backward compat) ---

def pack_frame(flags: int, seq: int, src: int, dst: int, payload: bytes = b'') -> bytes:
    return pack(src=src, dst=dst, seq=seq, payload=payload, flags=flags)


def unpack_frame(data: bytes):
    """Returns (flags, seq, src, dst, payload) tuple or None on error."""
    try:
        f = unpack(data)
        return (f.flags, f.seq, f.src, f.dst, f.payload)
    except ValueError:
        return None


# --- Authenticated Mode (v1.1) ---

AUTH_TAG_SIZE = 16  # HMAC-SHA256 truncated to 128 bits
MAX_PAYLOAD_AUTH = MAX_PAYLOAD - AUTH_TAG_SIZE  # 16352 bytes


def derive_link_key(psk: bytes, src_id: int, dst_id: int, nonce: bytes = b'\x00' * 4) -> bytes:
    """Derive a per-link key from the PSK using HKDF-like construction.
    link_key = HMAC-SHA256(PSK, src_id || dst_id || nonce)"""
    material = struct.pack('BB', src_id, dst_id) + nonce
    return hmac.digest(psk, material, 'sha256')


def _compute_tag(key: bytes, header: bytes, padded_payload: bytes) -> bytes:
    """HMAC-SHA256(key, header || padded_payload), truncated to 16 bytes."""
    return hmac.digest(key, header + padded_payload, 'sha256')[:AUTH_TAG_SIZE]


def pack_authenticated(src: int, dst: int, seq: int, payload: bytes,
                       key: bytes, flags: int = 0, hop: int = 0) -> bytes:
    """Pack a UDF frame with 16-byte HMAC auth tag between payload and CRC.

    Layout: header(16) + padded_payload(N) + auth_tag(16) + CRC(4)
    """
    plen = len(payload)
    padded = _pad16(plen)
    hdr = struct.pack('<2sBBI', MAGIC, flags, hop, seq)
    routing = struct.pack('<BBH I', src, dst, plen, 0)
    header = hdr + routing
    body = payload.ljust(padded, b'\x00') if padded else b''
    tag = _compute_tag(key, header, body)
    raw = header + body + tag
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    return raw + struct.pack('<I', crc)


def unpack_authenticated(data: bytes, key: bytes) -> Frame:
    """Unpack and verify an authenticated UDF frame.
    Raises ValueError on CRC mismatch, auth failure, or invalid frame."""
    if len(data) < MIN_FRAME + AUTH_TAG_SIZE:
        raise ValueError(f"Authenticated frame too short ({len(data)})")
    if data[0:2] != MAGIC:
        raise ValueError(f"Bad magic: {data[0:2]!r}")
    flags, hop, seq = struct.unpack_from('<BBI', data, 2)
    src, dst, plen, _ = struct.unpack_from('<BBH I', data, 8)
    padded = _pad16(plen)
    expected = HDR_SIZE + padded + AUTH_TAG_SIZE + CRC_SIZE
    if len(data) < expected:
        raise ValueError(f"Frame truncated ({len(data)} < {expected})")
    # Verify CRC first (covers header + payload + tag)
    crc_offset = HDR_SIZE + padded + AUTH_TAG_SIZE
    crc_stored = struct.unpack_from('<I', data, crc_offset)[0]
    crc_calc = zlib.crc32(data[:crc_offset]) & 0xFFFFFFFF
    if crc_stored != crc_calc:
        raise ValueError("CRC mismatch")
    # Verify HMAC tag
    header = data[:HDR_SIZE]
    body = data[HDR_SIZE:HDR_SIZE + padded]
    tag_stored = data[HDR_SIZE + padded:HDR_SIZE + padded + AUTH_TAG_SIZE]
    tag_expected = _compute_tag(key, header, body)
    if not hmac.compare_digest(tag_stored, tag_expected):
        raise ValueError("Authentication failed — HMAC mismatch")
    payload = data[HDR_SIZE:HDR_SIZE + plen]
    return Frame(flags=flags, hop=hop, seq=seq, src=src, dst=dst, payload=payload)


if __name__ == '__main__':
    # Self-test
    f = pack(src=1, dst=2, seq=42, payload=b'Hello UDF')
    assert len(f) == 16 + 16 + 4  # 9 bytes padded to 16
    r = unpack(f)
    assert r.seq == 42 and r.src == 1 and r.dst == 2 and r.payload == b'Hello UDF'

    hb = make_heartbeat(src=1, seq=99)
    assert len(hb) == 20  # min frame: header + CRC, no payload
    h = unpack(hb)
    assert h.is_heartbeat and h.seq == 99

    # CRC error detection
    bad = bytearray(f)
    bad[18] ^= 0xFF
    try:
        unpack(bytes(bad))
        assert False, "Should have raised"
    except ValueError:
        pass

    # CAP round-trip with truncation
    cap = make_cap(src=1, dst=2, seq=1, node_name='a-very-long-hostname-that-exceeds-ten-bytes')
    cf = unpack(cap)
    info = parse_cap(cf.payload)
    assert info['name'] == 'a-very-lo'  # truncated to exactly 9 bytes

    # Tuple API compat
    assert unpack_frame(f) == (0, 42, 1, 2, b'Hello UDF')

    # --- Authenticated mode tests ---
    psk = b'\x01' * 32  # test PSK
    key = derive_link_key(psk, src_id=1, dst_id=2)
    assert len(key) == 32  # full SHA-256 output

    # Authenticated round-trip
    af = pack_authenticated(src=1, dst=2, seq=7, payload=b'secret', key=key)
    assert len(af) == 16 + 16 + 16 + 4  # header + padded(6→16) + tag + CRC
    ar = unpack_authenticated(af, key)
    assert ar.payload == b'secret' and ar.seq == 7

    # Wrong key → auth failure
    wrong_key = b'\x02' * 32
    try:
        unpack_authenticated(af, wrong_key)
        assert False, "Should have raised"
    except ValueError as e:
        assert "Authentication failed" in str(e)

    # Tampered payload → auth failure
    tampered = bytearray(af)
    tampered[16] ^= 0xFF  # flip a payload byte
    try:
        unpack_authenticated(bytes(tampered), key)
        assert False, "Should have raised"
    except ValueError:
        pass  # either CRC or HMAC catches it

    print("All frame tests passed ✓ (including authenticated mode)")

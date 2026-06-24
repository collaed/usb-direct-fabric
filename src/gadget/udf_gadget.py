#!/usr/bin/env python3
"""UDF gadget-side daemon — FunctionFS bulk transport."""

import argparse
import os
import queue
import signal
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))
import frame

# FunctionFS constants
DESCRIPTORS_MAGIC_V2 = 0x00000003
STRINGS_MAGIC = 0x00000002
HAS_FS_DESC = 0x01
HAS_HS_DESC = 0x02
HAS_SS_DESC = 0x04

# USB descriptor types
DT_INTERFACE = 4
DT_ENDPOINT = 5
DT_SS_EP_COMPANION = 48

# UDF interface: class 0xFF, subclass 0x01, protocol 0x01
IFACE_CLASS = 0xFF
IFACE_SUBCLASS = 0x01
IFACE_PROTOCOL = 0x01

# Frame flags
FLAG_HB = 0x10


def _interface_desc():
    """Interface descriptor: 9 bytes."""
    return struct.pack('<BBBBBBBBB',
                       9, DT_INTERFACE, 0, 0, 2,
                       IFACE_CLASS, IFACE_SUBCLASS, IFACE_PROTOCOL, 0)


def _ep_bulk_out(max_pkt):
    """Bulk OUT endpoint descriptor: 7 bytes."""
    return struct.pack('<BBBBHB', 7, DT_ENDPOINT, 0x01, 0x02, max_pkt, 0)


def _ep_bulk_in(max_pkt):
    """Bulk IN endpoint descriptor: 7 bytes."""
    return struct.pack('<BBBBHB', 7, DT_ENDPOINT, 0x81, 0x02, max_pkt, 0)


def _ss_companion(max_burst=15):
    """SuperSpeed endpoint companion descriptor: 6 bytes."""
    return struct.pack('<BBBBH', 6, DT_SS_EP_COMPANION, max_burst, 0x00, 0)


def build_descriptors():
    """Build FunctionFS v2 descriptors blob."""
    # FS descriptors (bulk max 64)
    fs = _interface_desc() + _ep_bulk_out(64) + _ep_bulk_in(64)
    fs_count = 3

    # HS descriptors (bulk max 512)
    hs = _interface_desc() + _ep_bulk_out(512) + _ep_bulk_in(512)
    hs_count = 3

    # SS descriptors (bulk max 1024 + companion)
    ss = (_interface_desc()
          + _ep_bulk_out(1024) + _ss_companion()
          + _ep_bulk_in(1024) + _ss_companion())
    ss_count = 5

    body = struct.pack('<III', fs_count, hs_count, ss_count) + fs + hs + ss
    header = struct.pack('<III', DESCRIPTORS_MAGIC_V2,
                         12 + len(body),  # 12 = magic + length + flags
                         HAS_FS_DESC | HAS_HS_DESC | HAS_SS_DESC)
    return header + body


def build_strings():
    """Build FunctionFS strings blob."""
    lang = 0x0409
    strs = ['UDF Gadget\x00']
    str_data = strs[0].encode('utf-8')
    count = 1
    # Header: magic(4) + length(4) + str_count(4) + lang(4) + strings
    body = struct.pack('<I', lang) + str_data
    header = struct.pack('<III', STRINGS_MAGIC, 12 + len(body), count)
    return header + body


class GadgetDaemon:
    def __init__(self, ffs_dir, node_id, verbose):
        self.ffs_dir = ffs_dir
        self.node_id = node_id
        self.verbose = verbose
        self.running = False
        self.tx_queue = queue.Queue()
        self.rx_queue = queue.Queue()
        # Stats
        self.frames_rx = 0
        self.frames_tx = 0
        self.bytes_rx = 0
        self.bytes_tx = 0
        self.crc_errors = 0
        self.seq_gaps = 0
        self.expected_seq = 0
        self.tx_seq = 0
        self._lock = threading.Lock()

    def start(self):
        self.running = True
        ep0_path = os.path.join(self.ffs_dir, 'ep0')

        # Write descriptors and strings to ep0
        fd0 = os.open(ep0_path, os.O_RDWR)
        os.write(fd0, build_descriptors())
        os.write(fd0, build_strings())

        # Wait for endpoint files to appear
        ep1_path = os.path.join(self.ffs_dir, 'ep1')
        ep2_path = os.path.join(self.ffs_dir, 'ep2')
        for _ in range(50):
            if os.path.exists(ep1_path) and os.path.exists(ep2_path):
                break
            time.sleep(0.1)

        self.ep1_fd = os.open(ep1_path, os.O_WRONLY)
        self.ep2_fd = os.open(ep2_path, os.O_RDONLY)
        self.ep0_fd = fd0

        print(f"[UDF] Gadget daemon started, node_id={self.node_id}, ffs={self.ffs_dir}")

        # Launch threads
        self._threads = [
            threading.Thread(target=self._rx_loop, name='rx', daemon=True),
            threading.Thread(target=self._tx_loop, name='tx', daemon=True),
            threading.Thread(target=self._hb_loop, name='hb', daemon=True),
            threading.Thread(target=self._stats_loop, name='stats', daemon=True),
        ]
        for t in self._threads:
            t.start()

    def stop(self):
        self.running = False
        print("[UDF] Shutting down...")
        for fd in (self.ep0_fd, self.ep1_fd, self.ep2_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def _rx_loop(self):
        """Read frames from ep2 (bulk OUT, host-to-device)."""
        buf_size = 16388  # max frame size
        while self.running:
            try:
                data = os.read(self.ep2_fd, buf_size)
            except OSError:
                if self.running:
                    time.sleep(0.01)
                continue
            if not data:
                time.sleep(0.001)
                continue

            with self._lock:
                self.bytes_rx += len(data)

            try:
                hdr = frame.unpack(data)
            except Exception:
                with self._lock:
                    self.crc_errors += 1
                if self.verbose:
                    print("[UDF] RX: CRC/parse error")
                continue

            with self._lock:
                self.frames_rx += 1
                # Sequence gap detection
                if hdr.get('seq', 0) > self.expected_seq:
                    self.seq_gaps += 1
                    self.expected_seq = hdr['seq'] + 1
                elif hdr.get('seq', 0) == self.expected_seq:
                    self.expected_seq += 1
                # else: duplicate, ignore

            # Route: if dest is us or broadcast, deliver locally
            dest = hdr.get('dst', self.node_id)
            if dest == self.node_id or dest == 0xFF:
                self.rx_queue.put(hdr)
            elif hdr.get('hops', 0) < 15:
                # Forward
                self.tx_queue.put(data)

    def _tx_loop(self):
        """Write frames from send queue to ep1 (bulk IN, device-to-host)."""
        while self.running:
            try:
                item = self.tx_queue.get(timeout=0.05)
            except queue.Empty:
                continue

            # item can be raw bytes (forwarding) or a dict to pack
            if isinstance(item, (bytes, bytearray)):
                data = bytes(item)
            else:
                data = frame.pack(**item)

            try:
                os.write(self.ep1_fd, data)
                with self._lock:
                    self.frames_tx += 1
                    self.bytes_tx += len(data)
            except OSError:
                if self.running:
                    time.sleep(0.01)

    def _hb_loop(self):
        """Send heartbeat frames every 100ms."""
        while self.running:
            hb = frame.pack(
                flags=FLAG_HB,
                seq=self._next_seq(),
                src=self.node_id,
                dst=0xFF,
                payload=b'',
            )
            try:
                os.write(self.ep1_fd, hb)
                with self._lock:
                    self.frames_tx += 1
                    self.bytes_tx += len(hb)
            except OSError:
                pass
            time.sleep(0.1)

    def _next_seq(self):
        with self._lock:
            seq = self.tx_seq
            self.tx_seq = (self.tx_seq + 1) & 0xFFFFFFFF
            return seq

    def _stats_loop(self):
        """Log stats every 5 seconds."""
        while self.running:
            time.sleep(5)
            with self._lock:
                print(f"[UDF] rx={self.frames_rx} tx={self.frames_tx} "
                      f"bytes_rx={self.bytes_rx} bytes_tx={self.bytes_tx} "
                      f"crc_err={self.crc_errors} seq_gaps={self.seq_gaps}")

    def send(self, dst, payload):
        """Enqueue a data frame for transmission."""
        self.tx_queue.put({
            'flags': 0,
            'seq': self._next_seq(),
            'src': self.node_id,
            'dst': dst,
            'payload': payload,
        })


def main():
    parser = argparse.ArgumentParser(description='UDF gadget daemon')
    parser.add_argument('--ffs-dir', default='/tmp/udf_ffs',
                        help='FunctionFS mount point')
    parser.add_argument('--node-id', type=int, default=1,
                        help='Node ID (1-254)')
    parser.add_argument('--verbose', action='store_true',
                        help='Verbose logging')
    args = parser.parse_args()

    daemon = GadgetDaemon(args.ffs_dir, args.node_id, args.verbose)

    def _shutdown(sig, _frame):
        daemon.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    daemon.start()

    # Block main thread until shutdown
    while daemon.running:
        time.sleep(0.5)


if __name__ == '__main__':
    main()

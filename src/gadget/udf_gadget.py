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

# FunctionFS event types
FUNCTIONFS_BIND = 0
FUNCTIONFS_UNBIND = 1
FUNCTIONFS_ENABLE = 2
FUNCTIONFS_DISABLE = 3
FUNCTIONFS_SETUP = 4
FUNCTIONFS_SUSPEND = 5
FUNCTIONFS_RESUME = 6
# Event struct: type(1) + pad(3) + u(8) = 12 bytes
FFS_EVENT_SIZE = 12

# USB descriptor types
DT_INTERFACE = 4
DT_ENDPOINT = 5
DT_SS_EP_COMPANION = 48

# UDF interface: class 0xFF, subclass 0x01, protocol 0x01
IFACE_CLASS = 0xFF
IFACE_SUBCLASS = 0x01
IFACE_PROTOCOL = 0x01


def _interface_desc():
    return struct.pack('<BBBBBBBBB',
                       9, DT_INTERFACE, 0, 0, 2,
                       IFACE_CLASS, IFACE_SUBCLASS, IFACE_PROTOCOL, 0)


def _ep_bulk_out(max_pkt):
    return struct.pack('<BBBBHB', 7, DT_ENDPOINT, 0x01, 0x02, max_pkt, 0)


def _ep_bulk_in(max_pkt):
    return struct.pack('<BBBBHB', 7, DT_ENDPOINT, 0x81, 0x02, max_pkt, 0)


def _ss_companion(max_burst=15):
    return struct.pack('<BBBBH', 6, DT_SS_EP_COMPANION, max_burst, 0x00, 0)


def build_descriptors():
    fs = _interface_desc() + _ep_bulk_out(64) + _ep_bulk_in(64)
    hs = _interface_desc() + _ep_bulk_out(512) + _ep_bulk_in(512)
    ss = (_interface_desc()
          + _ep_bulk_out(1024) + _ss_companion()
          + _ep_bulk_in(1024) + _ss_companion())
    body = struct.pack('<III', 3, 3, 5) + fs + hs + ss
    header = struct.pack('<III', DESCRIPTORS_MAGIC_V2,
                         12 + len(body),
                         HAS_FS_DESC | HAS_HS_DESC | HAS_SS_DESC)
    return header + body


def build_strings():
    lang = 0x0409
    str_data = b'UDF Gadget\x00'
    body = struct.pack('<I', lang) + str_data
    header = struct.pack('<III', STRINGS_MAGIC, 12 + len(body), 1)
    return header + body


class GadgetDaemon:
    def __init__(self, ffs_dir, node_id, verbose):
        self.ffs_dir = ffs_dir
        self.node_id = node_id
        self.verbose = verbose
        self.running = False
        self.tx_queue = queue.Queue()
        self.rx_queue = queue.Queue()
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
        self.ep0_fd = fd0

        # Wait for BIND and ENABLE events before opening endpoints
        self._wait_for_enable()

        ep1_path = os.path.join(self.ffs_dir, 'ep1')
        ep2_path = os.path.join(self.ffs_dir, 'ep2')
        for _ in range(50):
            if os.path.exists(ep1_path) and os.path.exists(ep2_path):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Endpoint files did not appear")

        self.ep1_fd = os.open(ep1_path, os.O_WRONLY)
        self.ep2_fd = os.open(ep2_path, os.O_RDONLY)

        print(f"[UDF] Gadget started, node_id={self.node_id}, ffs={self.ffs_dir}")

        self._threads = [
            threading.Thread(target=self._rx_loop, name='rx', daemon=True),
            threading.Thread(target=self._tx_loop, name='tx', daemon=True),
            threading.Thread(target=self._hb_loop, name='hb', daemon=True),
            threading.Thread(target=self._stats_loop, name='stats', daemon=True),
            threading.Thread(target=self._ep0_loop, name='ep0', daemon=True),
        ]
        for t in self._threads:
            t.start()

    def _wait_for_enable(self):
        """Read ep0 events until FUNCTIONFS_ENABLE (or timeout).
        The kernel may batch multiple events in a single read."""
        for _ in range(50):  # 5 seconds max
            try:
                data = os.read(self.ep0_fd, FFS_EVENT_SIZE * 8)  # up to 8 events
                for i in range(0, len(data), FFS_EVENT_SIZE):
                    event_type = data[i]
                    if self.verbose:
                        print(f"[UDF] ep0 event: {event_type}")
                    if event_type == FUNCTIONFS_ENABLE:
                        return
            except OSError:
                pass
            time.sleep(0.1)
        print("[UDF] WARNING: ENABLE event not received, proceeding anyway")

    def _ep0_loop(self):
        """Handle ep0 control events (SUSPEND, RESUME, DISABLE)."""
        while self.running:
            try:
                data = os.read(self.ep0_fd, FFS_EVENT_SIZE)
                if data:
                    event_type = data[0]
                    if self.verbose:
                        print(f"[UDF] ep0 event: {event_type}")
                    if event_type == FUNCTIONFS_DISABLE:
                        print("[UDF] USB disabled (cable unplugged?)")
                    elif event_type == FUNCTIONFS_ENABLE:
                        print("[UDF] USB re-enabled")
            except OSError:
                if self.running:
                    time.sleep(0.1)

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
        buf_size = 16388
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
                f = frame.unpack(data)
            except ValueError:
                with self._lock:
                    self.crc_errors += 1
                if self.verbose:
                    print("[UDF] RX: CRC/parse error")
                continue

            with self._lock:
                self.frames_rx += 1
                if f.seq > self.expected_seq:
                    self.seq_gaps += 1
                    self.expected_seq = f.seq + 1
                elif f.seq == self.expected_seq:
                    self.expected_seq += 1

            # Route: deliver locally or forward
            if f.dst == self.node_id or f.dst == 0xFF:
                self.rx_queue.put(f)
            elif f.hop < 15:
                # Forward: increment hop, set FWD flag, re-pack with new seq
                fwd = frame.pack(src=f.src, dst=f.dst, seq=self._next_seq(),
                                 payload=f.payload, flags=f.flags | frame.FLAG_FWD,
                                 hop=f.hop + 1)
                self.tx_queue.put(fwd)

    def _tx_loop(self):
        """Write pre-packed frame bytes from queue to ep1 (bulk IN)."""
        while self.running:
            try:
                data = self.tx_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            # Handle partial writes — FunctionFS may not accept full buffer
            # if hardware FIFO is full or host is slow to poll
            written = 0
            while written < len(data) and self.running:
                try:
                    n = os.write(self.ep1_fd, data[written:])
                    written += n
                except BlockingIOError:
                    time.sleep(0.001)
                except OSError:
                    if self.running:
                        time.sleep(0.01)
                    break
            if written == len(data):
                with self._lock:
                    self.frames_tx += 1
                    self.bytes_tx += len(data)

    def _hb_loop(self):
        """Enqueue heartbeat frames every 100ms (goes through tx_queue).
        Uses dst=0xFF (broadcast) so receivers always recognise it as a
        liveness signal regardless of topology. In ring deployments,
        implementations SHOULD set dst to the direct neighbor's ID instead."""
        while self.running:
            hb = frame.make_heartbeat(src=self.node_id, seq=self._next_seq(),
                                      dst=0xFF)
            self.tx_queue.put(hb)
            time.sleep(0.1)

    def _next_seq(self):
        with self._lock:
            seq = self.tx_seq
            self.tx_seq = (self.tx_seq + 1) & 0xFFFFFFFF
            return seq

    def _stats_loop(self):
        while self.running:
            time.sleep(5)
            with self._lock:
                print(f"[UDF] rx={self.frames_rx} tx={self.frames_tx} "
                      f"bytes_rx={self.bytes_rx} bytes_tx={self.bytes_tx} "
                      f"crc_err={self.crc_errors} seq_gaps={self.seq_gaps}")

    def send(self, dst, payload):
        """Enqueue a data frame for transmission."""
        data = frame.pack(src=self.node_id, dst=dst, seq=self._next_seq(),
                          payload=payload)
        self.tx_queue.put(data)


def main():
    parser = argparse.ArgumentParser(description='UDF gadget daemon')
    parser.add_argument('--ffs-dir', default='/tmp/udf_ffs')
    parser.add_argument('--node-id', type=int, default=1)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    daemon = GadgetDaemon(args.ffs_dir, args.node_id, args.verbose)

    def _shutdown(sig, _):
        daemon.stop()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    daemon.start()
    while daemon.running:
        time.sleep(0.5)


if __name__ == '__main__':
    main()

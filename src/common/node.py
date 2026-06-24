#!/usr/bin/env python3
"""UDF Node — dual-cable full-duplex orchestrator.

Runs gadget RX + host TX simultaneously on one machine, providing a unified
send/receive API for the application layer. For the 2-node case: gadget RX
is inbound from neighbor, host TX is outbound to neighbor.
"""
import os
import queue
import signal
import struct
import sys
import threading
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
import frame


class UDFNode:
    def __init__(self, node_id: int, gadget_ffs_dir: str = '/tmp/udf_ffs',
                 host_vid: int = 0x1d6b, host_pid: int = 0x0105):
        self.node_id = node_id
        self.gadget_ffs_dir = gadget_ffs_dir
        self.host_vid = host_vid
        self.host_pid = host_pid

        self._rx_queue: queue.Queue = queue.Queue()
        self._tx_queue: queue.Queue = queue.Queue()
        self._running = False
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

        # Per-direction sequence counters
        self._seq_gadget_tx = 0
        self._seq_host_tx = 0

        # Stats
        self._stats = {
            'frames_rx': 0, 'frames_tx': 0,
            'bytes_rx': 0, 'bytes_tx': 0,
            'forwarded': 0, 'dropped': 0,
        }

        # File descriptors (set during start if hardware present, else simulated)
        self._gadget_ep_out: Optional[int] = None  # gadget RX (bulk OUT from host)
        self._gadget_ep_in: Optional[int] = None   # gadget TX (bulk IN to host)
        self._host_fd: Optional[int] = None        # host bulk device fd

    def start(self):
        """Launch all RX/TX/heartbeat threads."""
        self._running = True
        self._open_endpoints()
        names_funcs = [
            ('gadget-rx', self._gadget_rx_loop),
            ('gadget-tx', self._gadget_tx_loop),
            ('host-rx', self._host_rx_loop),
            ('host-tx', self._host_tx_loop),
            ('heartbeat', self._heartbeat_loop),
        ]
        for name, fn in names_funcs:
            t = threading.Thread(target=fn, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        """Clean shutdown of all threads."""
        self._running = False
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads.clear()
        self._close_endpoints()

    def send(self, dst: int, payload: bytes):
        """Route outbound frame. For 2-node: always host TX."""
        with self._lock:
            seq = self._seq_host_tx
            self._seq_host_tx += 1
        raw = frame.pack(self.node_id, dst, seq, payload)
        self._tx_queue.put(raw)
        with self._lock:
            self._stats['frames_tx'] += 1
            self._stats['bytes_tx'] += len(payload)

    def recv(self, timeout: float = 1.0) -> Optional[frame.Frame]:
        """Dequeue next inbound frame from either gadget or host RX."""
        try:
            return self._rx_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def forward(self, f: frame.Frame):
        """Forward frame if dst != self. Increment hop, send on TX port."""
        if f.dst == self.node_id:
            return
        if f.hop >= 15:
            with self._lock:
                self._stats['dropped'] += 1
            return
        with self._lock:
            seq = self._seq_host_tx
            self._seq_host_tx += 1
        raw = frame.pack(f.src, f.dst, seq, f.payload,
                         flags=f.flags | frame.FLAG_FWD, hop=f.hop + 1)
        self._tx_queue.put(raw)
        with self._lock:
            self._stats['forwarded'] += 1

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self._stats)

    # -- Internal endpoint management --

    def _open_endpoints(self):
        """Open FunctionFS endpoints (gadget) and host USB device fd."""
        ep_out = os.path.join(self.gadget_ffs_dir, 'ep1')
        ep_in = os.path.join(self.gadget_ffs_dir, 'ep2')
        if os.path.exists(ep_out):
            self._gadget_ep_out = os.open(ep_out, os.O_RDONLY | os.O_NONBLOCK)
        if os.path.exists(ep_in):
            self._gadget_ep_in = os.open(ep_in, os.O_WRONLY | os.O_NONBLOCK)
        # Host device: find by VID/PID under /dev/bus/usb or use libusb path
        host_path = self._find_host_device()
        if host_path:
            self._host_fd = os.open(host_path, os.O_RDWR | os.O_NONBLOCK)

    def _close_endpoints(self):
        for fd in (self._gadget_ep_out, self._gadget_ep_in, self._host_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def _find_host_device(self) -> Optional[str]:
        """Scan /dev/bus/usb for our VID:PID."""
        bus_root = '/dev/bus/usb'
        if not os.path.isdir(bus_root):
            return None
        for bus in sorted(os.listdir(bus_root)):
            bus_path = os.path.join(bus_root, bus)
            if not os.path.isdir(bus_path):
                continue
            for dev in sorted(os.listdir(bus_path)):
                dev_path = os.path.join(bus_path, dev)
                try:
                    fd = os.open(dev_path, os.O_RDONLY)
                    hdr = os.read(fd, 18)
                    os.close(fd)
                    if len(hdr) >= 12:
                        vid, pid = struct.unpack_from('<HH', hdr, 8)
                        if vid == self.host_vid and pid == self.host_pid:
                            return dev_path
                except OSError:
                    continue
        return None

    # -- Thread loops --

    def _gadget_rx_loop(self):
        """Read frames from gadget bulk OUT endpoint (neighbor → us)."""
        while self._running:
            if self._gadget_ep_out is None:
                time.sleep(0.1)
                continue
            try:
                data = os.read(self._gadget_ep_out, 16388)
                if not data:
                    time.sleep(0.001)
                    continue
                f = frame.unpack(data)
                with self._lock:
                    self._stats['frames_rx'] += 1
                    self._stats['bytes_rx'] += len(f.payload)
                if f.dst == self.node_id or f.dst == 0xFF:
                    self._rx_queue.put(f)
                else:
                    self.forward(f)
            except (OSError, ValueError):
                time.sleep(0.01)

    def _gadget_tx_loop(self):
        """Write frames from gadget TX queue to bulk IN endpoint."""
        while self._running:
            if self._gadget_ep_in is None:
                time.sleep(0.1)
                continue
            # Gadget TX is used in ring >2 nodes; for 2-node we use host TX
            time.sleep(0.1)

    def _host_rx_loop(self):
        """Read frames from host USB device (neighbor gadget → our host)."""
        while self._running:
            if self._host_fd is None:
                time.sleep(0.1)
                continue
            try:
                data = os.read(self._host_fd, 16388)
                if not data:
                    time.sleep(0.001)
                    continue
                f = frame.unpack(data)
                with self._lock:
                    self._stats['frames_rx'] += 1
                    self._stats['bytes_rx'] += len(f.payload)
                if f.dst == self.node_id or f.dst == 0xFF:
                    self._rx_queue.put(f)
                else:
                    self.forward(f)
            except (OSError, ValueError):
                time.sleep(0.01)

    def _host_tx_loop(self):
        """Drain _tx_queue and write to host USB device (us → neighbor gadget)."""
        while self._running:
            try:
                raw = self._tx_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if self._host_fd is not None:
                try:
                    os.write(self._host_fd, raw)
                except OSError:
                    with self._lock:
                        self._stats['dropped'] += 1

    def _heartbeat_loop(self):
        """Send heartbeat every 100ms if no data was sent recently."""
        while self._running:
            time.sleep(0.1)
            with self._lock:
                seq = self._seq_host_tx
                self._seq_host_tx += 1
            hb = frame.pack_heartbeat(seq)
            if self._host_fd is not None:
                try:
                    os.write(self._host_fd, hb)
                except OSError:
                    pass


def _signal_handler(node: 'UDFNode'):
    def handler(sig, _frame):
        node.stop()
        sys.exit(0)
    return handler


if __name__ == '__main__':
    """Demo: start a node, send 1000 frames in loopback, measure throughput."""
    node = UDFNode(node_id=1)

    signal.signal(signal.SIGINT, _signal_handler(node))
    signal.signal(signal.SIGTERM, _signal_handler(node))

    # Loopback demo (no hardware): measure pack/queue throughput
    print(f"UDFNode demo — node_id={node.node_id}, loopback 1000 frames")
    payload = b'\xAA' * 1024  # 1KB payload

    start = time.perf_counter()
    for i in range(1000):
        with node._lock:
            seq = node._seq_host_tx
            node._seq_host_tx += 1
        raw = frame.pack(node.node_id, 2, seq, payload)
        # Simulate RX by unpacking and enqueuing
        f = frame.unpack(raw)
        node._rx_queue.put(f)
        node._stats['frames_tx'] += 1
        node._stats['bytes_tx'] += len(payload)
    elapsed = time.perf_counter() - start

    # Drain RX queue
    rx_count = 0
    while not node._rx_queue.empty():
        node._rx_queue.get_nowait()
        rx_count += 1

    throughput_mbps = (1000 * len(payload) * 8) / (elapsed * 1e6)
    print(f"Sent 1000 frames in {elapsed*1000:.1f}ms")
    print(f"Throughput: {throughput_mbps:.1f} Mbps (pack+queue, no USB I/O)")
    print(f"RX dequeued: {rx_count}")
    print(f"Stats: {node._stats}")

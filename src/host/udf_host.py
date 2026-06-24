#!/usr/bin/env python3
"""UDF host-side daemon — libusb bulk transport via ctypes."""
import argparse, ctypes, ctypes.util, os, signal, struct, sys, threading, time
from collections import deque

# --- Path setup for frame module ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'common'))
import frame

# --- libusb ctypes bindings ---
_lib = ctypes.CDLL('libusb-1.0.so.0')

_lib.libusb_init.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
_lib.libusb_init.restype = ctypes.c_int

_lib.libusb_exit.argtypes = [ctypes.c_void_p]
_lib.libusb_exit.restype = None

_lib.libusb_open_device_with_vid_pid.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16]
_lib.libusb_open_device_with_vid_pid.restype = ctypes.c_void_p

_lib.libusb_claim_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.libusb_claim_interface.restype = ctypes.c_int

_lib.libusb_release_interface.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.libusb_release_interface.restype = ctypes.c_int

_lib.libusb_bulk_transfer.argtypes = [
    ctypes.c_void_p, ctypes.c_ubyte,
    ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int,
    ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
]
_lib.libusb_bulk_transfer.restype = ctypes.c_int

_lib.libusb_set_auto_detach_kernel_driver.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.libusb_set_auto_detach_kernel_driver.restype = ctypes.c_int

# libusb error codes
LIBUSB_ERROR_TIMEOUT = -7
LIBUSB_SUCCESS = 0

# UDF constants
VID = 0x1d6b
PID = 0x0105
EP_IN = 0x81
EP_OUT = 0x02
IFACE = 0
BULK_TIMEOUT_MS = 1000
BUF_SIZE = 16388  # max frame size


class UDFHost:
    def __init__(self, node_id: int, verbose: bool, duration: int):
        self.node_id = node_id
        self.verbose = verbose
        self.duration = duration
        self._running = False
        self._ctx = ctypes.c_void_p()
        self._handle = None
        self._tx_queue: deque = deque()
        self._rx_queue: deque = deque()
        self._tx_seq = 0
        self._hb_seq = 0
        self._lock = threading.Lock()
        # Stats
        self.tx_frames = 0
        self.tx_bytes = 0
        self.rx_frames = 0
        self.rx_bytes = 0
        self.rx_hb = 0
        self.crc_errors = 0
        self.timeouts = 0
        self._start_time = 0.0

    def open(self):
        rc = _lib.libusb_init(ctypes.byref(self._ctx))
        if rc != 0:
            raise RuntimeError(f"libusb_init failed: {rc}")
        self._handle = _lib.libusb_open_device_with_vid_pid(self._ctx, VID, PID)
        if not self._handle:
            _lib.libusb_exit(self._ctx)
            raise RuntimeError(f"Device {VID:04x}:{PID:04x} not found")
        _lib.libusb_set_auto_detach_kernel_driver(self._handle, 1)
        rc = _lib.libusb_claim_interface(self._handle, IFACE)
        if rc != 0:
            _lib.libusb_exit(self._ctx)
            raise RuntimeError(f"claim_interface failed: {rc}")
        print(f"[host] Opened UDF device {VID:04x}:{PID:04x}, interface {IFACE} claimed")

    def close(self):
        if self._handle:
            _lib.libusb_release_interface(self._handle, IFACE)
            self._handle = None
        if self._ctx:
            _lib.libusb_exit(self._ctx)
            self._ctx = ctypes.c_void_p()

    def _bulk_write(self, data: bytes) -> bool:
        buf = (ctypes.c_ubyte * len(data))(*data)
        transferred = ctypes.c_int(0)
        rc = _lib.libusb_bulk_transfer(self._handle, EP_OUT, buf, len(data),
                                       ctypes.byref(transferred), BULK_TIMEOUT_MS)
        if rc == LIBUSB_ERROR_TIMEOUT:
            self.timeouts += 1
            return False
        if rc != LIBUSB_SUCCESS:
            if self.verbose:
                print(f"[host] TX error: {rc}")
            return False
        self.tx_frames += 1
        self.tx_bytes += transferred.value
        return True

    def _bulk_read(self) -> bytes | None:
        buf = (ctypes.c_ubyte * BUF_SIZE)()
        transferred = ctypes.c_int(0)
        rc = _lib.libusb_bulk_transfer(self._handle, EP_IN, buf, BUF_SIZE,
                                       ctypes.byref(transferred), BULK_TIMEOUT_MS)
        if rc == LIBUSB_ERROR_TIMEOUT:
            self.timeouts += 1
            return None
        if rc != LIBUSB_SUCCESS:
            if self.verbose:
                print(f"[host] RX error: {rc}")
            return None
        return bytes(buf[:transferred.value])

    def _rx_loop(self):
        while self._running:
            data = self._bulk_read()
            if data is None:
                continue
            result = frame.unpack_frame(data)
            if result is None:
                self.crc_errors += 1
                continue
            flags, seq, src, dst, payload = result
            self.rx_frames += 1
            self.rx_bytes += len(data)
            if flags & frame.FLAG_HB:
                self.rx_hb += 1
            else:
                self._rx_queue.append((flags, seq, src, dst, payload))
            if self.verbose:
                print(f"[host] RX seq={seq} flags=0x{flags:02x} len={len(payload)}")

    def _tx_loop(self):
        while self._running:
            if self._tx_queue:
                payload = self._tx_queue.popleft()
                with self._lock:
                    seq = self._tx_seq
                    self._tx_seq += 1
                pkt = frame.pack_frame(0, seq, self.node_id, 0xFF, payload)
                self._bulk_write(pkt)
            else:
                time.sleep(0.001)

    def _hb_loop(self):
        while self._running:
            with self._lock:
                seq = self._tx_seq
                self._tx_seq += 1
            hb = frame.pack_heartbeat(seq, self.node_id)
            self._bulk_write(hb)
            time.sleep(0.1)

    def _stats_loop(self):
        while self._running:
            time.sleep(5)
            elapsed = time.monotonic() - self._start_time
            rx_mbps = (self.rx_bytes * 8 / 1e6) / elapsed if elapsed > 0 else 0
            tx_mbps = (self.tx_bytes * 8 / 1e6) / elapsed if elapsed > 0 else 0
            print(f"[host] {elapsed:.0f}s | "
                  f"TX: {self.tx_frames} frames {self.tx_bytes} bytes ({tx_mbps:.1f} Mbps) | "
                  f"RX: {self.rx_frames} frames {self.rx_bytes} bytes ({rx_mbps:.1f} Mbps) | "
                  f"HB_rx={self.rx_hb} crc_err={self.crc_errors} timeouts={self.timeouts}")

    def send(self, payload: bytes):
        self._tx_queue.append(payload)

    def run(self):
        self._running = True
        self._start_time = time.monotonic()
        threads = [
            threading.Thread(target=self._rx_loop, name='rx', daemon=True),
            threading.Thread(target=self._tx_loop, name='tx', daemon=True),
            threading.Thread(target=self._hb_loop, name='hb', daemon=True),
            threading.Thread(target=self._stats_loop, name='stats', daemon=True),
        ]
        for t in threads:
            t.start()
        print(f"[host] Running (node_id={self.node_id}, duration={self.duration or 'infinite'})")
        try:
            if self.duration > 0:
                time.sleep(self.duration)
            else:
                while self._running:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        self.stop()

    def stop(self):
        self._running = False
        elapsed = time.monotonic() - self._start_time
        print(f"\n[host] Final stats ({elapsed:.1f}s):")
        print(f"  TX: {self.tx_frames} frames, {self.tx_bytes} bytes")
        print(f"  RX: {self.rx_frames} frames, {self.rx_bytes} bytes")
        print(f"  HB received: {self.rx_hb}")
        print(f"  CRC errors: {self.crc_errors}, Timeouts: {self.timeouts}")
        if elapsed > 0:
            print(f"  Avg TX: {self.tx_bytes * 8 / elapsed / 1e6:.2f} Mbps")
            print(f"  Avg RX: {self.rx_bytes * 8 / elapsed / 1e6:.2f} Mbps")
        self.close()


def main():
    parser = argparse.ArgumentParser(description='UDF host-side daemon')
    parser.add_argument('--node-id', type=int, default=2)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--duration', type=int, default=0, help='Run duration in seconds (0=infinite)')
    args = parser.parse_args()

    host = UDFHost(args.node_id, args.verbose, args.duration)

    def _shutdown(sig, _):
        print(f"\n[host] Signal {sig}, shutting down...")
        host._running = False

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    host.open()
    host.run()


if __name__ == '__main__':
    main()

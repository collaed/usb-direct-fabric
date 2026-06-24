# USB Direct Fabric — Common Misunderstandings

A quick disambiguation for reviewers. Every point below was asked or assumed incorrectly by at least one reviewer of this project.

---

## "You can't connect two USB hosts together"

**Wrong.** One machine runs in **host mode** (standard xHCI). The other runs in **gadget/device mode** (via DWC3 xDCI). This is one host + one device — fully compliant with USB spec since USB OTG in 2001. It's how every Android phone does USB tethering.

UDF does NOT connect two hosts. It connects one host to one gadget over a standard USB3 cable.

---

## "This is USB4 / Thunderbolt"

**No.** USB4 uses PCIe tunneling over Thunderbolt. UDF uses **USB3 bulk endpoints** via the Linux FunctionFS gadget subsystem. Different hardware tier, different software layer, different mechanism entirely.

| | UDF | USB4/Thunderbolt |
|---|---|---|
| Physical layer | USB3 bulk (5/10 Gbps) | PCIe tunneled over USB4 (40/80 Gbps) |
| Software | Userspace (FunctionFS + libusb) | Kernel driver (`thunderbolt_net`) |
| Hardware needed | Any USB3 DRD port (€0 extra) | USB4/Thunderbolt controller (€200+ hardware) |
| Multi-hop routing | Yes (ring, crisscross, hub) | No (point-to-point only) |

---

## "This reinvents Ethernet"

**Partially true, intentionally.** UDF is a Layer 2 fabric — like Ethernet, but without:
- The kernel network stack (no sockets, no TCP, no IP, no SKB allocation)
- Fixed rate steps (no 1/2.5/5/10 GbE quantization — fills the pipe elastically)
- MTU constraints (frames up to 16KB, aligned to USB3 burst size)

If you need IP (SSH, NFS, HTTP), use UDF's CDC-NCM compatibility mode. If you need raw throughput with minimal latency, use the bulk path directly.

---

## "Where's the retransmission? This will lose data"

**By design.** UDF is a transport fabric (Layer 2), not a reliable stream protocol (Layer 4). This is identical to how Ethernet works:
- Ethernet drops corrupted frames silently. TCP retransmits above it.
- UDF drops corrupted frames silently. TCP retransmits above it (via CDC-NCM mode).

Adding retransmission to Layer 2 causes head-of-line blocking, bufferbloat, and higher latency — the opposite of UDF's goals. USB bulk already has hardware-level CRC16 + automatic retry for link errors.

Management frames (SYN, CAP, HELLO) DO have optional retry (§5.7.4). Data does not.

---

## "Python can't do 3.5 Gbps"

**Correct.** The Python implementation is a **protocol validator** (~100-400 Mbps), not a production data plane. This is explicitly documented (spec §6.3.4). The production path is C/Rust with `io_uring` or `mmap` on FunctionFS endpoints — a mechanical translation once the protocol is proven correct.

The spec claims 3.5-7.2 Gbps for the **wire format and hardware** (USB3 Gen 1/2 bulk throughput ceiling), not for the Python reference implementation.

---

## "This needs encryption / authentication"

**Not in v1.0.** The physical USB cable is the trust boundary — same as a direct-attach copper ethernet cable between two servers in a rack. You don't encrypt DAC links in a server rack.

For environments where physical trust is insufficient, v1.1 defines HMAC-SHA256 authentication (implemented in `frame.py`, tested). v1.2 defines ChaCha20-Poly1305 AEAD encryption. Both are negotiated during CAP exchange.

---

## "The benchmark shows 2.47 Gbps — is that UDF?"

**No.** That's the baseline measurement of the **existing 2.5G Realtek USB-ethernet adapters** (the thing UDF replaces). UDF raw bulk throughput has NOT been measured yet — it's blocked on enabling xDCI in BIOS.

The benchmark script (`benchmark_direct_link.sh`) measures the "before" state. Once xDCI is enabled, `bulk_bench.sh` and the UDF daemons will measure the "after" state.

---

## "Ring topologies are dead (Token Ring)"

UDF's ring is not Token Ring. There's no token passing, no deterministic access. It's store-and-forward routing over point-to-point USB links — closer to how BGP works on a ring of routers than to 1990s Token Ring LANs.

For 2-3 node home fabrics, a ring costs €0 in extra hardware. For fault tolerance, UDF supports crisscross (survives 1 cable failure) and star/hub (survives any single node failure except the hub).

---

## "What hardware do I actually need?"

One machine with a **USB Device Controller (UDC)** that can run in gadget mode:

| Hardware | UDC | Status |
|----------|-----|--------|
| Radxa Rock 5B (RK3588) | 2× USB3 DRD | ✅ Works out of the box |
| Intel NUC (Gemini Lake, Ice Lake+) | DWC3 xDCI | ⚠️ Often BIOS-disabled, needs unlock |
| Raspberry Pi 4/5 | 1× USB2 DRD | ❌ USB2 only (480 Mbps) — too slow |
| Any laptop with USB-C + xDCI | DWC3 | ⚠️ Varies by model |

The other machine just needs a standard USB3 host port (every machine made since 2012).

---

## "What's the current project status?"

| Component | Status |
|-----------|--------|
| Formal specification (v1.0) | ✅ Complete (1500+ lines, reviewed 9.0/10) |
| Wire format + auth (frame.py) | ✅ Implemented + tested (18 conformance tests pass) |
| Routing (ring, crisscross) | ✅ Implemented + tested |
| Gadget daemon (FunctionFS) | ✅ Implemented (not hardware-tested) |
| Host daemon (libusb ctypes) | ✅ Implemented (not hardware-tested) |
| Ethernet baseline benchmark | ✅ Measured (2.0-2.47 Gbps) |
| USB3 raw bulk benchmark | ❌ Blocked — xDCI disabled in BIOS |
| Hardware validation | ❌ Blocked — waiting for NUC with accessible xDCI |

**Single blocker**: enable xDCI on one machine (BIOS setting or acquire Rock 5B). Everything else is ready.

# USB Direct Fabric (UDF) Class Specification

| Field | Value |
|-------|-------|
| Revision | 1.0 |
| Date | 2026-06-22 |
| Status | Draft for Review |
| Authors | UDF Project |
| Classification | USB Device Class Specification |

---

## Table of Contents

1. [Scope](#1-scope)
2. [Normative References](#2-normative-references)
3. [Definitions and Abbreviations](#3-definitions-and-abbreviations)
4. [Device Framework](#4-device-framework)
5. [Protocol](#5-protocol)
6. [Routing](#6-routing)
7. [Topologies](#7-topologies)
8. [CDC-NCM Compatibility Mode](#8-cdc-ncm-compatibility-mode)
9. [Conformance](#9-conformance)
10. [Performance Targets](#10-performance-targets)
- [Appendix A: Benchmark Results Template](#appendix-a-benchmark-results-template)
- [Appendix B: Reference Implementation](#appendix-b-reference-implementation)
- [Appendix C: Bill of Materials](#appendix-c-bill-of-materials)
- [Revision History](#revision-history)

---

## 1. Scope

This specification defines the USB Direct Fabric (UDF) device class — a native USB bulk transport protocol that enables direct host-to-host communication at raw USB link speed, bypassing the fixed rate ceilings imposed by USB-to-ethernet adapters (1/2.5/5/10 GbE steps).

UDF fills the USB pipe elastically, achieving approximately 3.5 Gbps on USB3 Gen 1 (5 Gbps signaling) or approximately 7.2 Gbps on USB3 Gen 2 (10 Gbps signaling), using only standard USB bulk endpoints visible to any compliant host controller.

### 1.1 Supported Topologies

- **Point-to-point**: Two nodes, single cable (bidirectional USB link), or dual-cable for dedicated TX/RX paths.
- **Ring (degree 2)**: N nodes in a unidirectional ring. Each node exposes 1 gadget port and connects 1 host port to the next node's gadget.
- **Crisscross (degree 3)**: N nodes with 1 gadget port and 2 host ports each. Chord links halve diameter and survive single-cable failures.
- **Star/Hub (FX3)**: Central switch with N× Cypress FX3 controllers. Endpoints need no forwarding logic.

### 1.2 Design Constraints

- **No custom host-side drivers**: The gadget side presents standard USB bulk endpoints. The host side uses libusb or equivalent userspace USB access.
- **No pip dependencies**: Reference implementation uses Python stdlib + ctypes only.
- **Linux kernel gadget infrastructure**: FunctionFS, ConfigFS composite framework, DWC3 UDC driver.
- **Zero-copy friendly**: Frame header alignment ensures payload starts at offset 16, suitable for DMA.
- **USB3 burst-aligned**: Maximum payload fits within a single USB3 max burst (16 × 1024 = 16384 bytes).

### 1.3 Relationship to Other Specifications

UDF operates below the IP layer. For applications requiring TCP/UDP/ICMP, a CDC-NCM compatibility mode (§8) provides standard IP networking with 10–20% throughput overhead. A node MAY expose both UDF raw and CDC-NCM interfaces simultaneously as a composite USB gadget.

---

## 2. Normative References

The following documents are indispensable for the application of this specification. For dated references, only the edition cited applies. For undated references, the latest edition applies.

| # | Reference | Relevance |
|---|-----------|-----------|
| [USB32] | Universal Serial Bus 3.2 Specification, Revision 1.0, September 2017, USB Implementers Forum | Protocol layer (Chapter 8), Device Framework (Chapter 9), Bulk transfer model, SuperSpeed endpoint companion descriptors |
| [CDC-NCM] | Universal Serial Bus Communications Class Subclass Specification for Network Control Model Devices, Revision 1.0, November 2010, USB-IF | CDC-NCM compatibility mode descriptor format, NTB framing reference |
| [IEEE802.3] | IEEE Std 802.3-2022, Section 3 — Frame Check Sequence | CRC-32 polynomial: `0x04C11DB7` (normal form), also known as CRC-32/ISO-HDLC |
| [USB-NET] | USB-IF Device Class Definition for Network Devices, Version 1.0 | Class code assignments, network device model |
| [DWC3] | Synopsys DesignWare Cores USB 3.0 Controller Databook, Version 3.30a | Reference UDC hardware behavior, xDCI endpoint configuration |

---

## 3. Definitions and Abbreviations

| Term | Definition |
|------|------------|
| **UDF** | USB Direct Fabric — the protocol defined by this specification |
| **UDC** | USB Device Controller — hardware that implements the USB device (peripheral) role |
| **DWC3** | DesignWare Cores USB 3.0 — Synopsys IP block implementing USB3 device/host/OTG controller, used in Intel Gemini Lake and Ice Lake SoCs |
| **xDCI** | eXtensible Device Controller Interface — Intel's name for the DWC3 device-mode controller exposed in their SoCs |
| **FunctionFS** | Linux kernel filesystem interface allowing userspace programs to implement USB gadget functions without kernel modules |
| **ConfigFS** | Linux kernel filesystem for composing USB gadget configurations from userspace |
| **DRD** | Dual-Role Device — a USB controller capable of operating in both host and device modes |
| **NAK** | Negative Acknowledgment — USB hardware flow control signal indicating a device endpoint is temporarily unable to accept/provide data |
| **Bulk endpoint** | A USB endpoint type optimized for large, non-time-critical data transfers with error detection and retry |
| **Service interval** | The period between consecutive bus transactions to a given endpoint, determined by the host controller scheduler |
| **Max burst** | The maximum number of packets (1–16 for USB3) a SuperSpeed endpoint can send/receive in a single burst before requiring acknowledgment |
| **Ring topology** | A network arrangement where each node connects to exactly two neighbors, forming a closed loop |
| **Chord ring** | A ring augmented with shortcut links (chords) that reduce the network diameter |
| **SPOF** | Single Point of Failure — a component whose failure causes the entire system to fail |
| **Bisection bandwidth** | The minimum total bandwidth across any cut that divides the network into two equal halves |
| **TTL** | Time-To-Live — maximum number of forwarding hops before a frame is discarded (15 for UDF) |
| **CRC-32** | 32-bit Cyclic Redundancy Check using the IEEE 802.3 polynomial |
| **FX3** | Cypress EZ-USB FX3 — USB 3.0 peripheral controller with programmable firmware, suitable for hub/switch implementations |
| **NTB** | NCM Transfer Block — the framing unit used in CDC-NCM |

### 3.1 Key Words

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this document are to be interpreted as described in RFC 2119.


---

## 4. Device Framework

This section defines the USB descriptors that a UDF gadget MUST present to the host during enumeration. All multi-byte fields are little-endian unless otherwise noted.

### 4.1 Device Descriptor

The UDF gadget presents a vendor-specific device class with sub-class and protocol bytes encoding 'D' and 'F' (for "Direct Fabric").

| Offset | Field | Size | Value | Description |
|--------|-------|------|-------|-------------|
| 0 | bLength | 1 | 18 | Size of this descriptor |
| 1 | bDescriptorType | 1 | 0x01 | DEVICE descriptor type |
| 2 | bcdUSB | 2 | 0x0310 | USB 3.1 |
| 4 | bDeviceClass | 1 | 0xFF | Vendor-specific |
| 5 | bDeviceSubClass | 1 | 0x44 | 'D' — Direct |
| 6 | bDeviceProtocol | 1 | 0x46 | 'F' — Fabric |
| 7 | bMaxPacketSize0 | 1 | 9 | 2^9 = 512 bytes (USB3 control EP max) |
| 8 | idVendor | 2 | 0x1d6b | Linux Foundation (assigned) |
| 10 | idProduct | 2 | 0x0105 | UDF gadget product ID |
| 12 | bcdDevice | 2 | 0x0100 | Device release 1.0 |
| 14 | iManufacturer | 1 | 1 | Index of manufacturer string |
| 15 | iProduct | 1 | 2 | Index of product string |
| 16 | iSerialNumber | 1 | 3 | Index of serial number string |
| 17 | bNumConfigurations | 1 | 1 | Single configuration |

**Raw bytes (hex):**
```
12 01 10 03 FF 44 46 09 6B 1D 05 01 00 01 01 02 03 01
```

### 4.2 Configuration Descriptor

| Offset | Field | Size | Value | Description |
|--------|-------|------|-------|-------------|
| 0 | bLength | 1 | 9 | Size of this descriptor |
| 1 | bDescriptorType | 1 | 0x02 | CONFIGURATION descriptor type |
| 2 | wTotalLength | 2 | 44 | Total length of configuration + interface + endpoints + companions |
| 4 | bNumInterfaces | 1 | 1 | Single UDF interface |
| 5 | bConfigurationValue | 1 | 1 | Configuration 1 |
| 6 | iConfiguration | 1 | 0 | No string descriptor |
| 7 | bmAttributes | 1 | 0xC0 | Self-powered, no remote wakeup |
| 8 | bMaxPower | 1 | 0 | No bus power draw (self-powered) |

**Raw bytes (hex):**
```
09 02 2C 00 01 01 00 C0 00
```

### 4.3 Interface Descriptor

| Offset | Field | Size | Value | Description |
|--------|-------|------|-------|-------------|
| 0 | bLength | 1 | 9 | Size of this descriptor |
| 1 | bDescriptorType | 1 | 0x04 | INTERFACE descriptor type |
| 2 | bInterfaceNumber | 1 | 0 | First interface |
| 3 | bAlternateSetting | 1 | 0 | Default alternate setting |
| 4 | bNumEndpoints | 1 | 2 | One Bulk IN, one Bulk OUT |
| 5 | bInterfaceClass | 1 | 0xFF | Vendor-specific |
| 6 | bInterfaceSubClass | 1 | 0x01 | UDF subclass |
| 7 | bInterfaceProtocol | 1 | 0x01 | UDF Wire Format v0.1 |
| 8 | iInterface | 1 | 0 | No string descriptor |

**Raw bytes (hex):**
```
09 04 00 00 02 FF 01 01 00
```

### 4.4 Endpoint Descriptors

#### 4.4.1 Bulk IN Endpoint

| Offset | Field | Size | Value | Description |
|--------|-------|------|-------|-------------|
| 0 | bLength | 1 | 7 | Size of this descriptor |
| 1 | bDescriptorType | 1 | 0x05 | ENDPOINT descriptor type |
| 2 | bEndpointAddress | 1 | 0x81 | EP1 IN (device-to-host) |
| 3 | bmAttributes | 1 | 0x02 | Bulk transfer type |
| 4 | wMaxPacketSize | 2 | 1024 | USB3 bulk maximum (0x0400) |
| 6 | bInterval | 1 | 0 | Not applicable for bulk |

**Raw bytes (hex):**
```
07 05 81 02 00 04 00
```

#### 4.4.2 SuperSpeed Endpoint Companion (IN)

| Offset | Field | Size | Value | Description |
|--------|-------|------|-------|-------------|
| 0 | bLength | 1 | 6 | Size of this descriptor |
| 1 | bDescriptorType | 1 | 0x30 | SS_ENDPOINT_COMPANION descriptor type |
| 2 | bMaxBurst | 1 | 15 | 16 packets per burst (0-indexed: 15 means 16) |
| 3 | bmAttributes | 1 | 0x00 | No streams, no bulk streams |
| 4 | wBytesPerInterval | 2 | 0 | Not applicable for bulk |

**Raw bytes (hex):**
```
06 30 0F 00 00 00
```

#### 4.4.3 Bulk OUT Endpoint

| Offset | Field | Size | Value | Description |
|--------|-------|------|-------|-------------|
| 0 | bLength | 1 | 7 | Size of this descriptor |
| 1 | bDescriptorType | 1 | 0x05 | ENDPOINT descriptor type |
| 2 | bEndpointAddress | 1 | 0x02 | EP2 OUT (host-to-device) |
| 3 | bmAttributes | 1 | 0x02 | Bulk transfer type |
| 4 | wMaxPacketSize | 2 | 1024 | USB3 bulk maximum (0x0400) |
| 6 | bInterval | 1 | 0 | Not applicable for bulk |

**Raw bytes (hex):**
```
07 05 02 02 00 04 00
```

#### 4.4.4 SuperSpeed Endpoint Companion (OUT)

| Offset | Field | Size | Value | Description |
|--------|-------|------|-------|-------------|
| 0 | bLength | 1 | 6 | Size of this descriptor |
| 1 | bDescriptorType | 1 | 0x30 | SS_ENDPOINT_COMPANION descriptor type |
| 2 | bMaxBurst | 1 | 15 | 16 packets per burst (0-indexed: 15 means 16) |
| 3 | bmAttributes | 1 | 0x00 | No streams |
| 4 | wBytesPerInterval | 2 | 0 | Not applicable for bulk |

**Raw bytes (hex):**
```
06 30 0F 00 00 00
```

#### 4.4.5 Complete Configuration Block

Total wTotalLength = 9 (config) + 9 (interface) + 7 (EP IN) + 6 (SS companion IN) + 7 (EP OUT) + 6 (SS companion OUT) = **44 bytes**.

```
Complete descriptor set (hex, 44 bytes):
09 02 2C 00 01 01 00 C0 00   ← Configuration
09 04 00 00 02 FF 01 01 00   ← Interface
07 05 81 02 00 04 00         ← Bulk IN endpoint
06 30 0F 00 00 00            ← SS Companion (IN)
07 05 02 02 00 04 00         ← Bulk OUT endpoint
06 30 0F 00 00 00            ← SS Companion (OUT)
```

### 4.5 String Descriptors

| Index | Language | Value | Purpose |
|-------|----------|-------|---------|
| 0 | — | 0x0409 | Supported language (English US) |
| 1 | 0x0409 | `"Linux Foundation"` | Manufacturer name |
| 2 | 0x0409 | `"USB Direct Fabric"` | Product name |
| 3 | 0x0409 | `"{node_id:02X}-{unique_suffix}"` | Serial number (unique per device instance) |

The serial number string MUST encode the node's assigned ID (2 hex digits) followed by a hyphen and a unique suffix (implementation-defined, e.g., random hex or hardware serial). This allows the host to distinguish multiple UDF gadgets connected simultaneously.

**Example**: Node ID 0x01 → serial `"01-A3F7C2D1"`


---

## 5. Protocol

### 5.1 Frame Format

All UDF communication uses a fixed-header framed protocol over USB bulk transfers. Each frame consists of a 16-byte header, a variable-length payload (0–16368 bytes, padded to 16-byte alignment), and a 4-byte CRC-32 trailer.

#### 5.1.1 Frame Structure

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|      Magic (0x55, 0x46)       |    Flags      |   Hop Count   |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    Sequence Number (LE)                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   Source ID   |    Dest ID    |      Payload Length (LE)      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                     Reserved (must be 0)                      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                                                               |
|                   Payload (0–16368 bytes)                      |
|              (zero-padded to 16-byte alignment)               |
|                                                               |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                        CRC-32 (LE)                            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

#### 5.1.2 Byte-Level Layout

| Offset | Size (bytes) | Field | Type | Description |
|--------|-------------|-------|------|-------------|
| 0 | 2 | Magic | bytes | Fixed: `0x55 0x46` (ASCII 'U', 'F') |
| 2 | 1 | Flags | uint8 | Bitfield (see §5.1.3) |
| 3 | 1 | Hop Count | uint8 | Forwarding hop counter, originator sets 0 |
| 4 | 4 | Sequence Number | uint32 LE | Per-link-direction monotonic counter |
| 8 | 1 | Source Node ID | uint8 | Originating node (0x01–0xFE) |
| 9 | 1 | Destination Node ID | uint8 | Target node (0x01–0xFE, 0xFF=broadcast) |
| 10 | 2 | Payload Length | uint16 LE | Actual payload byte count before padding |
| 12 | 4 | Reserved | uint32 | MUST be 0x00000000 (future: flow control credits) |
| 16 | 0–16368 | Payload | bytes | Application data, zero-padded to 16B boundary |
| 16+N | 4 | CRC-32 | uint32 LE | IEEE 802.3 CRC over all preceding bytes |

Where N = `(payload_length + 15) & ~15` if payload_length > 0, else 0.

#### 5.1.3 Flags Byte

| Bit | Mask | Name | Description |
|-----|------|------|-------------|
| 0 | `0x01` | SYN | Connection initiation; resets sequence numbers |
| 1 | `0x02` | FIN | Connection teardown; sender enters DRAINING |
| 2 | `0x04` | ACK | Acknowledgment; combined with SYN/FIN for handshake |
| 3 | `0x08` | FWD | Frame has been forwarded by an intermediate node |
| 4 | `0x10` | HB | Heartbeat frame (standard 20-byte format, zero payload) |
| 5 | `0x20` | CAP | Capabilities exchange frame |
| 6 | `0x40` | — | Reserved, MUST be 0 |
| 7 | `0x80` | — | Reserved, MUST be 0 |

#### 5.1.4 Size Constraints

| Metric | Value | Derivation |
|--------|-------|------------|
| Maximum frame size | 16388 bytes | 16 (header) + 16368 (payload) + 4 (CRC) |
| Minimum frame size (data) | 20 bytes | 16 (header) + 0 (payload) + 4 (CRC) |
| Minimum frame size (heartbeat) | 20 bytes | 16 (header) + 4 (CRC), zero payload |
| USB3 burst capacity | 16384 bytes | 16 × 1024 (wMaxPacketSize × (bMaxBurst+1)) |
| Payload alignment | 16 bytes | Zero-padded to next 16-byte boundary |
| Maximum payload | 16368 bytes | 16384 − 16 (header) = 16368; CRC spills to next burst packet |

#### 5.1.5 CRC Computation

The CRC-32 field is computed using the IEEE 802.3 polynomial (`0x04C11DB7`, reflected/LSB-first as implemented in zlib's `crc32()`). The CRC covers all bytes from offset 0 through the end of the padded payload (i.e., header + padded payload, excluding the CRC field itself). The result is stored in little-endian byte order.

#### 5.1.6 Padding

```
padded_payload_size = (payload_length + 15) & ~15    if payload_length > 0
padded_payload_size = 0                              if payload_length == 0
total_frame_size    = 16 + padded_payload_size + 4
```

Padding bytes MUST be set to zero by the sender. Receivers MUST ignore padding bytes (only `payload_length` bytes of the payload are meaningful).

### 5.2 Connection Establishment

UDF uses a three-way handshake modeled after TCP but operating at the frame level.

#### 5.2.1 Handshake Sequence

```
Initiator                              Responder
─────────                              ─────────
    │                                      │
    │─── SYN (seq=0, src=A, dst=B) ──────→│  Initiator → SYN_SENT
    │                                      │  Responder → SYN_RECEIVED
    │←── SYN+ACK (seq=0, src=B, dst=A) ───│
    │                                      │
    │─── ACK (seq=1, src=A, dst=B) ──────→│  Both → ESTABLISHED
    │                                      │
    │←─→ CAP exchange (both send) ←─→      │  Capabilities negotiated
    │                                      │
    │←─→ DATA / HB ←─→                    │  Normal operation
```

#### 5.2.2 State Machine

| State | Entry Condition | Exit Condition |
|-------|----------------|----------------|
| IDLE | Initial state / connection closed | Send SYN or receive SYN |
| SYN_SENT | SYN transmitted | Receive SYN+ACK → ESTABLISHED; Timeout (5×100ms) → IDLE |
| SYN_RECEIVED | SYN received, SYN+ACK sent | Receive ACK → ESTABLISHED; Timeout (500ms) → IDLE |
| ESTABLISHED | Handshake complete | Send/recv FIN → DRAINING; 5 missed HB → CLOSED |
| DRAINING | FIN sent or received | FIN+ACK received or 200ms timeout → CLOSED |
| CLOSED | Teardown complete | Resources released → IDLE |

#### 5.2.3 SYN Retransmission

If the initiator does not receive SYN+ACK within 100ms, it MUST retransmit the SYN frame. After 5 consecutive failures (500ms total), the initiator MUST transition to IDLE and report connection failure to the application layer.

#### 5.2.4 CAP Exchange

Within 200ms of entering ESTABLISHED, both sides MUST send a CAP frame (flags=0x20). If no CAP frame is received within this window, the connection MUST be torn down with FIN.

**CAP Payload Format (16 bytes):**

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 2 | Protocol Version | uint16 LE — 0x0001 for v1.0 |
| 2 | 2 | Max Frame Size | uint16 LE — advertised maximum frame size |
| 4 | 1 | Node ID | uint8 — sender's node ID |
| 5 | 1 | Features Bitmap | uint8 — capability flags |
| 6 | 10 | Node Name | UTF-8 string, null-padded (see below) |

**Node Name Encoding:**
- Maximum 9 bytes of UTF-8 content + 1 mandatory null terminator = 10 bytes total.
- If the hostname exceeds 9 bytes when encoded as UTF-8, it MUST be **truncated** to 9 bytes (at a valid UTF-8 boundary) and null-terminated in position 10.
- Receivers MUST treat the name as null-terminated and ignore bytes after the first null.
- Multi-byte UTF-8 characters that would be split by the 9-byte limit MUST be removed entirely (do not store partial sequences).

**Features Bitmap:**

| Bit | Mask | Feature |
|-----|------|---------|
| 0 | `0x01` | Forwarding capable |
| 1 | `0x02` | CRC acceleration available (CPU CRC32 instructions, e.g., SSE4.2 or ARMv8 CRC) |
| 2 | `0x04` | Multi-link (node has >1 UDF interface) |
| 3–7 | — | Reserved (MUST be 0) |

> **Note on CRC acceleration (bit 1)**: This refers to CPU-native CRC32 instructions
> (Intel SSE4.2 `crc32` or ARM PMULL), NOT the USB controller's link-layer CRC engine.
> The DWC3/xHCI hardware CRC operates at the USB packet level and is not accessible
> for application-layer computation. When this bit is set, the peer MAY assume CRC
> validation adds negligible latency to the forwarding path.

**Negotiation Rules:**
- The effective max frame size for the link is `min(local_max, remote_max)`.
- If protocol versions are incompatible, the higher-version node MUST either downgrade or send FIN.
- Node IDs MUST be unique within the topology. On conflict, both sides send FIN.

### 5.3 Data Transfer

#### 5.3.1 Bulk IN/OUT Mapping

| Direction | USB Transfer | UDF Meaning |
|-----------|-------------|-------------|
| Gadget → Host | Bulk IN (EP 0x81) | Gadget transmits frames to the connected host |
| Host → Gadget | Bulk OUT (EP 0x02) | Host transmits frames to the connected gadget |

In a point-to-point link, machine A's gadget connects to machine B's host port. Machine A transmits via its gadget's Bulk IN; machine B transmits via Bulk OUT to A's gadget.

> **Important clarification**: A single USB 3.x cable carries independent Bulk IN and
> Bulk OUT pipes simultaneously — the physical layer is full-duplex. When this spec
> refers to "half-duplex" or "single-cable" operation in the topology sections (§7.1),
> it refers to the **forwarding path constraint** in a ring: each node has only one
> gadget port (one inbound link) and one host port (one outbound link), so traffic
> can only flow in one direction around the ring. The USB link itself is always
> bidirectional at the electrical level.

For full-duplex with dual cables: each machine has one gadget port (receiving from one neighbor) and one host connection (transmitting to the other neighbor's gadget), providing independent TX and RX paths on separate physical links.

#### 5.3.2 Sequence Numbers

- **Scope**: Per link direction. Each direction maintains an independent 32-bit counter.
- **Initial value**: 0 (reset on SYN handshake).
- **Increment**: +1 per transmitted frame (including heartbeats).
- **Wrap**: At 2^32 − 1, wraps to 0. No special signaling required.

**Receiver behavior:**
1. `frame.seq == expected_seq` → accept, increment expected_seq
2. `frame.seq > expected_seq` → gap detected, log warning, update `expected_seq = frame.seq + 1`, accept frame
3. `frame.seq < expected_seq` → duplicate or reorder, drop silently, increment duplicate counter

#### 5.3.3 Maximum Transfer Unit

The maximum payload per frame is 16368 bytes. Applications requiring larger messages MUST fragment at the application layer. UDF provides no built-in fragmentation or reassembly.

### 5.4 Heartbeat

Heartbeat frames use the standard 20-byte minimum frame format (full header + CRC, zero payload). This ensures uniform transfer sizes at the USB bulk endpoint boundary, preventing short-packet synchronization issues in asynchronous URB submission queues.

#### 5.4.1 Heartbeat Frame Format

A heartbeat is a normal UDF frame with:
- Flags = `0x10` (HB bit set)
- Payload Length = 0
- Source = sender's node ID
- Destination = 0x00 (ignored by receiver)
- Hop = 0
- CRC-32 computed over the 16-byte header as usual

**Total: 20 bytes (16-byte header + 4-byte CRC). No payload.**

> **Design rationale**: An earlier draft used a shortened 8-byte format without CRC.
> This was rejected because: (1) variable-size transfers (8B vs 16KB) can thrash
> asynchronous URB pools in userspace implementations; (2) without CRC, a corrupted
> data frame could be misidentified as a heartbeat if it happens to have the HB bit
> set and appears short due to a truncated USB transfer; (3) the bandwidth cost
> difference between 8 and 20 bytes at 5 Gbps is 0.00003% — completely negligible.

#### 5.4.2 Timing

| Parameter | Value |
|-----------|-------|
| Heartbeat interval | 100 ms |
| Dead detection threshold | 500 ms (5 consecutive missed heartbeats) |

#### 5.4.3 Sender Behavior

- Transmit one HB frame every 100ms when no data frame has been sent within that interval.
- If a data frame was sent within the 100ms interval, the heartbeat MAY be suppressed (data frames prove liveness).
- Heartbeats consume sequence numbers (they are sequenced like data frames).

#### 5.4.4 Receiver Behavior

- Maintain a `last_seen` timestamp, updated on receipt of ANY valid frame (data or HB).
- If `now − last_seen > 500ms`, declare link dead and transition to CLOSED state.
- No heartbeat acknowledgment is required.

#### 5.4.5 Heartbeat Activation

- No heartbeats are sent during SYN_SENT or SYN_RECEIVED states.
- Heartbeat transmission begins immediately upon entering ESTABLISHED.

### 5.5 Connection Termination

#### 5.5.1 Graceful Shutdown

```
Side A                                 Side B
──────                                 ──────
   │                                      │
   │─── FIN (flags=0x02) ───────────────→ │  A enters DRAINING
   │                                      │  B enters DRAINING
   │←── FIN+ACK (flags=0x06) ────────────│
   │                                      │
   │  → CLOSED                            │  → CLOSED
```

#### 5.5.2 Timeout-Based Shutdown

If no FIN+ACK is received within 200ms of sending FIN, the sender transitions directly to CLOSED. This prevents indefinite DRAINING state if the peer has already disconnected.

#### 5.5.3 Ungraceful Disconnect

If 5 consecutive heartbeats are missed (500ms), the node transitions directly from ESTABLISHED to CLOSED without FIN exchange. The application layer is notified of abrupt disconnection.

### 5.6 Flow Control

#### 5.6.1 NAK-Based Hardware Flow Control (v1.0)

UDF v1.0 relies entirely on the USB hardware's native flow control:

1. The gadget-side UDC posts Bulk OUT receive buffers via FunctionFS.
2. When all receive buffers are consumed, the UDC hardware returns NAK to the host's Bulk OUT transfer.
3. The host xHCI controller retries per the USB 3.x specification (hardware-level, transparent to software).
4. When the gadget reposts buffers, the next host retry succeeds.

This provides back-pressure with zero software overhead and zero additional protocol messages.

#### 5.6.2 No Software Flow Control

UDF v1.0 does NOT implement:
- Window advertisements
- Credit-based schemes
- PAUSE frames
- Rate limiting at the protocol level

#### 5.6.3 Future Extension (Informative)

The 4-byte Reserved field (offset 12–15) is designated for future credit-based flow control:
- Sender includes remaining TX credits in Reserved[0:1] (uint16 LE)
- Receiver grants credits via ACK frames with credit count in Reserved[0:1]

This is NOT implemented in v1.0. The Reserved field MUST be zero.

### 5.7 Error Handling

#### 5.7.1 Error Conditions and Actions

| Condition | Detection | Action | Counter |
|-----------|-----------|--------|---------|
| CRC-32 mismatch | Computed CRC ≠ stored CRC | Drop frame silently | `crc_errors` |
| Invalid magic bytes | Bytes 0–1 ≠ 0x55 0x46 | Drop frame silently | `sync_errors` |
| Sequence gap | `frame.seq > expected_seq` | Accept frame, log, update expected | `seq_gaps` |
| Sequence duplicate | `frame.seq < expected_seq` | Drop frame silently | `seq_duplicates` |
| Hop count exceeded | `hop_count > 15` | Drop frame, do not forward | `ttl_exceeded` |
| Payload oversize | `payload_length > 16368` | Drop frame silently | `oversize_errors` |
| Reserved non-zero | `reserved ≠ 0x00000000` | Accept frame (forward-compatible), log | `reserved_nonzero` |
| Unknown flags | Bits 6–7 set | Accept frame, ignore unknown bits | — |
| CAP timeout | No CAP within 200ms of ESTABLISHED | Send FIN, close connection | `cap_timeouts` |

#### 5.7.2 No Retransmission

UDF v1.0 does NOT perform retransmission at the transport layer. Rationale:
1. USB bulk transfers are reliable at the link layer (CRC16 per packet + hardware retry).
2. Frame-level CRC-32 detects software bugs or buffer corruption, not cable errors.
3. Retransmission adds buffering complexity incompatible with zero-copy goals.

Reliability for application data MUST be implemented at a higher layer if needed.

#### 5.7.3 Error Counters

All error counters are unsigned 64-bit integers, monotonically increasing, never reset (wrap at 2^64). Implementations SHOULD expose counters via a local management interface (sysfs, procfs, or Unix domain socket).

#### 5.7.4 Optional Management Frame Reliability

While data frame reliability is explicitly delegated to higher layers (§5.7.2), management frames (SYN, CAP, HELLO) are critical for fabric operation. Implementations MAY provide lightweight acknowledgment for these frames:

- **SYN/ACK**: Already defined in the handshake (§5.2). No change needed.
- **CAP**: Sender SHOULD retransmit the CAP frame up to 3 times (200ms interval) if no response is received within 200ms of the initial CAP exchange window.
- **HELLO**: In multi-hop topologies, a HELLO frame that traverses the full ring and returns to the originator serves as implicit acknowledgment. If the originator does not receive its own HELLO back within `N × 200ms` (where N = expected ring size), it SHOULD re-flood.

**Failure behavior when retries are exhausted:**

| Frame | Max Retries | On Exhaustion |
|-------|-------------|---------------|
| SYN | 5 (per §5.2.3) | Transition to IDLE. Log `syn_failures`. Notify application: "connection refused". |
| CAP | 3 | Send FIN. Transition to CLOSED. Log `cap_timeouts`. Notify application: "negotiation failed". |
| HELLO | 3 re-floods | Do NOT tear down existing links. Mark the non-responding segment as "unconfirmed". Log `hello_timeouts`. Routing table remains based on last-known-good topology. |

The key principle: **management frame failure on an established link does NOT tear down that link** (HELLO case). Only handshake failures (SYN, CAP) prevent a link from forming. Once ESTABLISHED, only heartbeat timeout (§5.4.4) can kill a link.

This mechanism is OPTIONAL. Implementations that omit it MUST still handle the case where a CAP or HELLO is lost (eventual consistency via periodic re-announcement, recommended every 10 seconds for HELLO).

#### 5.7.5 Security Extension (v1.1 — Concrete Design)

UDF v1.0 operates with a physical trust model: the USB cable is the security boundary. This section defines the **concrete authenticated mode** for UDF v1.1, suitable for environments where cable-level trust is insufficient.

##### 5.7.5.1 Authentication Tag Placement

When authenticated mode is active, a 16-byte HMAC-SHA256 truncated tag is appended **between the payload and the CRC**:

```
┌────────────────────┐
│  Header (16B)      │
├────────────────────┤
│  Payload (0–16336B)│  ← max payload reduced by 32B to keep total ≤ 16388
├────────────────────┤
│  Auth Tag (16B)    │  ← HMAC-SHA256 truncated to 128 bits
├────────────────────┤
│  CRC-32 (4B)      │  ← covers header + payload + auth tag
└────────────────────┘
```

**Maximum payload in authenticated mode**: 16336 bytes (16368 − 32 for tag + alignment).

The Auth Tag is computed over: `HMAC-SHA256(PSK, header || padded_payload)`, truncated to the first 16 bytes. The CRC covers everything including the tag.

##### 5.7.5.2 Negotiation

Authentication is negotiated during CAP exchange:
- Bit 3 (`0x08`) of the Features Bitmap = "Authentication required"
- If both peers set this bit, authenticated mode is active for the link
- If one peer sets it and the other does not → the requiring peer sends FIN (incompatible)
- If neither sets it → unauthenticated mode (v1.0 behavior)

##### 5.7.5.3 Key Management

| Method | Mechanism | When to use |
|--------|-----------|-------------|
| Pre-shared key (PSK) | 32-byte key in `/etc/udf/psk.key` (file mode 0600). Both peers MUST have the same key. | Small fabrics (2-8 nodes), manual deployment |
| Per-link key derivation | `link_key = HKDF-SHA256(PSK, salt=src_id||dst_id||cap_nonce)` | Prevents replay across links |

The CAP frame in authenticated mode includes a 4-byte random nonce in the Reserved field (bytes 12–15) for key derivation. Each link derives its own key from the shared PSK + both node IDs + this nonce.

##### 5.7.5.4 Encryption (Optional, v1.2+)

When both confidentiality and authentication are needed:
- Use ChaCha20-Poly1305 AEAD
- Header remains cleartext (for forwarding)
- Payload is encrypted in-place; the 16-byte Poly1305 tag replaces the HMAC tag
- Nonce: `link_key_id (4B) || sequence_number (4B) || zeros (4B)` = 12 bytes
- Negotiated via Features Bitmap bit 4 (`0x10`) = "Encryption available"

##### 5.7.5.5 Trust Model Summary

| Deployment | Mode | Overhead | Protection |
|------------|------|----------|------------|
| Home fabric (sake↔beirao) | Unauthenticated (v1.0) | 0 bytes | Physical cable = trust |
| Multi-room / shared rack | Authenticated (v1.1) | +16 bytes/frame | Spoofing, injection, topology poisoning |
| Untrusted environment | Encrypted (v1.2) | +16 bytes/frame | Full confidentiality + integrity |

Implementations MUST NOT rely on CRC-32 for security — it is trivially forgeable. CRC-32 detects transmission errors only.

### 5.8 Broadcast Storm Prevention

In multi-hop topologies, broadcast frames (dst=0xFF) and forwarded HELLO frames can circulate indefinitely if not properly bounded. Implementations supporting forwarding MUST implement source-based deduplication:

#### 5.8.1 Deduplication Table

Each forwarding node maintains a table of recently seen `(source_node_id, sequence_number)` pairs:

| Field | Description |
|-------|-------------|
| Source ID | The frame's original source (not the forwarding node) |
| Sequence | The frame's sequence number |
| Timestamp | When the entry was created |

**Rules:**
1. On receiving a broadcast or forwarded frame, compute the key `(src, seq)`.
2. If the key exists in the deduplication table → **drop the frame** (already seen/forwarded).
3. If the key does not exist → **add it** to the table, process/forward the frame normally.
4. Entries expire after 5 seconds (TTL). Expired entries are removed lazily or on a periodic sweep (every 1 second).

#### 5.8.2 Table Size

The table need not be large. At maximum frame rate (~55,000 frames/sec) with 254 possible sources, a 16,384-entry hash table with 5-second TTL is more than sufficient. Memory cost: <512 KB.

#### 5.8.3 Hop Count as Backup

Even with deduplication, the hop count limit of 15 (§6.3.2) serves as a hard safety net: frames that somehow escape deduplication will be dropped after 15 hops regardless.


---

## 6. Routing

UDF supports multi-hop communication through store-and-forward routing. This section is normative for implementations that support forwarding (multi-hop topologies). Point-to-point implementations MAY omit routing logic entirely.

### 6.1 Node Addressing

| Address | Meaning |
|---------|---------|
| 0x00 | Unassigned (MUST NOT appear in frames on the wire) |
| 0x01–0xFE | Valid node identifiers (254 usable addresses) |
| 0xFF | Broadcast — delivered to all reachable nodes |

Node IDs are assigned statically at deployment time or dynamically via an out-of-band mechanism. This specification does not define a dynamic address assignment protocol; implementations MAY use any method (configuration file, DHCP-like service, user assignment).

**Node ID Assignment Procedure (Informative):**

For small fabrics (2–4 nodes), the recommended procedure is:
1. Assign sequential IDs starting from 0x01 at initial deployment (e.g., `sake=0x01`, `beirao=0x02`).
2. Record assignments in a static configuration file on each node (e.g., `/etc/udf/node.conf`).
3. Pass the node ID as a command-line argument to the UDF daemon at startup.
4. When adding a node to an existing fabric, assign the next unused ID and update all nodes' ring membership configuration.

Automatic node ID assignment (e.g., lowest-MAC-wins, or coordinator-based allocation) is reserved for a future revision of this specification. Implementations MUST NOT assume dynamic ID assignment is available.

Node IDs MUST be unique within a connected topology. Duplicate detection occurs during CAP exchange (§5.2.4): if a node receives a CAP frame containing its own node ID from a different link, it MUST send FIN on the conflicting link and log an error.

### 6.2 Neighbor Discovery

#### 6.2.1 HELLO Frame

Nodes discover ring membership via HELLO frames — broadcast UDF data frames with a structured payload.

**HELLO Payload Format:**

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | HELLO Magic | Fixed: `0x48` (ASCII 'H') |
| 1 | 1 | Originator | Node ID of the HELLO sender |
| 2 | 1 | Count | Number of known nodes in the path list |
| 3 | N | Node List | Ordered list of node IDs (1 byte each) |

HELLO frames are sent as standard UDF data frames with `dst=0xFF` (broadcast) and no special flag bits. They are distinguished by the `0x48` magic byte at payload offset 0.

#### 6.2.2 HELLO Transmission Rules

- A node MUST send a HELLO frame on all links immediately upon entering ESTABLISHED state.
- A node MUST send a HELLO frame whenever its routing table changes (neighbor added or removed).
- A node SHOULD send periodic HELLO frames every 10 seconds as a keep-alive mechanism for ring membership.
- The node list in a HELLO frame contains all nodes the sender currently knows about (from its routing table).

#### 6.2.3 HELLO Reception and Ring Learning

Upon receiving a HELLO frame:
1. Extract the originator and node list from the payload.
2. Merge the node list into the local ring membership set.
3. Recompute the routing table (§6.5).
4. If the HELLO contains nodes not previously known, forward the HELLO on all other links (flooding).
5. If all nodes in the HELLO are already known, do not re-flood (loop prevention).

### 6.3 Forwarding

#### 6.3.1 Store-and-Forward Model

UDF uses store-and-forward routing: an intermediate node receives a complete frame, validates it, then retransmits on the appropriate outbound link.

#### 6.3.2 Forwarding Algorithm

When a node receives a frame where `dst ≠ self.node_id` and `dst ≠ 0xFF`:

1. Check `hop_count`: if `hop_count > 15` → drop frame, increment `ttl_exceeded` counter, STOP.
2. Increment `hop_count` by 1.
3. Set the FWD flag (bit 3, `0x08`) by ORing with existing flags.
4. Look up `dst` in the routing table to determine the outbound port.
5. If no route exists → drop frame, increment `dropped` counter, STOP.
6. Assign a new sequence number from the outbound link's TX sequence space.
7. Recompute the CRC-32 over the modified frame.
8. Transmit on the outbound link.

#### 6.3.3 Broadcast Forwarding

When `dst = 0xFF`:
1. Deliver the frame locally (to the application layer).
2. Forward on all links EXCEPT the link from which the frame was received.
3. Increment hop_count and set FWD flag as with unicast.
4. If `hop_count > 15` after increment → do not forward (prevents broadcast storms in mis-wired topologies).

#### 6.3.4 Forwarding Latency Budget

Implementations SHOULD forward frames within 50 µs of reception (measured from last byte received to first byte transmitted on outbound link). This budget assumes:
- Frame is in kernel buffer (no disk I/O)
- Routing table lookup is O(1) (hash table or direct array index)
- CRC recomputation completes within the budget
- Implementation language supports zero-copy or near-zero-copy buffer passing

> **Implementation note**: The 50 µs target is achievable in C or Rust implementations
> with direct FunctionFS `mmap()` or `io_uring` submission. The Python reference
> implementation (Appendix B) will typically exhibit 200–500 µs forwarding latency due
> to GIL contention, ctypes marshaling overhead, and userspace buffer copies. This does
> not affect conformance (this section is informative), but production deployments
> requiring <50 µs per hop SHOULD use a compiled-language implementation.

### 6.4 Dead Node Detection

#### 6.4.1 Heartbeat-Based Liveness

Each node monitors all directly connected neighbors via the heartbeat mechanism (§5.4):
- Maintain a `last_seen[neighbor_id]` timestamp per link.
- Update on receipt of ANY valid frame from that link.
- If `now − last_seen[neighbor_id] > 500ms` → declare neighbor dead.

#### 6.4.2 Dead Neighbor Actions

Upon detecting a dead neighbor:
1. Transition the link state to CLOSED.
2. Remove the neighbor from the routing table.
3. Recompute routes for all known destinations.
4. Send a HELLO frame on all remaining live links (to propagate the topology change).
5. Log the event with the dead neighbor's node ID and time of last frame.

#### 6.4.3 Reconnection

A previously dead neighbor MAY reconnect by initiating a new SYN handshake. The surviving node MUST accept the SYN and re-integrate the neighbor into the routing table upon successful handshake.

### 6.5 Routing Table Construction

#### 6.5.1 Ring Topology (Unidirectional Shortest-Path)

In a ring of N nodes, each node has exactly two neighbors (clockwise and counter-clockwise). The routing table assigns each destination to the shorter of the two directions:

> **Static configuration requirement**: Ring node ordering (the assignment of each
> node ID to a position in the ring) is **statically configured**, not dynamically
> discovered. Each node must be told its ring index and the total ring membership at
> startup (via command-line arguments, configuration file, or the CAP exchange with
> immediate neighbors). HELLO flooding confirms the topology but does not establish
> ring order — it only validates that the pre-configured ordering matches physical
> cabling. A misconfigured node (wrong index) will be detected by HELLO frames
> arriving with unexpected ring membership and MUST log a warning.

```python
for each destination D:
    cw_distance  = (index_of(D) - index_of(self)) mod N
    ccw_distance = (index_of(self) - index_of(D)) mod N
    if cw_distance <= ccw_distance:
        route[D] = clockwise_port     # 'host' by convention
    else:
        route[D] = counter_clockwise_port  # 'gadget' by convention
```

Ties (equidistant) are broken in favor of the clockwise direction.

#### 6.5.2 Crisscross Topology (Shortest-Path with Chords)

In a crisscross topology, each node has 3 links (1 gadget + 2 host). The routing table is computed via BFS from the local node:

1. Initialize distances: `dist[self] = 0`, all others = ∞.
2. BFS from self, exploring all links. For each neighbor reached, record the first-hop port used.
3. For each destination, the route is the first-hop port from the BFS tree.

This gives shortest-path routing with O(N) computation.

#### 6.5.3 Star/Hub Topology (Switching Table)

In a star topology, the central hub maintains a switching table mapping node IDs to physical ports:

| Node ID | Port |
|---------|------|
| 0x01 | FX3 Port 0 |
| 0x02 | FX3 Port 1 |
| ... | ... |
| 0xNN | FX3 Port N-1 |

The hub learns port assignments from CAP frames received on each port. Endpoint nodes need no routing logic — they send all frames to the hub, which switches based on destination.

Unknown destinations are flooded on all ports (unknown unicast flooding), then learned from return traffic.


---

## 7. Topologies

### 7.1 Ring (Degree 2)

#### 7.1.1 Description

Each node exposes 1 UDC (gadget) port and connects 1 host port to the next node's gadget, forming a unidirectional ring. The minimum ring size is 3 nodes (2-node ring degenerates to point-to-point with dual cables).

#### 7.1.2 Wiring Diagram (4 Nodes)

```
         ┌──── Host ────→ Gadget ────┐
         │                            │
     Node A                       Node B
         │                            │
         └── Gadget ←── Host ─────── ┘
              ↑                         │
              │                         ↓
         Node D                       Node C
              │                         │
              └──── Host ────→ Gadget ──┘

Ring direction: A → B → C → D → A (clockwise)
Host TX → neighbor Gadget RX
```

#### 7.1.3 Properties

| Property | Value |
|----------|-------|
| Cables per node | 1 (USB3, connecting host port to next node's gadget) |
| Total cables (N nodes) | N |
| Degree | 2 (1 gadget link + 1 host link) |
| Diameter | ⌊N/2⌋ hops |
| Bisection bandwidth | 2 × link bandwidth (cut must sever 2 cables) |
| Fault tolerance | 0 — one cable failure cuts the ring |
| Max burst throughput per pair | Link speed (single path) |
| Hardware per node | 1 UDC + 1 host USB3 port |

#### 7.1.4 Failure Mode

A single cable failure partitions the ring into a line. Nodes on opposite sides of the cut cannot communicate. Recovery requires physical cable repair or topology reconfiguration.

### 7.2 Crisscross (Degree 3)

#### 7.2.1 Description

Each node exposes 1 UDC (gadget) port and connects 2 host ports to non-adjacent nodes' gadgets. The extra "chord" links halve the ring diameter and provide redundancy.

#### 7.2.2 Wiring Diagram (4 Nodes)

```
     Node A ─────────Host[0]─────────→ Gadget Node B
       │                                     │
       │ Host[1]                    Host[1]  │
       │        ╲                  ╱         │
       ↓         ╲                ╱          ↓
     Gadget       ╲              ╱        Gadget
     Node D        ╲            ╱         Node C
       │            ╲          ╱             │
       └──Host[0]────→  (cross)  ←──Host[0]─┘

Chord links (A→C, B→D) reduce diameter from 2 to 1.
```

#### 7.2.3 Properties

| Property | Value |
|----------|-------|
| Cables per node | 2 (connecting 2 host ports to non-adjacent gadgets) |
| Total cables (N nodes) | 3N/2 (for even N) |
| Degree | 3 (1 gadget link + 2 host links) |
| Diameter | ⌈N/4⌉ hops (halved vs ring) |
| Bisection bandwidth | 3 × link bandwidth |
| Fault tolerance | 1 — survives any single cable failure |
| Max burst throughput per pair | 2 × link speed (parallel paths) |
| Hardware per node | 1 UDC + 2 host USB3 ports |

#### 7.2.4 Failure Mode

Any single cable failure leaves all node pairs still connected via an alternate path. The diameter may increase by 1 hop. Two failures on the same node can isolate it.

### 7.3 Star/Hub (FX3)

#### 7.3.1 Description

A central switch device (implemented with Cypress FX3 or equivalent multi-port USB3 controller) connects to all endpoint nodes. Each endpoint connects one host port to a port on the central hub's multi-gadget interface.

#### 7.3.2 Wiring Diagram (4 Nodes)

```
     Node A ──Host──→ ┌──────────┐ ←──Host── Node B
                      │   HUB    │
     Node C ──Host──→ │  (FX3)   │ ←──Host── Node D
                      └──────────┘

Hub has N gadget-mode ports, one per endpoint node.
All switching logic runs on the hub.
```

#### 7.3.3 Properties

| Property | Value |
|----------|-------|
| Cables per node | 1 (to hub) |
| Total cables | N (plus hub device) |
| Degree | 1 (from endpoint perspective) |
| Diameter | 2 hops (source → hub → destination) |
| Bisection bandwidth | N/2 × link bandwidth (non-blocking switch) |
| Fault tolerance | 0 — hub is SPOF; any cable failure isolates that node |
| Max burst throughput per pair | Link speed (through hub) |
| Hardware per node | 1 host USB3 port only (no UDC needed at endpoints) |
| Hub hardware | N× FX3 controllers or multi-port USB3 device PHY |

#### 7.3.4 Failure Mode

The hub is a single point of failure. Hub failure takes down the entire fabric. Individual cable failures isolate only the affected endpoint. Endpoints need no forwarding logic.

### 7.4 Comparison Table

| Property | Ring | Crisscross | Star/Hub |
|----------|------|-----------|----------|
| Degree per node | 2 | 3 | 1 (endpoint) |
| Cables (4 nodes) | 4 | 6 | 4 + hub |
| Diameter (4 nodes) | 2 hops | 1 hop | 2 hops |
| Fault tolerance | 0 | 1 cable | 0 (hub=SPOF) |
| Forwarding needed | Yes (all nodes) | Yes (all nodes) | No (hub only) |
| UDC required per node | Yes | Yes | No |
| Cost (4 nodes) | ~€40 | ~€60 | ~€300–450 |
| Max aggregate throughput | 2 × link | 3 × link | N/2 × link |
| Complexity | Low | Medium | High (hub firmware) |

### 7.5 Recommendations by Scale

| Scale | Recommended Topology | Rationale |
|-------|---------------------|-----------|
| 2 nodes | Point-to-point (dual cable) | Simplest; full-duplex with no forwarding |
| 3–4 nodes | Ring | Minimal cabling; acceptable diameter |
| 4–8 nodes | Crisscross | Halved diameter; fault tolerance worth the extra cables |
| 8–16 nodes | Star/Hub (FX3) | Endpoints need no UDC; centralized switching simplifies management |
| 16+ nodes | Hierarchical hub or fat-tree | Beyond UDF v1.0 scope; requires multi-hub cascading |


---

## 8. CDC-NCM Compatibility Mode

### 8.1 Purpose

While UDF provides maximum throughput via raw bulk transport, many applications require standard IP networking (TCP, UDP, ICMP, DNS, etc.). The CDC-NCM compatibility mode provides a standard network interface that the operating system recognizes natively, enabling IP-based communication over the same USB hardware without custom drivers on either side.

### 8.2 Descriptor Changes

When operating in CDC-NCM mode, the gadget replaces the UDF vendor-specific interface with standard CDC-NCM descriptors:

#### 8.2.1 Device Descriptor Changes

| Field | UDF Value | CDC-NCM Value |
|-------|-----------|---------------|
| bDeviceClass | 0xFF | 0x02 (Communications) |
| bDeviceSubClass | 0x44 | 0x00 |
| bDeviceProtocol | 0x46 | 0x00 |

#### 8.2.2 Interface Descriptors (CDC-NCM)

**Communication Interface (Interface 0):**

| Field | Value | Description |
|-------|-------|-------------|
| bInterfaceClass | 0x02 | Communications Interface Class |
| bInterfaceSubClass | 0x0D | NCM subclass |
| bInterfaceProtocol | 0x00 | No protocol |
| bNumEndpoints | 1 | Interrupt IN for notifications |

**Data Interface (Interface 1):**

| Field | Value | Description |
|-------|-------|-------------|
| bInterfaceClass | 0x0A | Data Interface Class |
| bInterfaceSubClass | 0x00 | — |
| bInterfaceProtocol | 0x01 | NCM |
| bNumEndpoints | 2 | Bulk IN + Bulk OUT |

#### 8.2.3 NCM Functional Descriptors

The CDC-NCM function additionally requires:
- CDC Header Functional Descriptor (5 bytes)
- CDC Union Functional Descriptor (5 bytes)
- ECM Functional Descriptor (13 bytes, includes MAC address)
- NCM Functional Descriptor (6 bytes, NTB parameters)

These follow the [CDC-NCM] specification exactly. Implementations SHOULD use the Linux `f_ncm` FunctionFS function or equivalent.

### 8.3 Overhead Analysis

| Factor | UDF Raw | CDC-NCM | Delta |
|--------|---------|---------|-------|
| Frame header | 16 bytes | 12 bytes (NTH) + 8–16 bytes (NDP) per datagram | +4–16 bytes |
| CRC | 4 bytes (UDF CRC-32) | Optional (NCM CRC-32 per datagram) | Similar |
| IP/TCP headers | Not applicable | 40 bytes minimum (IPv4+TCP) | +40 bytes per packet |
| NTB aggregation | Not applicable | Up to 64KB NTB with multiple datagrams | Amortizes overhead |
| Protocol stack | Zero (userspace direct) | Full kernel network stack | CPU overhead |
| **Expected throughput reduction** | — | — | **10–20%** |

The 10–20% overhead comes primarily from:
1. IP/TCP header overhead on small packets
2. Kernel network stack processing (context switches, SKB allocation)
3. NTB framing overhead (NTH + NDP pointers)
4. Interrupt endpoint polling for NCM notifications

For bulk transfers with large payloads (>8KB), the overhead approaches 10%. For small-packet workloads (VoIP, interactive), overhead can reach 20%.

### 8.4 Coexistence

A UDF node MAY expose both a UDF raw interface AND a CDC-NCM interface simultaneously using a multi-function composite USB gadget.

#### 8.4.1 Composite Gadget Configuration

```
Configuration 1:
├── Interface 0: UDF Raw (bInterfaceClass=0xFF, SubClass=0x01, Protocol=0x01)
│   ├── Bulk IN (EP 0x81)
│   └── Bulk OUT (EP 0x02)
├── Interface 1: CDC-NCM Communication (bInterfaceClass=0x02, SubClass=0x0D)
│   └── Interrupt IN (EP 0x83) — notifications
└── Interface 2: CDC-NCM Data (bInterfaceClass=0x0A, SubClass=0x00)
    ├── Bulk IN (EP 0x84)
    └── Bulk OUT (EP 0x05)
```

#### 8.4.2 Endpoint Allocation

In composite mode, the UDF and NCM functions use separate endpoint addresses. The host sees multiple interfaces and can bind different applications to each:
- High-throughput bulk transfers → UDF raw interface (via libusb)
- Standard networking (SSH, HTTP, NFS) → CDC-NCM interface (via kernel network stack)

#### 8.4.3 ConfigFS Setup (Linux)

```bash
# Create composite gadget with both UDF and NCM functions
cd /sys/kernel/config/usb_gadget/udf_composite
mkdir functions/ffs.udf0        # UDF raw via FunctionFS
mkdir functions/ncm.usb0        # CDC-NCM via kernel f_ncm
mkdir configs/c.1
ln -s functions/ffs.udf0 configs/c.1/
ln -s functions/ncm.usb0 configs/c.1/
echo "${UDC_NAME}" > UDC
```

#### 8.4.4 Routing Between Interfaces

Traffic arriving on the UDF raw interface is NOT visible to the NCM network interface and vice versa. They are completely independent data paths sharing only the physical USB cable. An application-layer bridge MAY be implemented if cross-interface communication is desired, but this is outside the scope of UDF v1.0.


---

## 9. Conformance

### 9.1 Mandatory Requirements

All UDF implementations MUST support the following:

| Requirement | Section | Description |
|-------------|---------|-------------|
| Frame parsing | §5.1 | Parse and validate UDF frame format (magic, lengths, alignment) |
| CRC-32 verification | §5.1.5 | Compute and verify IEEE 802.3 CRC-32 on all received frames |
| CRC-32 generation | §5.1.5 | Compute and append CRC-32 to all transmitted frames |
| SYN/ACK handshake | §5.2 | Initiate or respond to three-way handshake |
| CAP exchange | §5.2.4 | Send and receive CAP frames within 200ms of ESTABLISHED |
| Heartbeat transmission | §5.4 | Send HB frames every 100ms (or suppress when data sent) |
| Dead detection | §5.4.4 | Detect dead link within 600ms (5 missed intervals + tolerance) |
| Sequence numbering | §5.3.2 | Maintain per-direction sequence counters, detect gaps/duplicates |
| Graceful shutdown | §5.5 | Support FIN/FIN+ACK connection termination |
| Error counters | §5.7.3 | Maintain monotonic counters for all error conditions |
| Descriptor compliance | §4 | Present correct USB descriptors as specified |

### 9.2 Optional Requirements

The following features are OPTIONAL and only required for specific deployment scenarios:

| Requirement | Section | When Required |
|-------------|---------|---------------|
| Forwarding | §6.3 | Multi-hop topologies (ring with N>2, crisscross) |
| HELLO frames | §6.2 | Ring or crisscross topologies (neighbor discovery) |
| Routing table | §6.5 | Any topology with intermediate forwarding |
| Broadcast forwarding | §6.3.3 | Multi-hop topologies |
| CDC-NCM fallback | §8 | When IP networking is required |
| Composite gadget | §8.4 | When both UDF raw and NCM are needed simultaneously |

### 9.3 Test Suite Definition

A conformant implementation MUST pass all mandatory tests. Optional tests apply only when the corresponding optional feature is implemented.

#### Test 1: Single-Link Frame Exchange (Mandatory)

| Parameter | Value |
|-----------|-------|
| Objective | Verify basic frame encode/decode and delivery |
| Setup | Two nodes connected point-to-point |
| Procedure | Node A sends 1000 data frames (1024-byte payload each) to Node B |
| Pass criteria | Node B receives exactly 1000 frames with zero loss, zero CRC errors, zero sequence gaps |
| Timeout | 10 seconds maximum for all 1000 frames |
| Payload verification | Each frame payload contains a known pattern (frame index repeated); receiver verifies content |

#### Test 2: Heartbeat Detection (Mandatory)

| Parameter | Value |
|-----------|-------|
| Objective | Verify dead link detection timing |
| Setup | Two nodes connected, ESTABLISHED state |
| Procedure | Node A enters ESTABLISHED, then stops all transmission (simulated failure) |
| Pass criteria | Node B detects dead link and transitions to CLOSED within 600ms of last received frame |
| Measurement | Timestamp difference: `last_frame_received` to `state_transition(CLOSED)` |
| Tolerance | Detection MUST occur between 500ms and 600ms (5 intervals + scheduling jitter) |

#### Test 3: Forwarding (Optional — required for multi-hop)

| Parameter | Value |
|-----------|-------|
| Objective | Verify store-and-forward routing through intermediate node |
| Setup | Three nodes: A → B → C in a line (A connected to B, B connected to C) |
| Procedure | Node A sends 100 frames addressed to Node C (dst=C) |
| Pass criteria | Node C receives all 100 frames; Node B increments `forwarded` counter by 100; hop_count = 1 on all received frames at C; FWD flag set |
| Timeout | 5 seconds maximum |

#### Test 4: CRC Rejection (Mandatory)

| Parameter | Value |
|-----------|-------|
| Objective | Verify corrupted frames are silently dropped |
| Setup | Two nodes connected point-to-point |
| Procedure | Node A sends 100 valid frames interleaved with 100 frames that have 1 bit flipped in the payload (CRC will mismatch) |
| Pass criteria | Node B receives exactly 100 valid frames; `crc_errors` counter = 100; no corrupted frame delivered to application |
| Verification | Application-layer callback receives only frames with correct content |

#### Test 5: Sequence Accounting (Mandatory)

| Parameter | Value |
|-----------|-------|
| Objective | Verify 60-second sustained transfer with zero sequence gaps |
| Setup | Two nodes connected point-to-point |
| Procedure | Node A sends frames continuously for 60 seconds at maximum rate (back-to-back, 1024-byte payloads) |
| Pass criteria | Node B reports zero `seq_gaps`, zero `seq_duplicates`; `expected_seq` equals `frames_received` |
| Minimum frame count | >100,000 frames (at ~3 Gbps with 1024B payloads: ~220,000 frames expected) |
| Duration tolerance | Test runs for exactly 60 ± 0.5 seconds |

---

## 10. Performance Targets (Informative)

This section is informative, not normative. These targets represent expected performance on compliant hardware and serve as design guidelines. Failure to meet these targets does not constitute non-conformance.

### 10.1 Throughput and Overhead

| Metric | USB3 Gen 1 (5 Gbps) | USB3 Gen 2 (10 Gbps) |
|--------|---------------------|----------------------|
| Sustained unidirectional throughput | >3.0 Gbps | >6.5 Gbps |
| Sustained bidirectional throughput (dual cable) | >3.0 Gbps per direction | >6.5 Gbps per direction |
| Frame overhead (16KB payload) | <0.2% | <0.2% |
| Frame overhead (1KB payload) | <2.0% | <2.0% |
| Heartbeat bandwidth overhead | <0.01% | <0.01% |

### 10.2 Latency

| Metric | Target | Notes |
|--------|--------|-------|
| Forwarding latency per hop | <50 µs | Store-and-forward, no disk |
| End-to-end latency (point-to-point) | <100 µs | Single hop, userspace-to-userspace |
| Dead detection time | <600 ms | 5 × 100ms intervals + jitter |
| Handshake completion | <50 ms | SYN + SYN+ACK + ACK |

### 10.3 Overhead Calculations

**Frame overhead formula:**
```
overhead_pct = (20 / (payload_length + 20)) × 100

Examples:
  16368 B payload → 20 / 16388 = 0.12%
   1024 B payload → 20 / 1044  = 1.92%
    64 B payload  → 20 / 84    = 23.8%  (not recommended for bulk)
```

**Heartbeat overhead formula:**
```
hb_bandwidth = 20 bytes × 10 Hz = 200 bytes/sec = 1600 bits/sec
At 3 Gbps: 1600 / 3,000,000,000 = 0.0000005 = 0.00005%
```

### 10.4 Hardware Factors

| Factor | Impact | Mitigation |
|--------|--------|-----------|
| UDC DMA alignment | Misaligned buffers cause extra copies | Payload starts at offset 16 (aligned) |
| Max burst utilization | Under-filling bursts wastes bandwidth | 16KB payload fills exactly 1 burst |
| Host xHCI scheduling | Service interval affects latency | Use bulk with max burst for throughput |
| CPU cache pressure | Large frames may thrash L1/L2 | Zero-copy path avoids extra memcpy |
| USB cable quality | Poor cables cause link errors | USB3 CRC + hardware retry handles this |


---

## Appendix A: Benchmark Results Template

This appendix provides a standardized template for recording benchmark results. All fields marked "TBD" are to be filled with measured data from the reference hardware (sake: Pentium J5005, beirao: i5-1030NG7).

### A.1 Current 2.5G Ethernet Baseline

| Test | Direction | Throughput (Gbps) | Retransmits | Latency (µs) | Notes |
|------|-----------|-------------------|-------------|---------------|-------|
| TCP unidirectional | sake → beirao | TBD | TBD | TBD | iperf3, MTU 9000 |
| TCP unidirectional | beirao → sake | TBD | TBD | TBD | iperf3, MTU 9000 |
| TCP bidirectional | simultaneous | TBD | TBD | TBD | iperf3 --bidir |
| UDP unidirectional | sake → beirao | TBD | TBD | TBD | iperf3 -u, 2.4G target |
| ICMP RTT | — | — | — | TBD | ping -c 100 |

**Test conditions:**
- Adapter: Realtek RTL8156 2.5GbE USB dongle
- MTU: 9000 (jumbo frames)
- Link: 192.168.100.1/24 ↔ 192.168.100.2/24
- Duration: 30 seconds per test, 3 runs averaged

### A.2 Raw Bulk Transfer (g_zero / usbtest)

| Test | Direction | Throughput (Gbps) | CPU Usage | Notes |
|------|-----------|-------------------|-----------|-------|
| g_zero sink | host → gadget | TBD | TBD | Kernel module, no userspace |
| g_zero source | gadget → host | TBD | TBD | Kernel module, no userspace |
| usbtest bulk OUT | host → gadget | TBD | TBD | Varies by transfer size |
| usbtest bulk IN | gadget → host | TBD | TBD | Varies by transfer size |

**Test conditions:**
- Gadget: Linux `g_zero` kernel module with `buflen=16384`
- Host: `usbtest` kernel module or `testusb` utility
- Duration: 30 seconds per test
- Transfer sizes: 1024, 4096, 16384 bytes

### A.3 Framed UDF Transfer (Single Cable)

| Test | Payload Size | Throughput (Gbps) | Frames/sec | Overhead % | CPU Usage |
|------|-------------|-------------------|------------|-----------|-----------|
| Unidirectional | 1024 B | TBD | TBD | TBD | TBD |
| Unidirectional | 4096 B | TBD | TBD | TBD | TBD |
| Unidirectional | 16368 B | TBD | TBD | TBD | TBD |
| Sustained 60s | 16368 B | TBD | TBD | TBD | TBD |

**Test conditions:**
- UDF framing enabled (16B header + CRC)
- Single cable (USB link is bidirectional, but only one forwarding path exists per direction in ring topology)
- Sequence verification enabled
- Duration: 30 seconds per test (60s for sustained)

### A.4 Full-Duplex UDF Transfer (Dual Cable)

| Test | Payload Size | TX Throughput (Gbps) | RX Throughput (Gbps) | Aggregate | CPU Usage |
|------|-------------|---------------------|---------------------|-----------|-----------|
| Bidirectional | 1024 B | TBD | TBD | TBD | TBD |
| Bidirectional | 16368 B | TBD | TBD | TBD | TBD |
| Sustained 60s | 16368 B | TBD | TBD | TBD | TBD |

**Test conditions:**
- Two cables: each node has 1 gadget port + 1 host port
- Both directions transmitting simultaneously
- Sequence verification on both directions

### A.5 CDC-NCM over USB3 vs Current Adapter

| Test | CDC-NCM (Gbps) | UDF Raw (Gbps) | Current 2.5G Adapter (Gbps) | NCM Overhead vs Raw |
|------|----------------|-----------------|----------------------------|---------------------|
| TCP unidirectional | TBD | TBD | TBD | TBD% |
| TCP bidirectional | TBD | TBD | TBD | TBD% |
| Small packet (64B) | TBD | TBD | TBD | TBD% |
| iperf3 parallel ×8 | TBD | TBD | TBD | TBD% |

**Test conditions:**
- CDC-NCM: Linux `f_ncm` gadget function, standard kernel network stack
- UDF Raw: Application-layer throughput (frame payload bytes / time)
- Current adapter: Realtek RTL8156, same cable, same host ports


---

## Appendix B: Reference Implementation

### B.1 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           GADGET NODE (Device Role)                          │
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐    │
│  │ Application  │     │ udf_gadget.py│     │   Linux Kernel            │    │
│  │   Layer      │◄───►│  (daemon)    │◄───►│                          │    │
│  │              │     │              │     │  FunctionFS (f_fs)       │    │
│  └──────────────┘     └──────────────┘     │       │                  │    │
│                                             │       ▼                  │    │
│                                             │  DWC3 UDC Driver         │    │
│                                             │  (dwc3-pci / dwc3-plat)  │    │
│                                             └───────┬──────────────────┘    │
│                                                     │                       │
└─────────────────────────────────────────────────────┼───────────────────────┘
                                                      │
                                              USB 3.x Cable
                                              (5/10 Gbps)
                                                      │
┌─────────────────────────────────────────────────────┼───────────────────────┐
│                           HOST NODE (Host Role)     │                        │
│                                                     │                        │
│  ┌──────────────┐     ┌──────────────┐     ┌───────┴──────────────────┐    │
│  │ Application  │     │ udf_host.py  │     │   Linux Kernel            │    │
│  │   Layer      │◄───►│  (daemon)    │◄───►│                          │    │
│  │              │     │              │     │  xHCI Host Controller    │    │
│  └──────────────┘     │  (libusb     │     │  Driver (xhci-hcd)      │    │
│                        │   ctypes)    │     │                          │    │
│                        └──────────────┘     └──────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

Data flow (TX): Application → udf_gadget.py → FunctionFS ep1 (Bulk IN) → DWC3 → USB cable
                              → xHCI → libusb → udf_host.py → Application

Data flow (RX): Application ← udf_gadget.py ← FunctionFS ep2 (Bulk OUT) ← DWC3 ← USB cable
                              ← xHCI ← libusb ← udf_host.py ← Application
```

### B.2 Module Listing

| Module | Path | Lines | Purpose |
|--------|------|-------|---------|
| `frame.py` | `src/common/frame.py` | ~130 | Frame pack/unpack, CRC computation, Flag constants, Frame dataclass |
| `routing.py` | `src/common/routing.py` | ~140 | RoutingTable, NeighborMonitor, HELLO frame construction/parsing |
| `node.py` | `src/common/node.py` | ~200 | UDFNode orchestrator: dual-cable full-duplex, RX/TX queues, forwarding |
| `udf_gadget.py` | `src/gadget/udf_gadget.py` | ~200 | GadgetDaemon: FunctionFS descriptor setup, RX/TX/HB loops |
| `udf_host.py` | `src/host/udf_host.py` | ~200 | UDFHost: libusb ctypes bindings, bulk transfer loops |

### B.3 Module Interfaces

#### frame.py

```python
# Constants
MAGIC = 0x5546
HDR_SIZE = 16
CRC_SIZE = 4
MAX_PAYLOAD = 16368
FLAG_SYN = 0x01
FLAG_FIN = 0x02
FLAG_ACK = 0x04
FLAG_FWD = 0x08
FLAG_HB  = 0x10
FLAG_CAP = 0x20

# Functions
def pack(src: int, dst: int, seq: int, payload: bytes,
         flags: int = 0, hop: int = 0) -> bytes: ...

def pack_heartbeat(seq: int, src: int) -> bytes: ...

def unpack(data: bytes) -> Frame: ...
    # Raises ValueError on CRC mismatch, truncation, bad magic

# Dataclass
@dataclass
class Frame:
    flags: int
    hop: int
    seq: int
    src: int
    dst: int
    payload: bytes
```

#### routing.py

```python
class RoutingTable:
    def __init__(self, node_id: int, max_hops: int = 15): ...
    def add_neighbor(self, neighbor_id: int, port: str): ...
    def remove_neighbor(self, neighbor_id: int): ...
    def get_next_hop(self, dst: int) -> Optional[str]: ...
    def update_from_hello(self, hello_path: list[int]): ...
    def recompute(self): ...

class NeighborMonitor:
    def __init__(self, timeout_ms: int = 500): ...
    def heartbeat_received(self, neighbor_id: int): ...
    def check_dead(self) -> list[int]: ...

def make_hello(node_id: int, known_nodes: list[int], seq: int) -> bytes: ...
def parse_hello(f: Frame) -> tuple[int, list[int]]: ...
```

#### node.py

```python
class UDFNode:
    def __init__(self, node_id: int, gadget_ffs_dir: str = '/tmp/udf_ffs',
                 host_vid: int = 0x1d6b, host_pid: int = 0x0105): ...
    def start(self): ...
    def stop(self): ...
    def send(self, dst: int, payload: bytes): ...
    def recv(self, timeout: float = 1.0) -> Optional[Frame]: ...
    def forward(self, f: Frame): ...
    def get_stats(self) -> dict: ...
```

### B.4 Dependencies

| Dependency | Version | Purpose | Install |
|------------|---------|---------|---------|
| Python | 3.10+ | Runtime (stdlib only, no pip packages) | System package |
| Linux kernel | 6.8+ | DWC3, USB ConfigFS, FunctionFS support | System kernel |
| libusb | 1.0.x | Host-side USB device access (via ctypes) | `apt install libusb-1.0-0` |
| DWC3 kernel module | — | UDC hardware driver | `CONFIG_USB_DWC3=m` in kernel config |
| ConfigFS | — | USB gadget composition | `CONFIG_USB_CONFIGFS=y` |
| FunctionFS | — | Userspace gadget function | `CONFIG_USB_FUNCTIONFS=m` |

### B.5 Kernel Configuration

Required kernel config options:

```
CONFIG_USB_GADGET=y
CONFIG_USB_CONFIGFS=y
CONFIG_USB_CONFIGFS_F_FS=y
CONFIG_USB_DWC3=m
CONFIG_USB_DWC3_PCI=m        # For Intel SoCs (Gemini Lake, Ice Lake)
CONFIG_USB_DWC3_GADGET=y     # Or CONFIG_USB_DWC3_DUAL_ROLE=y
CONFIG_USB_FUNCTIONFS=m
CONFIG_USB_F_FS=m
```

### B.6 Quick Start

```bash
# On gadget node (e.g., sake):
sudo modprobe dwc3-pci
sudo modprobe usb_f_fs
sudo mkdir -p /tmp/udf_ffs
sudo mount -t functionfs udf /tmp/udf_ffs
sudo python3 src/gadget/udf_gadget.py --node-id 1 --ffs-dir /tmp/udf_ffs

# On host node (e.g., beirao):
sudo python3 src/host/udf_host.py --node-id 2
```


---

## Appendix C: Bill of Materials

### C.1 Ring Topology (4 Nodes)

| Item | Qty | Unit Cost | Total | Notes |
|------|-----|-----------|-------|-------|
| USB 3.x cable (Type-C to Type-C, 1m) | 4 | ~€10 | ~€40 | Gen 1 (5 Gbps) sufficient; Gen 2 for higher throughput |
| Machine with 1 UDC (gadget-capable) port | 4 | — | — | Existing hardware (must have DWC3 xDCI or equivalent) |
| Machine with 1 USB3 host port | 4 | — | — | Same machines (standard host port) |

**Total additional cost: ~€40** (cables only, assuming machines already exist)

**Hardware requirements per node:**
- 1× USB3 port capable of device mode (UDC/xDCI)
- 1× USB3 host port (standard)
- Linux kernel 6.8+ with DWC3 support

### C.2 Crisscross Topology (4 Nodes)

| Item | Qty | Unit Cost | Total | Notes |
|------|-----|-----------|-------|-------|
| USB 3.x cable (Type-C to Type-C, 1m) | 6 | ~€10 | ~€60 | 2 cables per node outgoing |
| Machine with 1 UDC port | 4 | — | — | Same UDC requirement as ring |
| Machine with 2 USB3 host ports | 4 | — | — | Many machines have 2+ USB3 ports |

**Total additional cost: ~€60** (cables only)

**Hardware requirements per node:**
- 1× USB3 port capable of device mode (UDC/xDCI)
- 2× USB3 host ports (standard)
- Linux kernel 6.8+ with DWC3 support

### C.3 Star/Hub Topology (4 Nodes)

| Item | Qty | Unit Cost | Total | Notes |
|------|-----|-----------|-------|-------|
| USB 3.x cable (Type-C, 1m) | 4 | ~€10 | ~€40 | Hub to each endpoint |
| Cypress FX3 dev board (CYUSB3KIT-003) | 1 | ~€200 | ~€200 | Central hub; or 4× individual FX3 boards |
| Custom hub firmware | 1 | — | — | Switching logic (frame routing) |
| Hub enclosure + power | 1 | ~€50 | ~€50 | USB3 power for FX3 |

**Total additional cost: ~€300–450** (hub hardware is the major expense)

**Alternative hub hardware:**
- 4× Cypress FX3 SuperSpeed Explorer boards (~€50 each = €200)
- Custom PCB with multi-port USB3 PHY (higher NRE cost, lower per-unit)
- FPGA with USB3 IP (e.g., Xilinx Zynq + USB3 PHY) (~€300–500)

**Hardware requirements per endpoint node:**
- 1× USB3 host port (standard) — NO UDC needed at endpoints
- Linux with libusb (or any OS with USB bulk support)

### C.4 Recommended Development Boards

| Board | SoC | USB3 DRD Ports | Price | Notes |
|-------|-----|----------------|-------|-------|
| Radxa Rock 5B | RK3588 | 2× USB3 DRD (Type-C) | ~€80 | Best value: 2 device-mode ports enables ring without additional hardware |
| Radxa Rock 5A | RK3588S | 1× USB3 DRD + 1× USB3 host | ~€60 | Single DRD limits to ring endpoint |
| Orange Pi 5 Plus | RK3588 | 2× USB3 DRD | ~€90 | Similar to Rock 5B |
| Intel NUC (Gemini Lake) | J5005 | 1× DWC3 xDCI (internal) | ~€150 used | Proven: reference hardware (sake) |
| Intel NUC (Ice Lake) | i5-1030NG7 | 1× DWC3 xDCI | ~€250 used | Proven: reference hardware (beirao) |
| Cypress FX3 SuperSpeed Kit | FX3 | 1× USB3 device | ~€50 | Hub/switch node only (no host role) |

**Recommendation for new deployments:**
- 4× Radxa Rock 5B (~€320 total) provides a complete 4-node crisscross fabric with 2× DRD ports per node.
- Combined with 6× USB3 cables (~€60), total fabric cost is ~€380 for 4 nodes at up to 3.5 Gbps per link.

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2026-06-22 | Wire format specification (frame format, flags, CRC, state machine) |
| 1.0 | 2026-06-22 | Initial consolidated specification. Incorporates: device framework, protocol (handshake, heartbeat, flow control, error handling), routing (addressing, forwarding, HELLO, dead detection), topology definitions (ring, crisscross, hub), CDC-NCM compatibility mode, conformance test suite, performance targets, reference implementation documentation, bill of materials. |

---

*End of USB Direct Fabric (UDF) Class Specification, Revision 1.0.*

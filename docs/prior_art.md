# USB Direct Fabric — Prior Art & Positioning

## Summary

UDF occupies an empty niche: **USB3 DRD, userspace, multi-hop, framed protocol with CDC-NCM fallback**. No existing project covers this exact combination.

| Project | Layer | Hardware | Multi-hop | Framing | IP compat | Speed | Status |
|---------|-------|----------|-----------|---------|-----------|-------|--------|
| **UDF** | L2 userspace | USB3 DRD (DWC3, RK3588) | Ring, crisscross, hub | 16B header + CRC | CDC-NCM mode | 3.5–7.2 Gbps | This project |
| USB4STREAM | Kernel char device | USB4/Thunderbolt only | Point-to-point only | None (raw stream) | No | 40–80 Gbps | Merged Linux 7.2 (2026-06-22) |
| Thunderbolt Net | Kernel NIC driver | Thunderbolt/USB4 only | No | Ethernet framing | Yes (native) | ~13 Gbps practical | Mainline since 4.15 |
| USB/IP (usbip) | USB-over-TCP | Any network | Via IP routing | TCP encapsulation | Yes (is IP) | Limited by TCP/latency | Mainline since 3.17 |
| PCIe NTB | Kernel + DMA | PCIe switch hardware | No (point-to-point) | Memory-mapped | ntb_netdev | 50+ Gbps | Production HPC |
| CDC-NCM gadget | Kernel NIC driver | USB2/3 DRD | No | NTB framing + IP | Yes (native) | ~2.5 Gbps (USB3) | Widely deployed |
| Legacy bridge cables | Custom ASIC | Proprietary hardware | No | Proprietary | No | USB2 speeds | Obsolete |

---

## Detailed Comparison

### USB4STREAM (Linux 7.2, merged 2026-06-22)

The most directly relevant prior art. Intel's USB4STREAM creates `/dev/tbstreamX` character devices for raw byte streaming between two USB4/Thunderbolt-connected hosts. No IP stack, no network interface — just `open()/read()/write()`.

**Architectural overlap with UDF:**
- Both bypass the network stack entirely
- Both expose a direct pipe to userspace
- Both target the "USB cable = fabric" model

**Where UDF differs:**
- UDF works on USB3 DRD (vastly larger hardware base: Intel Gemini Lake, Ice Lake, RK3588)
- UDF has explicit multi-hop routing (ring, crisscross, hub topologies)
- UDF has a defined frame format (CRC, sequence numbers, heartbeat, addressing)
- UDF provides CDC-NCM fallback for IP when needed
- UDF runs entirely in userspace (no kernel patches)
- USB4STREAM is point-to-point only, no routing

**Complementary, not competing.** USB4STREAM is the high-bandwidth kernel-native path for USB4 hardware. UDF is the userspace multi-node fabric for the cheaper USB3 tier.

### Thunderbolt Networking (`thunderbolt_net`)

Creates a virtual Ethernet interface over Thunderbolt DMA tunnels. Standard IP tools work transparently.

**Why UDF exists despite this:**
- Requires Thunderbolt/USB4 hardware (expensive, limited availability)
- Forces all traffic through the kernel IP stack (CPU overhead kills throughput)
- ~13 Gbps practical vs 40 Gbps theoretical (Ethernet framing costs ~33%)
- No multi-host topology support

### USB/IP (usbip)

Wraps USB Request Blocks in TCP packets, sends over standard IP network. Remote USB devices appear local via `vhci-hcd`.

**The fundamental problem UDF avoids:**
- USB→TCP→network→TCP→USB adds two full protocol stacks
- Serialization of USB transactions over TCP creates latency that makes real-time device access impossible
- Works for printers and cameras, fails for bulk throughput

**UDF inverts the model:** USB bulk IS the transport. No TCP. No IP. No serialization.

### PCIe NTB + `ntb_netdev`

The HPC gold standard. Two hosts share PCIe fabric via Non-Transparent Bridge hardware. Direct memory-to-memory DMA. Zero-copy. Sub-microsecond latency.

**UDF is NTB's consumer-hardware cousin:**
- Same architectural pattern (mediating controller presents as device to each host)
- Different physical layer (USB3 vs PCIe)
- Different cost point (€10 cable vs €500+ switch hardware)
- Different performance tier (3.5 Gbps vs 50+ Gbps)
- Same zero-IP-overhead philosophy

### CDC-NCM/ECM Gadget (Raspberry Pi, embedded Linux)

The well-trodden path: USB gadget presents as a standard network adapter. IP works, SSH works.

**UDF's relationship:**
- UDF's CDC-NCM mode (§8) IS this — but on USB3 hardware (10–20× faster than Pi Zero)
- The raw UDF bulk path sits alongside NCM for throughput-sensitive workloads
- UDF scales to multi-host; Pi Zero gadget is single-host only

---

## Anticipated Criticisms & Defenses

| Criticism | Defense |
|-----------|---------|
| "You reinvented Ethernet at Layer 2" | Ethernet forces traffic through the kernel IP stack. UDF allows direct userspace-to-bulk-endpoint writes, eliminating TCP/IP overhead entirely. |
| "Ring topologies are dead (Token Ring)" | For 2–4 node home fabrics, ring saves €300 in hub hardware. Crisscross topology provides fault tolerance for 4–6 nodes. Star/hub available for 7+. |
| "Userspace Python can't do 5 Gbps" | Python is the protocol validator (~100–400 Mbps). Production data plane targets C/Rust with io_uring/mmap. This is documented in the spec (§6.3.4). |
| "USB4STREAM just merged and does this better" | USB4STREAM requires USB4/Thunderbolt hardware and is point-to-point only. UDF works on USB3 DRD (much larger hardware base) and supports multi-hop topologies. They're complementary. |
| "Why not just buy a 10GbE switch?" | A 10GbE switch costs €200–400. UDF requires €40–80 in cables + hardware you already own. For a 2–4 node homelab the economics are compelling. |

---

## The Timing Argument

USB4STREAM's merge into Linux 7.2 on the same day UDF development started validates the architectural direction: the kernel community accepts "bypass the network stack, expose a direct USB pipe" as a legitimate design pattern. UDF extends this pattern to:
1. Cheaper hardware (USB3 vs USB4)
2. Multi-hop topologies (ring, crisscross vs point-to-point)
3. Userspace implementation (no kernel patches required)
4. Explicit protocol with framing, routing, and security

The risk: USB4 adoption over 3–5 years may reduce the relevance of USB3 DRD hardware. The counter: USB3 DRD (Intel Gemini Lake, Ice Lake, Alder Lake, RK3588) will remain the dominant tier in embedded, home-lab, and edge hardware for years. And USB4STREAM has no topology support whatsoever.

---

## References

1. USB4STREAM — merged Linux 7.2, June 22 2026. Mika Westerberg (Intel), Alan Borzeszkowski.
2. Thunderbolt Networking — Linux kernel `thunderbolt_net`, mainline since 4.15 (2018).
3. USB/IP — Takahiro Hirofuchi, mainline since 3.17 (2014). https://www.kernel.org/doc/html/latest/usb/usbip_protocol.html
4. PCIe NTB — Linux kernel `ntb`, `ntb_netdev`, mainline since ~3.10 (2013).
5. CDC-NCM — USB-IF specification. Linux `f_ncm` gadget function.
6. "USB 3.x Real-Time Networking" — Richard West, Boston University, ACM TECS 2023. https://www.cs.bu.edu/~richwest/papers/usb-networking-acm-tecs-2023.pdf
7. Legacy USB bridge cables — Prolific PL25A1, Cypress EZ-Host (discontinued).

# USB Direct Fabric — Baseline Benchmark Report

## Test Environment

### Hardware

| Node | SoC | UDC | USB Adapter | Link |
|------|-----|-----|-------------|------|
| sake | Pentium J5005 (Gemini Lake) | DWC3 xDCI | 2.5G Realtek USB Ethernet | enx00e04c680052 |
| beirao | i5-1030NG7 (Ice Lake) | DWC3 xDCI | 2.5G Realtek USB Ethernet | enx00e04c68007d |

### Software

- Kernel: (fill in)
- iperf3 version: (fill in)
- MTU: 9000

### Link Configuration

- Point-to-point: 192.168.100.1/24 ↔ 192.168.100.2/24
- Cable: USB 3.x (fill in type/length)
- Adapter: Realtek RTL8156 2.5GbE USB dongle

---

## Test 1: Unidirectional TCP (sake → beirao)

### Expected

~2.35 Gbps (2.5G line rate minus TCP/IP overhead, jumbo frames)

### Measured

| Run | Throughput (Gbps) | Retransmits |
|-----|-------------------|-------------|
| 1 | — | — |
| 2 | — | — |
| 3 | — | — |

### Analysis

(fill in)

---

## Test 2: Unidirectional TCP (beirao → sake)

### Expected

~2.35 Gbps (symmetric to Test 1)

### Measured

| Run | Throughput (Gbps) | Retransmits |
|-----|-------------------|-------------|
| 1 | — | — |
| 2 | — | — |
| 3 | — | — |

### Analysis

(fill in)

---

## Test 3: Bidirectional Simultaneous

### Expected

Possibly degraded vs unidirectional — USB adapter may be half-duplex internally, or share a single USB bulk pipe for both directions. Expected ~1.5–2.0 Gbps per direction if half-duplex, ~2.35 Gbps per direction if true full-duplex.

### Measured

| Direction | Throughput (Gbps) |
|-----------|-------------------|
| sake → beirao | — |
| beirao → sake | — |

### Analysis

(fill in)

---

## Test 4: UDP Saturation (sake → beirao)

### Expected

~2.45 Gbps (no TCP overhead, 3G offered load exceeds link capacity, shows true ceiling)

### Measured

| Metric | Value |
|--------|-------|
| Bandwidth | — |
| Jitter | — |
| Lost datagrams | — |
| Loss % | — |

### Analysis

(fill in)

---

## Test 5: Raw Throughput (dd + nc)

### Expected

- /dev/zero: near line rate (~2.4 Gbps), minimal CPU
- /dev/urandom: CPU-bound, likely 500–800 Mbps (urandom generation is slow)

### Measured

| Source | Size | Time | Throughput |
|--------|------|------|------------|
| /dev/zero | 512 MB | — | — |
| /dev/urandom | 512 MB | — | — |

### Analysis

(fill in)

---

## Test 6: CPU Load During iperf3

### Expected

Low CPU on both nodes (iperf3 TCP with jumbo frames should not saturate modern CPUs). <10% system time expected.

### Measured

| Node | %usr | %sys | %iowait | %idle |
|------|------|------|---------|-------|
| sake | — | — | — | — |
| beirao | — | — | — | — |

### Analysis

(fill in)

---

## Summary

| Test | Direction | Expected (Gbps) | Measured (Gbps) | Notes |
|------|-----------|-----------------|-----------------|-------|
| 1 TCP | sake→beirao | ~2.35 | — | |
| 2 TCP | beirao→sake | ~2.35 | — | |
| 3 Bidir | sake→beirao | ~1.5–2.35 | — | |
| 3 Bidir | beirao→sake | ~1.5–2.35 | — | |
| 4 UDP | sake→beirao | ~2.45 | — | |
| 5 Raw (zero) | sake→beirao | ~2.4 | — | |
| 5 Raw (urandom) | sake→beirao | ~0.5–0.8 | — | CPU-bound |
| 6 CPU | — | <10% sys | — | |

## Conclusions

(fill in after running benchmark)

- Is the 2.5G adapter achieving line rate?
- Is the link full-duplex or half-duplex?
- What is the CPU overhead?
- Does this justify pursuing raw USB bulk transport (Phase 3+)?

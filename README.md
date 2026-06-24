# USB Direct Fabric (UDF)

A native USB bulk transport fabric that runs at raw link speed, bypassing fixed ethernet rate ceilings. Scales from 2 to N machines via ring, crisscross, or hub topologies using only stock Linux kernel USB gadget infrastructure.

## Goal

Replace USB-to-ethernet adapters (locked to 1/2.5/5/10 GbE steps) with a direct USB bulk transport that fills the pipe elastically — achieving ~3.5 Gbps on USB3 Gen 1 or ~7.2 Gbps on Gen 2, with no custom host drivers required.

## Current Hardware

| Machine | SoC | UDC | Direct Link IP | Interface |
|---------|-----|-----|----------------|-----------|
| sake | Pentium J5005 (Gemini Lake) | DWC3 xDCI | 192.168.100.1/24 | enx00e04c680052 |
| beirao | i5-1030NG7 (Ice Lake) | DWC3 xDCI | 192.168.100.2/24 | enx00e04c68007d |

Current interconnect: 2.5G Realtek USB ethernet adapters, MTU 9000, point-to-point.

## Project Phases

| Phase | Objective | Status |
|-------|-----------|--------|
| 1 | Baseline benchmark of current 2.5G link | Scripted |
| 2 | xDCI hardware validation on both machines | Scripted |
| 3 | Single-cable raw bulk gadget link | Implemented |
| 4 | Wire format specification (v0.1) | Documented |
| 5 | Framed bulk transport with sequence verification | Implemented |
| 6 | Dual-cable full-duplex (ring of 2) | Implemented |
| 7 | Forwarding daemon & ring topology support | Implemented |
| 8 | Topology specification (ring, crisscross, hub) | Documented |
| 9 | CDC-NCM IP compatibility layer | Implemented |
| 10 | Formal USB-IF spec (v1.0) | Documented |

## Directory Layout

```
benchmark/          Baseline performance scripts and results
validation/         Hardware discovery and xDCI validation
src/common/         Shared protocol: framing, routing, node orchestration
src/gadget/         Gadget-side (device controller) daemons and setup
src/host/           Host-side daemons and benchmarks
spec/               Protocol and topology specifications
docs/               Reports, validation results, analysis
```

## Topologies

- **Ring (degree 2)**: 1 gadget + 1 host cable per node. Zero extra hardware. One failure = ring cut.
- **Crisscross (degree 3)**: 1 gadget + 2 host cables per node. Survives 1 cable failure. Diameter halved.
- **Star/Hub (FX3)**: Central switch with N× Cypress FX3 controllers. Hub is SPOF but zero forwarding at endpoints.

## Running the Benchmark

```bash
# Baseline current 2.5G link (requires SSH to sake + beirao)
./benchmark/benchmark_direct_link.sh

# Validate xDCI hardware
sudo ./validation/validate_xdci.sh
```

## Requirements

- Linux kernel 6.8+ with DWC3, USB configfs, FunctionFS support
- Python 3.10+ (stdlib only — no pip dependencies)
- iperf3, jq, sysstat (mpstat), netcat on both nodes
- USB 3.x cables (Type-C or Type-A depending on UDC port)

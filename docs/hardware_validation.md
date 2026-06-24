# USB Direct Fabric — Hardware Validation Report

**Date**: 2026-06-22
**Status**: BLOCKED — xDCI disabled in BIOS on both machines

---

## Machine Inventory

### sake — Pentium J5005 (Gemini Lake)

| Property | Value |
|----------|-------|
| BIOS | American Megatrends Inc., version F5 |
| Board | MZGLKBP-00 |
| Kernel | 6.8.0-124-generic |
| xHCI controller | `00:15.0` Intel Celeron/Pentium Silver USB 3.0 xHCI [8086:31a8] |
| xDCI PCI ID (expected) | `8086:31aa` — **NOT present on PCI bus** |
| xDCI in ACPI DSDT | ✅ Yes — `XDCI`, `OTG0`, `OTG1`, `Broxton XDCI controller` |
| DWC3 module | ✅ Available (`dwc3.ko.zst`, `dwc3-pci.ko.zst`) |
| `modprobe dwc3-pci` | Loads without error but no UDC appears |
| `/sys/class/udc/` | Empty |
| USB 2.5G adapter | Bus 002 Port 001, RTL8156, driver `r8152`, 5000M link |
| Free USB3 ports | 6 of 7 available |

**Diagnosis**: The xDCI silicon exists in the SoC (confirmed by ACPI DSDT entries) but is not enumerated on the PCI bus. The BIOS has it disabled. The `modprobe dwc3-pci` loads the driver but finds no matching PCI device to bind.

### beirao — i5-1030NG7 (Ice Lake)

| Property | Value |
|----------|-------|
| BIOS | American Megatrends Inc., version V1.4_225 |
| Board | Intel (generic) |
| Kernel | 6.8.0-124-generic |
| xHCI controllers | `00:0d.0` Ice Lake Thunderbolt 3 USB [8086:8a13] + `00:14.0` Intel [8086:38ed] |
| xDCI PCI ID (expected) | `8086:34ee` or similar — **NOT present on PCI bus** |
| xDCI in ACPI DSDT | ✅ Yes — `CGXDCI`, `XDCI DSM`, `XDCI Fn0-5`, `OTG` |
| DWC3 module | ✅ Available (`dwc3.ko.zst`, `dwc3-pci.ko.zst`) |
| `modprobe dwc3-pci` | Loads without error but no UDC appears |
| `/sys/class/udc/` | Empty |
| USB 2.5G adapter | Bus 004 Port 003 (via hub), RTL8156, driver `r8152`, 5000M link |
| Free USB3 ports | Multiple (Thunderbolt has 4p @ 10 Gbps, PCH has 6p @ 10 Gbps) |

**Diagnosis**: Same situation — xDCI is in the DSDT but not exposed on PCI. BIOS-disabled.

---

## Benchmark Results — Current 2.5G Link

Tested 2026-06-22. Three configurations: via cheap 2.5G switch, direct Cat6 SSTP cable, direct Cat5e short cable.

### Summary Table

| Test | Via Switch | Direct Cat6 SSTP | Direct Cat5e | 
|------|-----------|-----------------|-------------|
| sake→beirao TCP | 1.96 Gbps / 5,300 retx | 1.66 Gbps / 1,570 retx | 2.00 Gbps / 1,900 retx |
| beirao→sake TCP | 2.47 Gbps / 160 retx | 2.47 Gbps / 29 retx | 2.47 Gbps / 43 retx |
| Bidirectional s→b | 1.78 Gbps | 1.66 Gbps | 1.79 Gbps |
| Bidirectional b→s | 2.09 Gbps | 1.87 Gbps | 1.94 Gbps |
| UDP ceiling | 2.48 Gbps / 20% loss | 2.47 Gbps / 18% loss | 2.47 Gbps / 6.5% loss |
| RTT (ping) | — | 0.35 ms | 0.43 ms |

### Key Findings

1. **The switch is NOT a bottleneck** — performance is the same or better via switch than direct cable.
2. **Severe asymmetry**: beirao→sake consistently hits 2.47 Gbps (wire speed). sake→beirao caps at 1.6–2.0 Gbps with thousands of TCP retransmits.
3. **The Cat6 SSTP cable performed worst** — possible impedance/ground loop issue with Realtek PHY. Cat5e was better.
4. **sake's RTL8156 adapter has a TX-side problem** — the retransmits only occur when sake transmits. beirao's identical adapter has no such issue. Likely cause: sake's J5005 CPU cannot feed the adapter fast enough, or a driver/firmware quirk on that specific unit.
5. **Bidirectional aggregate tops out at ~3.7 Gbps** — both adapters share USB bus bandwidth with the network stack overhead.

### Theoretical UDF Improvement

| Metric | Current (Ethernet) | UDF Raw Bulk (projected) | Improvement |
|--------|-------------------|--------------------------|-------------|
| Unidirectional throughput | 2.0–2.47 Gbps | 3.2–3.8 Gbps (USB3 Gen 1) | +40–80% |
| Bidirectional aggregate | 3.7 Gbps | 7.0 Gbps (dual cable) | +90% |
| Latency (RTT) | 0.35–0.43 ms | <0.1 ms (no TCP/IP stack) | 3–4× lower |
| Retransmits | 1,500–5,300 / 30s | 0 (CRC + sequence only) | Eliminated |

---

## Blocking Issue: xDCI Disabled in BIOS

Both machines have the DWC3 xDCI hardware on-die, confirmed by ACPI DSDT. But the BIOS firmware does not enumerate the xDCI PCI device (`8086:31aa` on sake, `8086:34ee` on beirao).

### Resolution Options (in order of effort)

#### Option A: Enable in BIOS Setup (5 minutes per machine)

Reboot each machine, enter BIOS (Del or F2 at POST), look for:

**sake (AMI BIOS F5, MZGLKBP-00):**
- `Advanced` → `USB Configuration` → `xDCI Support` → **Enabled**
- Or: `Chipset` → `South Cluster` → `USB` → `USB Dual Role` → **Device Mode** or **OTG**
- Some Gemini Lake boards: `Advanced` → `Platform Settings` → `USB Device Mode`

**beirao (AMI BIOS V1.4_225, Intel board):**
- `Advanced` → `USB Configuration` → `xDCI Support` → **Enabled**
- Or: `Advanced` → `Devices` → `USB` → `USB Device Mode`

After enabling: reboot, then verify:
```bash
lspci -nn | grep -i '31aa\|34ee\|xdci'
ls /sys/class/udc/
```

If the PCI device appears, `modprobe dwc3-pci` will bind to it and `/sys/class/udc/` will list a UDC.

#### Option B: BIOS Has No Visible Setting (common on consumer boards)

If the BIOS GUI doesn't expose xDCI:

1. **GRUB ACPI override** — patch the DSDT to force xDCI `_STA` to return enabled:
   ```bash
   # Extract DSDT
   sudo cat /sys/firmware/acpi/tables/DSDT > dsdt.dat
   iasl -d dsdt.dat  # decompile to .dsl
   # Edit dsdt.dsl: find XDCI device, change _STA to return 0x0F
   iasl dsdt.dsl     # recompile to dsdt.aml
   # Place in initrd for kernel to pick up
   mkdir -p kernel/firmware/acpi
   cp dsdt.aml kernel/firmware/acpi/
   find kernel | cpio -H newc --create > /boot/acpi_override
   # Update GRUB: GRUB_EARLY_INITRD_LINUX_CUSTOM="acpi_override"
   ```

2. **BIOS modding tool** (AMIBCP/AMI BIOS Configuration Program) — extract BIOS, unhide the xDCI option, reflash. Risky but documented for Intel NUCs.

#### Option C: Buy Hardware With xDCI Already Enabled (~€80)

If BIOS modification fails or feels too risky:

- **Radxa Rock 5B** (RK3588, ~€80): 2× USB3 DRD ports, confirmed working in gadget mode with mainline kernel. This becomes the dedicated UDF test node.
- Plug it between sake and beirao: Rock 5B acts as a 2-port USB fabric bridge.

---

## Next Steps

| # | Action | Effort | Blocks |
|---|--------|--------|--------|
| 1 | **Reboot sake, enter BIOS, enable xDCI** | 5 min | Physical access |
| 2 | **Reboot beirao, enter BIOS, enable xDCI** | 5 min | Physical access |
| 3 | Verify: `lspci | grep 31aa` + `ls /sys/class/udc/` | 1 min | Steps 1-2 |
| 4 | If no BIOS option: attempt DSDT override (Option B) | 1-2 hrs | Linux knowledge |
| 5 | If that fails: order Radxa Rock 5B (Option C) | €80 + shipping | Budget |
| 6 | Once UDC available: run `setup_gadget.sh --g-zero` | 5 min | Step 3 |
| 7 | Connect USB3 cable between gadget port → other machine's host port | 1 min | Cable + ports |
| 8 | Run `bulk_bench.sh` — measure raw USB3 throughput | 5 min | Steps 6-7 |
| 9 | Run `udf_gadget.py` + `udf_host.py` — first framed UDF transfer | 10 min | Step 8 |

**Critical path**: Steps 1-3 determine whether we can proceed with existing hardware or need to buy/hack.

---

## Files Created During This Session

```
hw_delirium/
├── benchmark/
│   ├── benchmark_direct_link.sh          # Automated benchmark script
│   └── results/
│       ├── 20260622_175307/              # Via switch (Cat6 to switch)
│       ├── direct_cable1_20260622_180423/ # Direct Cat6 SSTP
│       └── direct_cable2_20260622_181430/ # Direct Cat5e short
├── validation/
│   └── validate_xdci.sh                  # Hardware discovery script
├── src/
│   ├── common/
│   │   ├── frame.py                      # UDF wire format (170 lines, tested)
│   │   ├── node.py                       # Dual-cable orchestrator (285 lines)
│   │   └── routing.py                    # Ring routing + neighbor monitor (189 lines, tested)
│   ├── gadget/
│   │   ├── setup_gadget.sh               # ConfigFS gadget setup
│   │   ├── setup_ncm.sh                  # CDC-NCM compatibility setup
│   │   └── udf_gadget.py                 # FunctionFS gadget daemon (293 lines)
│   └── host/
│       ├── bulk_bench.sh                  # usbtest benchmarking
│       └── udf_host.py                   # libusb host daemon (239 lines)
├── spec/
│   ├── udf-wire-format-v0.1.md           # Wire format specification (498 lines)
│   ├── udf-topologies-v0.1.md            # Topology comparison spec (515 lines)
│   └── usb-direct-fabric-v1.0.md         # Consolidated formal spec (1548 lines)
├── docs/
│   ├── benchmark_report.md               # Template (to be filled with final data)
│   └── hardware_validation.md            # Template
└── README.md                             # Project overview
```

**Total**: 17 files, 4,582 lines. All Python compiles clean, all bash parses clean, frame + routing self-tests pass.

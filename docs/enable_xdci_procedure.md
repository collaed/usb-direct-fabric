# Enabling xDCI on sake — Procedure

## Current Status (2026-06-22)

- BIOS: AMI F5, board MZGLKBP-00 (Gemini Lake J5005)
- xDCI PCI device (8086:31aa) is NOT on PCI bus — disabled in firmware
- ACPI DSDT confirms silicon exists: "Broxton XDCI controller", OTG0, OTG1
- Setup UEFI variable: 1529 bytes, GUID `EC87D643-EBA4-4BB5-A1E5-3F3E36B20DA9`
- String "XDCI controller" found in HII string database
- IFR forms are in Tiano-compressed firmware volumes (not easily parseable without UEFITool GUI)

## Method 1: Check BIOS GUI (Simplest)

Reboot sake, press **Del** or **F2** at POST to enter BIOS Setup.

Look under:
- `Advanced` → `USB Configuration` → look for "xDCI" or "USB Device Mode"
- `Chipset` → `South Bridge` → `USB` → "xDCI Support" or "USB OTG"
- `IntelRCSetup` → `PCH-IO` → `USB` → "xDCI Support"

If found: set to **Enabled**, save, reboot.

## Method 2: EFI Shell + setup_var (If BIOS GUI has no option)

sake has "UEFI: Built-in EFI Shell" in its boot menu.

### Step 1: Get setup_var tool

Download `grub-mod-setup_var` from:
https://github.com/datasone/grub-mod-setup_var/releases

Or use the `modded GRUB` shell which has the `setup_var_3` command built in.

### Step 2: Find xDCI offset

Since we couldn't parse the Tiano-compressed IFR from Linux, use UEFITool GUI
on a desktop machine:

1. Copy `/tmp/sake_bios.bin` to a machine with UEFITool installed
2. Open in UEFITool (NE version from https://github.com/LongSoft/UEFITool/releases)
3. Ctrl+F → String → "xDCI" → Unicode
4. Double-click the result to navigate to the Setup form
5. In that section, find the IFR ONE_OF or CHECKBOX opcode
6. Note the VarStore name and VarOffset value — this is what we need

### Step 3: Set the variable

From GRUB shell (boot from USB with modded GRUB):
```
setup_var_3 0xXXX 0x01
# where 0xXXX is the offset found in Step 2
```

Or from EFI Shell:
```
# List all variables to find Setup
dmpstore Setup
# Use a UEFI variable editing tool
```

### Step 4: Verify

After reboot into Linux:
```bash
lspci -nn | grep 31aa          # Should show xDCI device
sudo modprobe dwc3-pci          # Load driver
ls /sys/class/udc/              # Should list a UDC
```

## Method 3: Known Gemini Lake xDCI offsets (RISKY — try only if Method 2 confirms)

Based on other Gemini Lake boards with AMI BIOS, common xDCI offsets:

| Board | Variable | Offset | Value (enable) | Source |
|-------|----------|--------|----------------|--------|
| Various GLK | Setup | 0x15 | 0x01 | Unconfirmed for MZGLKBP-00 |
| Various GLK | Setup | 0x2B | 0x01 | Unconfirmed |
| Surface Go (Pentium) | PchSetup | 0x40 | 0x01 | Confirmed (shinyquagsire23) |

**DO NOT blindly try these offsets** without confirming via IFR extraction.
Wrong offset = bricked BIOS (recoverable only via SPI programmer).

## Method 4: Order a Rock 5B (Fallback)

If BIOS modification is too risky or fails:
- Radxa Rock 5B (~€80): 2× USB3 DRD (Type-C), xDCI works out of the box
- No BIOS modification needed
- Plug between sake and beirao as a UDF bridge/test node

## WOL Status (also set during this session)

```bash
# sake: WOL enabled (volatile)
sudo ethtool -s enx00e04c680052 wol g

# To make persistent, add to netplan:
# /etc/netplan/01-direct-link.yaml:
#   ethernets:
#     enx00e04c680052:
#       wakeonlan: true
```

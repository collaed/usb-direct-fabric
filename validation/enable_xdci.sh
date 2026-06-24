#!/bin/bash
# enable_xdci.sh — Enable xDCI on Intel Gemini Lake / Ice Lake via UEFI variable modification
#
# IMPORTANT: This must be done from GRUB command line or EFI Shell, NOT from a running Linux system.
# Writing PCI config space from a running kernel can crash the system (confirmed 2026-06-22).
#
# === METHOD: grub-setup_var (recommended) ===
#
# 1. Download grub-mod-setup_var from:
#    https://github.com/datasone/grub-mod-setup_var/releases
#    Get: setup_var.efi (for EFI Shell) or modded grub with setup_var_3 command
#
# 2. Find the correct offset:
#    - Extract IFR from BIOS ROM (we have /tmp/bios.bin on sake)
#    - Use UEFITool + IFRExtractor to find the "xDCI Support" variable offset
#    - The variable is typically in "PchSetup" or "Setup" UEFI variable
#
# 3. From GRUB command line (at boot, press 'c'):
#    setup_var_3 0xNNN 0x01    # where 0xNNN is the offset found in step 2
#    reboot
#
# 4. Verify after reboot:
#    lspci -nn | grep 31aa    # sake (Gemini Lake xDCI)
#    ls /sys/class/udc/        # Should now show a UDC
#
# === ALTERNATIVE: EFI Shell ===
#
# sake has "UEFI: Built-in EFI Shell" in boot menu.
# From EFI Shell, you can modify UEFI variables directly:
#
#   Shell> setvar PchSetup -guid XXXX-XXXX -bs -rt -offset 0xNN -value 0x01
#
# === FINDING THE OFFSET ===
#
# We need to extract the IFR (Internal Forms Representation) from the BIOS.
# The BIOS ROM was dumped to /tmp/bios.bin on sake via flashrom.
#
# On a working machine, analyze it:
#   1. Install UEFITool: https://github.com/LongSoft/UEFITool/releases
#   2. Open /tmp/bios.bin in UEFITool
#   3. Search (Ctrl+F) for Unicode text "xDCI" or "USB Device" or "OTG"
#   4. If not found by string, search for GUID of the Setup form
#   5. Extract the Setup form body, run through IFRExtractor
#   6. Look for the offset of the xDCI enable option
#
# Common offsets by platform (for reference only — VERIFY before using):
#   Dell XPS 13 (Skylake):     Setup variable, offset 0x56B
#   Surface Go (Pentium Gold): PchSetup variable, offset 0x40
#   Gemini Lake NUC:           TBD — needs IFR extraction
#
# === STATUS (2026-06-22) ===
#
# - BIOS ROM dumped: /tmp/bios.bin (16 MB, via flashrom -p internal)
# - String search for "xDCI" in UCS-2: NOT FOUND in this BIOS image
# - ACPI DSDT references: XDCI, OTG0, OTG1, "Broxton XDCI controller" — confirms silicon exists
# - PCI device 8086:31aa: NOT on bus (firmware-disabled)
# - DUAL_ROLE_CFG0 register at xHCI BAR+0x80D8: readable (0x00200800), SW_IDPIN_EN=1, mode=host
# - Direct PCI CF8/CFC write: CRASHED THE SYSTEM — do NOT attempt from running Linux
#
# === NEXT STEPS ===
#
# 1. Copy /tmp/bios.bin from sake to local machine for UEFITool analysis
# 2. Run IFRExtractor to find xDCI offset
# 3. Boot sake to GRUB, use setup_var_3 to set the byte
# 4. Reboot, verify PCI device appears
#
# If IFR extraction fails to find xDCI (the string may not be present on this board):
# - Try booting to EFI Shell and enumerating UEFI variables manually
# - Or order a Radxa Rock 5B (~€80) which has xDCI enabled by default
#

echo "This script is documentation only. Do NOT run it as a bash script."
echo "Follow the instructions in the comments above."
exit 1

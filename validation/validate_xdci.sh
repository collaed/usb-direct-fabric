#!/usr/bin/env bash
set -euo pipefail

# USB Direct Fabric — xDCI Hardware Validation
# Usage: sudo ./validate_xdci.sh [hostname]
# If hostname given, runs remotely via SSH; otherwise runs locally.

HOST="${1:-}"
UDC_FOUND=1

run() {
    if [[ -n "$HOST" ]]; then
        ssh "$HOST" "sudo bash -c '$1'"
    else
        eval "$1"
    fi
}

section() { printf '\n══════ %s ══════\n' "$1"; }

section "UDC Controllers"
UDC_OUT=$(run "ls /sys/class/udc/ 2>/dev/null") || true
if [[ -n "$UDC_OUT" ]]; then
    echo "$UDC_OUT"
    UDC_FOUND=0
else
    echo "(none found)"
fi

section "dr_mode Settings"
run "find /sys -name dr_mode 2>/dev/null | while read f; do printf '%s = %s\n' \"\$f\" \"\$(cat \"\$f\")\"; done" || true

section "PCI USB/xHCI/DWC Devices"
run "lspci | grep -i 'usb\|xhci\|dwc'" || echo "(none)"

section "USB Tree"
run "lsusb -t" || true

section "DWC3 UDC State"
run "cat /sys/bus/platform/drivers/dwc3/*/udc/*/state 2>/dev/null" || echo "(not available)"

section "DWC3 Kernel Messages (last 20)"
run "dmesg | grep -i 'dwc3\|xdci\|udc' | tail -20" || echo "(none)"

section "DWC3 Platform Driver Instances"
run "ls /sys/bus/platform/drivers/dwc3/ 2>/dev/null" || echo "(not present)"

section "DWC3 Module Check"
if run "lsmod | grep -q dwc3"; then
    echo "dwc3 module loaded"
else
    echo "dwc3 not loaded, attempting modprobe..."
    run "modprobe dwc3 2>&1" || echo "modprobe failed"
    if run "lsmod | grep -q dwc3"; then
        echo "dwc3 loaded after modprobe"
    else
        echo "dwc3 still not loaded"
    fi
fi

section "USB Debug Devices (first 100 lines)"
run "cat /sys/kernel/debug/usb/devices 2>/dev/null | head -100" || echo "(not available — mount debugfs?)"

section "Result"
if [[ $UDC_FOUND -eq 0 ]]; then
    echo "✓ UDC found — device controller available"
else
    echo "✗ No UDC found — xDCI not available"
fi

exit $UDC_FOUND

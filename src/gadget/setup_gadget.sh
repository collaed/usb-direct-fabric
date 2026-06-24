#!/bin/bash
# setup_gadget.sh — Configure USB gadget for UDF raw bulk transfer
set -euo pipefail

GADGET_PATH="/sys/kernel/config/usb_gadget/udf"
FFS_MOUNT="/tmp/udf_ffs"

die() { echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Must be run as root"

teardown() {
    echo "Tearing down UDF gadget..."
    if [[ -d "$GADGET_PATH" ]]; then
        echo "" > "$GADGET_PATH/UDC" 2>/dev/null || true
        rm -f "$GADGET_PATH/configs/c.1/ffs.udf0"
        rmdir "$GADGET_PATH/configs/c.1/strings/0x409" 2>/dev/null || true
        rmdir "$GADGET_PATH/configs/c.1" 2>/dev/null || true
        rmdir "$GADGET_PATH/functions/ffs.udf0" 2>/dev/null || true
        rmdir "$GADGET_PATH/strings/0x409" 2>/dev/null || true
        rmdir "$GADGET_PATH" 2>/dev/null || true
    fi
    umount "$FFS_MOUNT" 2>/dev/null || true
    rmdir "$FFS_MOUNT" 2>/dev/null || true
    echo "Teardown complete."
}

setup_g_zero() {
    echo "Loading g_zero module for quick benchmarking..."
    modprobe g_zero || die "Failed to load g_zero"
    echo "g_zero loaded. Use bulk_bench.sh on host side."
}

setup_gadget() {
    local udc="${1:-}"
    if [[ -z "$udc" ]]; then
        udc=$(ls /sys/class/udc/ 2>/dev/null | head -1)
        [[ -n "$udc" ]] || die "No UDC found in /sys/class/udc/"
        echo "Auto-detected UDC: $udc"
    fi

    modprobe libcomposite || true
    modprobe usb_f_fs || true

    mkdir -p "$GADGET_PATH"
    echo 0x1d6b > "$GADGET_PATH/idVendor"
    echo 0x0105 > "$GADGET_PATH/idProduct"

    mkdir -p "$GADGET_PATH/strings/0x409"
    echo "UDF Project"         > "$GADGET_PATH/strings/0x409/manufacturer"
    echo "USB Direct Fabric"   > "$GADGET_PATH/strings/0x409/product"
    echo "0001"                > "$GADGET_PATH/strings/0x409/serialnumber"

    mkdir -p "$GADGET_PATH/configs/c.1/strings/0x409"
    echo "UDF Config" > "$GADGET_PATH/configs/c.1/strings/0x409/configuration"

    mkdir -p "$GADGET_PATH/functions/ffs.udf0"
    ln -sf "$GADGET_PATH/functions/ffs.udf0" "$GADGET_PATH/configs/c.1/ffs.udf0"

    mkdir -p "$FFS_MOUNT"
    mount -t functionfs udf0 "$FFS_MOUNT"
    echo "FunctionFS mounted at $FFS_MOUNT"

    echo "$udc" > "$GADGET_PATH/UDC"
    echo "Gadget bound to UDC: $udc"
}

case "${1:-}" in
    --teardown) teardown ;;
    --g-zero)   setup_g_zero ;;
    *)          setup_gadget "${1:-}" ;;
esac

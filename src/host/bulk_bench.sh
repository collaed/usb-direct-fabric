#!/bin/bash
# bulk_bench.sh — Benchmark raw USB bulk transfers from host side
set -euo pipefail

DURATION="${1:-30}"
SIZES=(512 4096 16384 65536)

die() { echo "ERROR: $*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Must be run as root"

if ! command -v testusb &>/dev/null; then
    cat >&2 <<'EOF'
testusb not found. Compile from kernel source:
  cd /usr/src/linux/tools/usb
  gcc -o testusb testusb.c -lpthread
  cp testusb /usr/local/bin/
Or: apt install linux-tools-$(uname -r)
EOF
    exit 1
fi

modprobe usbtest || true

# Find device: UDF (1d6b:0105) or g_zero (0525:a4a0)
find_dev() {
    for d in /sys/bus/usb/devices/*/idVendor; do
        local base=$(dirname "$d")
        local vid=$(cat "$base/idVendor" 2>/dev/null)
        local pid=$(cat "$base/idProduct" 2>/dev/null)
        if [[ "$vid:$pid" == "1d6b:0105" || "$vid:$pid" == "0525:a4a0" ]]; then
            echo "${base##*/}"
            return 0
        fi
    done
    return 1
}

DEV=$(find_dev) || die "No UDF or g_zero device found"
echo "Found device: $DEV"

# Bind to usbtest if not already
BUSNUM=$(cat "/sys/bus/usb/devices/$DEV/busnum")
DEVNUM=$(cat "/sys/bus/usb/devices/$DEV/devnum")

run_test() {
    local test_num=$1 label=$2 size=$3
    local iterations=$(( (DURATION * 1000000) / (size + 64) ))  # rough estimate
    [[ $iterations -lt 100 ]] && iterations=100

    local out
    out=$(testusb -D "/dev/bus/usb/$(printf '%03d' "$BUSNUM")/$(printf '%03d' "$DEVNUM")" \
        -t "$test_num" -g "$size" -c "$iterations" 2>&1) || true

    # Parse timing from testusb output
    local usecs=$(echo "$out" | grep -oP '\d+(?= usecs)' | tail -1)
    if [[ -n "$usecs" && "$usecs" -gt 0 ]]; then
        local bytes=$(( iterations * size ))
        local mb_s=$(echo "scale=2; $bytes / $usecs" | bc)
        local gbps=$(echo "scale=2; $mb_s * 8 / 1000" | bc)
        printf "  %-12s %6d B × %d iter: %s MB/s (%s Gbps)\n" "$label" "$size" "$iterations" "$mb_s" "$gbps"
    else
        printf "  %-12s %6d B: %s\n" "$label" "$size" "$out"
    fi
}

echo "=== USB Bulk Transfer Benchmark (duration ~${DURATION}s per test) ==="
echo ""
echo "--- Bulk OUT (host → device) ---"
for sz in "${SIZES[@]}"; do
    run_test 5 "OUT" "$sz"
done

echo ""
echo "--- Bulk IN (device → host) ---"
for sz in "${SIZES[@]}"; do
    run_test 6 "IN" "$sz"
done

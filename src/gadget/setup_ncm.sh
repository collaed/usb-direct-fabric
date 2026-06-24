#!/usr/bin/env bash
# setup_ncm.sh — Configure CDC-NCM USB gadget for IP compatibility layer
# Part of USB Direct Fabric (UDF) Phase 9
set -euo pipefail

GADGET=/sys/kernel/config/usb_gadget/udf_ncm
UDC=""
IP="10.0.0.1/24"
PEER_IP="10.0.0.2/24"
HOST_ADDR=""
DEV_ADDR=""
DHCP=0
TEARDOWN=0
STATUS=0

die() { echo "ERROR: $*" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Configure CDC-NCM USB gadget mode as an IP compatibility layer.
Must be run as root.

Options:
  --udc UDC         UDC controller name (auto-detected from /sys/class/udc/ if omitted)
  --ip CIDR         IP address for usb0 (default: 10.0.0.1/24)
  --peer-ip CIDR    Expected peer IP (default: 10.0.0.2/24, informational only)
  --host-addr MAC   Set host-side MAC address
  --dev-addr MAC    Set device-side MAC address
  --dhcp            Start dnsmasq DHCP server on usb0
  --teardown        Remove gadget configuration and bring down interface
  --status          Show current gadget/interface state
  -h, --help        Show this help

Examples:
  sudo ./setup_ncm.sh                          # Auto-detect UDC, default IPs
  sudo ./setup_ncm.sh --udc dwc3.0 --ip 10.0.0.5/24
  sudo ./setup_ncm.sh --teardown
  sudo ./setup_ncm.sh --status

Note: For raw UDF bulk transport, use setup_gadget.sh instead.
      NCM adds ~10-20% overhead but provides standard IP networking.
EOF
    exit 0
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --udc) UDC="$2"; shift 2 ;;
            --ip) IP="$2"; shift 2 ;;
            --peer-ip) PEER_IP="$2"; shift 2 ;;
            --host-addr) HOST_ADDR="$2"; shift 2 ;;
            --dev-addr) DEV_ADDR="$2"; shift 2 ;;
            --dhcp) DHCP=1; shift ;;
            --teardown) TEARDOWN=1; shift ;;
            --status) STATUS=1; shift ;;
            -h|--help) usage ;;
            *) die "Unknown option: $1" ;;
        esac
    done
}

detect_udc() {
    if [[ -z "$UDC" ]]; then
        local udcs=(/sys/class/udc/*)
        [[ ${#udcs[@]} -eq 0 || ! -d "${udcs[0]}" ]] && die "No UDC found in /sys/class/udc/"
        UDC=$(basename "${udcs[0]}")
        echo "Auto-detected UDC: $UDC"
    fi
}

do_status() {
    echo "=== Gadget State ==="
    if [[ -d "$GADGET" ]]; then
        echo "Gadget:  $GADGET (exists)"
        echo "UDC:     $(cat "$GADGET/UDC" 2>/dev/null || echo 'unbound')"
    else
        echo "Gadget:  not configured"
    fi
    echo
    echo "=== Interface State ==="
    if ip link show usb0 &>/dev/null; then
        ip addr show usb0
    else
        echo "usb0: not present"
    fi
    exit 0
}

do_teardown() {
    echo "Tearing down NCM gadget..."
    if ip link show usb0 &>/dev/null; then
        ip link set usb0 down 2>/dev/null || true
    fi
    if [[ -d "$GADGET" ]]; then
        echo "" > "$GADGET/UDC" 2>/dev/null || true
        rm -f "$GADGET/configs/c.1/ncm.usb0" 2>/dev/null || true
        rmdir "$GADGET/configs/c.1/strings/0x409" 2>/dev/null || true
        rmdir "$GADGET/configs/c.1" 2>/dev/null || true
        rmdir "$GADGET/functions/ncm.usb0" 2>/dev/null || true
        rmdir "$GADGET/strings/0x409" 2>/dev/null || true
        rmdir "$GADGET" 2>/dev/null || true
    fi
    echo "Done."
    exit 0
}

do_setup() {
    detect_udc

    # Load modules
    modprobe libcomposite 2>/dev/null || true
    modprobe usb_f_ncm 2>/dev/null || true

    # Create gadget
    mkdir -p "$GADGET"
    echo 0x1d6b > "$GADGET/idVendor"
    echo 0x0106 > "$GADGET/idProduct"
    echo 0x0100 > "$GADGET/bcdDevice"
    echo 0x0200 > "$GADGET/bcdUSB"

    # Strings
    mkdir -p "$GADGET/strings/0x409"
    echo "UDF Project"                  > "$GADGET/strings/0x409/manufacturer"
    echo "USB Direct Fabric (NCM)"      > "$GADGET/strings/0x409/product"
    echo "0001"                         > "$GADGET/strings/0x409/serialnumber"

    # NCM function
    mkdir -p "$GADGET/functions/ncm.usb0"
    [[ -n "$HOST_ADDR" ]] && echo "$HOST_ADDR" > "$GADGET/functions/ncm.usb0/host_addr"
    [[ -n "$DEV_ADDR" ]]  && echo "$DEV_ADDR"  > "$GADGET/functions/ncm.usb0/dev_addr"

    # Config
    mkdir -p "$GADGET/configs/c.1/strings/0x409"
    echo "NCM Network" > "$GADGET/configs/c.1/strings/0x409/configuration"
    echo 250 > "$GADGET/configs/c.1/MaxPower"
    ln -sf "$GADGET/functions/ncm.usb0" "$GADGET/configs/c.1/"

    # Bind
    echo "$UDC" > "$GADGET/UDC"
    echo "Bound to UDC: $UDC"

    # Wait for interface
    echo -n "Waiting for usb0..."
    for i in $(seq 1 30); do
        if ip link show usb0 &>/dev/null; then
            echo " up"
            break
        fi
        sleep 0.2
        echo -n "."
    done
    ip link show usb0 &>/dev/null || die "usb0 did not appear after 6s"

    # Configure IP
    ip link set usb0 up
    ip addr add "$IP" dev usb0 2>/dev/null || true
    echo "Configured usb0 with $IP"

    # DHCP
    if [[ $DHCP -eq 1 ]]; then
        command -v dnsmasq &>/dev/null || die "dnsmasq not installed"
        local net="${IP%.*}"
        dnsmasq --interface=usb0 --bind-interfaces \
            --dhcp-range="${net}.10,${net}.50,12h" \
            --except-interface=lo --no-daemon &
        echo "dnsmasq DHCP started on usb0 (range ${net}.10-${net}.50)"
    fi

    # Status
    echo
    echo "=== NCM Gadget Active ==="
    echo "  Device IP:  $IP"
    echo "  Peer IP:    $PEER_IP (configure on host side)"
    echo
    echo "Host-side instructions:"
    echo "  The host should see a new CDC-NCM network interface (e.g. usb0 or enx...)."
    echo "  Configure it with: ip addr add $PEER_IP dev <iface> && ip link set <iface> up"
    echo
    echo "Note: For raw UDF bulk transport, use setup_gadget.sh instead."
    echo "      NCM adds ~10-20% overhead but provides standard IP networking."
}

# Main
[[ $EUID -ne 0 ]] && die "Must be run as root"
parse_args "$@"
[[ $STATUS -eq 1 ]] && do_status
[[ $TEARDOWN -eq 1 ]] && do_teardown
do_setup

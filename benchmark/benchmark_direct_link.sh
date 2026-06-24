#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
SAKE="sake"
BEIRAO="beirao"
SAKE_IP="192.168.100.1"
BEIRAO_IP="192.168.100.2"
DURATION=30
RUNS=3
PORT=5201

SAKE_IF="enx00e04c680052"
BEIRAO_IF="enx00e04c68007d"

RESULTS="$(dirname "$0")/results/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS"

# --- Cleanup trap ---
cleanup() {
    echo "[*] Cleaning up remote iperf3 processes..."
    ssh "$SAKE" "pkill -f 'iperf3 -s' || true" 2>/dev/null
    ssh "$BEIRAO" "pkill -f 'iperf3 -s' || true" 2>/dev/null
}
trap cleanup EXIT

# --- Helper: start iperf3 server on remote node ---
start_server() { ssh "$1" "iperf3 -s -p $PORT -D"; sleep 1; }
kill_server() { ssh "$1" "pkill -f 'iperf3 -s' || true"; sleep 1; }

# --- Pre-flight checks ---
echo "=== Pre-flight checks ==="

echo "[*] Verifying SSH connectivity..."
ssh "$SAKE" "true"
ssh "$BEIRAO" "true"

echo "[*] Verifying link state..."
SAKE_STATE=$(ssh "$SAKE" "cat /sys/class/net/$SAKE_IF/operstate")
BEIRAO_STATE=$(ssh "$BEIRAO" "cat /sys/class/net/$BEIRAO_IF/operstate")
[[ "$SAKE_STATE" == "up" ]] || { echo "FAIL: $SAKE_IF is $SAKE_STATE on sake"; exit 1; }
[[ "$BEIRAO_STATE" == "up" ]] || { echo "FAIL: $BEIRAO_IF is $BEIRAO_STATE on beirao"; exit 1; }

echo "[*] MTU:"
ssh "$SAKE" "ip link show $SAKE_IF | grep -oP 'mtu \K[0-9]+'"
ssh "$BEIRAO" "ip link show $BEIRAO_IF | grep -oP 'mtu \K[0-9]+'"

echo "[*] Verifying required tools..."
for node in "$SAKE" "$BEIRAO"; do
    for tool in iperf3 nc jq mpstat; do
        ssh "$node" "command -v $tool >/dev/null" || { echo "FAIL: $tool missing on $node"; exit 1; }
    done
done

echo "=== Pre-flight OK ==="
echo ""

# --- Test 1: Unidirectional sake→beirao (TCP) ---
echo "=== Test 1: TCP sake→beirao ==="
start_server "$BEIRAO"
for i in $(seq 1 "$RUNS"); do
    echo "  Run $i/$RUNS"
    ssh "$SAKE" "iperf3 -c $BEIRAO_IP -p $PORT -t $DURATION -J" > "$RESULTS/test1_run${i}.json"
done
kill_server "$BEIRAO"

# --- Test 2: Unidirectional beirao→sake (TCP) ---
echo "=== Test 2: TCP beirao→sake ==="
start_server "$SAKE"
for i in $(seq 1 "$RUNS"); do
    echo "  Run $i/$RUNS"
    ssh "$BEIRAO" "iperf3 -c $SAKE_IP -p $PORT -t $DURATION -J" > "$RESULTS/test2_run${i}.json"
done
kill_server "$SAKE"

# --- Test 3: Bidirectional simultaneous ---
echo "=== Test 3: Bidirectional ==="
start_server "$BEIRAO"
start_server "$SAKE"
ssh "$SAKE" "iperf3 -c $BEIRAO_IP -p $PORT -t $DURATION -J" > "$RESULTS/test3_s2b.json" &
PID1=$!
ssh "$BEIRAO" "iperf3 -c $SAKE_IP -p $PORT -t $DURATION -J" > "$RESULTS/test3_b2s.json" &
PID2=$!
wait $PID1 $PID2
kill_server "$BEIRAO"
kill_server "$SAKE"

# --- Test 4: UDP saturation sake→beirao ---
echo "=== Test 4: UDP saturation sake→beirao ==="
start_server "$BEIRAO"
ssh "$SAKE" "iperf3 -c $BEIRAO_IP -p $PORT -u -b 3G -t $DURATION -J" > "$RESULTS/test4_udp.json"
kill_server "$BEIRAO"

# --- Test 5: Raw throughput with dd+nc ---
echo "=== Test 5: Raw throughput (dd+nc) ==="
NC_PORT=9999
BYTES=$((1024*1024*512))

echo "  /dev/zero (512MB)..."
ssh "$BEIRAO" "nc -l -p $NC_PORT > /dev/null" &
sleep 1
ZERO_TIME=$(ssh "$SAKE" "dd if=/dev/zero bs=1M count=512 2>/dev/null | { time nc $BEIRAO_IP $NC_PORT; } 2>&1 | grep real | awk '{print \$2}'")
echo "  Zero time: $ZERO_TIME" | tee "$RESULTS/test5_zero.txt"
wait 2>/dev/null || true

echo "  /dev/urandom (512MB)..."
ssh "$BEIRAO" "nc -l -p $NC_PORT > /dev/null" &
sleep 1
URAND_TIME=$(ssh "$SAKE" "dd if=/dev/urandom bs=1M count=512 2>/dev/null | { time nc $BEIRAO_IP $NC_PORT; } 2>&1 | grep real | awk '{print \$2}'")
echo "  Urandom time: $URAND_TIME" | tee "$RESULTS/test5_urandom.txt"
wait 2>/dev/null || true

# --- Test 6: CPU load during iperf3 ---
echo "=== Test 6: CPU load ==="
start_server "$BEIRAO"
ssh "$SAKE" "mpstat 1 $DURATION" > "$RESULTS/test6_cpu_sake.txt" &
PID_MPSTAT_S=$!
ssh "$BEIRAO" "mpstat 1 $DURATION" > "$RESULTS/test6_cpu_beirao.txt" &
PID_MPSTAT_B=$!
ssh "$SAKE" "iperf3 -c $BEIRAO_IP -p $PORT -t $DURATION" > /dev/null
wait $PID_MPSTAT_S $PID_MPSTAT_B
kill_server "$BEIRAO"

# --- Summary ---
echo ""
echo "=== Summary ==="
echo "Results directory: $RESULTS"
echo ""

printf "%-30s %s\n" "Test" "Throughput (Gbps)"
printf "%-30s %s\n" "----" "-----------------"

for i in $(seq 1 "$RUNS"); do
    BPS=$(jq '.end.sum_sent.bits_per_second // .end.sum_received.bits_per_second' "$RESULTS/test1_run${i}.json" 2>/dev/null || echo 0)
    printf "%-30s %.2f\n" "T1 sake→beirao run$i" "$(echo "$BPS / 1000000000" | bc -l)"
done

for i in $(seq 1 "$RUNS"); do
    BPS=$(jq '.end.sum_sent.bits_per_second // .end.sum_received.bits_per_second' "$RESULTS/test2_run${i}.json" 2>/dev/null || echo 0)
    printf "%-30s %.2f\n" "T2 beirao→sake run$i" "$(echo "$BPS / 1000000000" | bc -l)"
done

BPS=$(jq '.end.sum_sent.bits_per_second // .end.sum_received.bits_per_second' "$RESULTS/test3_s2b.json" 2>/dev/null || echo 0)
printf "%-30s %.2f\n" "T3 bidir sake→beirao" "$(echo "$BPS / 1000000000" | bc -l)"
BPS=$(jq '.end.sum_sent.bits_per_second // .end.sum_received.bits_per_second' "$RESULTS/test3_b2s.json" 2>/dev/null || echo 0)
printf "%-30s %.2f\n" "T3 bidir beirao→sake" "$(echo "$BPS / 1000000000" | bc -l)"

BPS=$(jq '.end.sum.bits_per_second' "$RESULTS/test4_udp.json" 2>/dev/null || echo 0)
printf "%-30s %.2f\n" "T4 UDP sake→beirao" "$(echo "$BPS / 1000000000" | bc -l)"

echo ""
echo "T5 raw dd+nc: zero=$ZERO_TIME urandom=$URAND_TIME"
echo "T6 CPU logs: $RESULTS/test6_cpu_*.txt"
echo ""
echo "=== Done ==="

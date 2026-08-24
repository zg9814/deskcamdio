#!/usr/bin/env bash
# Real-device metrics sampler for the deskcamdio MAIN service process:
# RSS/PSS/FD of the systemd MainPID + system swap/available → stdout (+ json file).
# Usage: measure_pi.sh [duration_s] [interval_s] [out_file]   (UNIT env overrides service)
set -euo pipefail

DURATION="${1:-10}"
INTERVAL="${2:-1}"
OUT="${3:-}"
UNIT="${UNIT:-deskcamdio.service}"

main_pid() { systemctl show -p MainPID --value "$UNIT"; }

sample_once() {
    local pid rss pss fd avail swap
    pid=$(main_pid)
    if [[ -z "$pid" || "$pid" == "0" || ! -r "/proc/$pid/status" ]]; then
        echo "${UNIT} not running (MainPID=${pid:-?})" >&2
        return 1
    fi
    rss=$(awk '/^VmRSS/{print $2}' "/proc/$pid/status" 2>/dev/null || echo 0)
    pss=0
    if [[ -r "/proc/$pid/smaps_rollup" ]]; then
        pss=$(awk '/^Pss:/{print $2}' "/proc/$pid/smaps_rollup")
    fi
    fd=$(ls "/proc/$pid/fd" 2>/dev/null | wc -l)
    avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
    swap=$(( $(awk '/SwapTotal/{print $2}' /proc/meminfo) - $(awk '/SwapFree/{print $2}' /proc/meminfo) ))
    printf 'pid=%s rss_kb=%s pss_kb=%s fd=%s available_kb=%s swap_kb=%s\n' \
        "$pid" "$rss" "$pss" "$fd" "$avail" "$swap"
}

elapsed=0
while [[ $elapsed -lt $DURATION ]]; do
    line=$(sample_once)
    echo "$(date -u +%H:%M:%S) $line"
    [[ -n "$OUT" ]] && echo "$line" >> "$OUT"
    sleep "$INTERVAL"
    elapsed=$(( elapsed + INTERVAL ))
done

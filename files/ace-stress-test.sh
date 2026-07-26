#!/bin/sh
# Long-run ACE connection stress test for CosmOS / Centauri (BusyBox sh).
# Manual start only — do NOT install as a boot service (112MB RAM).
#
# Gently pokes health every INTERVAL seconds for DURATION minutes, while
# also tracking USB presence and dmesg disconnects. Spaced so it does not
# tip the board into "Timer too close".
#
# Usage:
#   ace-stress-test.sh                 # 30 min, health every 15s
#   ace-stress-test.sh 30 15           # duration_min interval_s
#   DURATION=60 INTERVAL=20 ./ace-stress-test.sh
#   LOG=/tmp/ace-stress.log ./ace-stress-test.sh
#
# Stop early: Ctrl-C, or: kill $(cat /var/run/ace-stress.pid)
#
# Results append to /board-resource/ace-stress.log

set -u

ADDON_DIR="${ADDON_DIR:-/user-resource/ace-addon}"
ACE_CMD="${ACE_CMD:-${ADDON_DIR}/ace-command.sh}"
LOG="${LOG:-/board-resource/ace-stress.log}"
PIDFILE="${PIDFILE:-/var/run/ace-stress.pid}"
ACE_VID="${ACE_VID:-28e9}"

DURATION_MIN="${1:-${DURATION:-30}}"
INTERVAL_S="${2:-${INTERVAL:-15}}"

# Sanity: do not hammer. Floor interval at 5s on this board.
case "$INTERVAL_S" in
    ''|*[!0-9]*) INTERVAL_S=15 ;;
esac
[ "$INTERVAL_S" -lt 5 ] && INTERVAL_S=5

case "$DURATION_MIN" in
    ''|*[!0-9]*) DURATION_MIN=30 ;;
esac
[ "$DURATION_MIN" -lt 1 ] && DURATION_MIN=1

DURATION_S=$((DURATION_MIN * 60))
# BusyBox date may not support +%s; fall back to a counter.
if date +%s >/dev/null 2>&1; then
    START_EPOCH="$(date +%s)"
    have_epoch=1
else
    START_EPOCH=0
    have_epoch=0
fi

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
echo $$ > "$PIDFILE" 2>/dev/null || true

say() {
    ts="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date)"
    printf '%s %s\n' "$ts" "$*" | tee -a "$LOG"
}

cleanup() {
    say "INTERRUPTED — printing partial summary"
    print_summary
    rm -f "$PIDFILE" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

ok=0
fail=0
sum_ms=0
n_ms=0
min_ms=999999
max_ms=0
ace_present_hits=0
ace_absent_hits=0
flaps_start="$(dmesg 2>/dev/null | grep -c 'USB disconnect' || echo 0)"
# strip any newlines from busybox quirks
flaps_start="$(printf '%s' "$flaps_start" | tr -cd '0-9')"
[ -n "$flaps_start" ] || flaps_start=0

load_warn=0
sample=0
next_progress=300

elapsed_s() {
    if [ "$have_epoch" -eq 1 ]; then
        now="$(date +%s)"
        echo $((now - START_EPOCH))
    else
        echo $((sample * INTERVAL_S))
    fi
}

print_summary() {
    elapsed="$(elapsed_s)"
    total=$((ok + fail))
    flaps_now="$(dmesg 2>/dev/null | grep -c 'USB disconnect' || echo 0)"
    flaps_now="$(printf '%s' "$flaps_now" | tr -cd '0-9')"
    [ -n "$flaps_now" ] || flaps_now=0
    flaps=$((flaps_now - flaps_start))
    [ "$flaps" -lt 0 ] && flaps="$flaps_now"

    avg=0
    [ "$n_ms" -gt 0 ] && avg=$((sum_ms / n_ms))

    pct=0
    [ "$total" -gt 0 ] && pct=$((ok * 100 / total))

    say "==== STRESS SUMMARY (${elapsed}s / ${DURATION_S}s planned) ===="
    say "health: ok=${ok} fail=${fail} total=${total} success=${pct}%"
    if [ "$n_ms" -gt 0 ]; then
        say "latency_ms: min/avg/max=${min_ms}/${avg}/${max_ms}"
    else
        say "latency_ms: n/a"
    fi
    say "usb: present_samples=${ace_present_hits} absent_samples=${ace_absent_hits}"
    say "dmesg USB disconnects during run: ${flaps}"
    say "load_warn_samples (loadavg1>=2.0): ${load_warn}"
    say "log: ${LOG}"
}

say "==== ace-stress-test start duration=${DURATION_MIN}m interval=${INTERVAL_S}s ===="
say "pid=$$ log=${LOG} conf via ${ACE_CMD}"
say "NOTE: leave ace-usb-watch / other hammers off during this run (112MB board)."

while true; do
    elapsed="$(elapsed_s)"
    if [ "$elapsed" -ge "$DURATION_S" ]; then
        break
    fi

    sample=$((sample + 1))

    # USB present?
    if lsusb 2>/dev/null | grep -qi "$ACE_VID"; then
        ace_present_hits=$((ace_present_hits + 1))
        ace_state=present
    else
        ace_absent_hits=$((ace_absent_hits + 1))
        ace_state=absent
    fi

    # Host load (1-min)
    load1="$(cut -d' ' -f1 /proc/loadavg 2>/dev/null || echo '?')"
    case "$load1" in
        2.*|3.*|4.*|5.*|6.*|7.*|8.*|9.*|[1-9][0-9]*)
            load_warn=$((load_warn + 1))
            ;;
    esac

    out="$("$ACE_CMD" health 2>&1)" || true
    if printf '%s' "$out" | grep -q '"ok": true'; then
        ok=$((ok + 1))
        status=OK
    else
        fail=$((fail + 1))
        status=FAIL
        err="$(printf '%s' "$out" | grep -o '"error": "[^"]*"' | head -n 1)"
        say "sample ${sample} FAIL ace=${ace_state} load=${load1} ${err:-no-json}"
    fi

    ms="$(printf '%s' "$out" | grep -o '"elapsed_ms": [0-9]*' | grep -o '[0-9]*' | head -n 1)"
    if [ -n "$ms" ]; then
        sum_ms=$((sum_ms + ms))
        n_ms=$((n_ms + 1))
        [ "$ms" -lt "$min_ms" ] && min_ms="$ms"
        [ "$ms" -gt "$max_ms" ] && max_ms="$ms"
    else
        ms="?"
    fi

    # Quiet per-sample line (successes are one-liners; failures already logged above)
    if [ "$status" = "OK" ]; then
        say "sample ${sample} OK ace=${ace_state} load=${load1} elapsed_ms=${ms}"
    fi

    # Progress every ~5 minutes of wall time
    if [ "$elapsed" -ge "$next_progress" ]; then
        total=$((ok + fail))
        pct=0
        [ "$total" -gt 0 ] && pct=$((ok * 100 / total))
        say "PROGRESS ${elapsed}s: ok=${ok} fail=${fail} (${pct}%) load=${load1}"
        next_progress=$((next_progress + 300))
    fi

    # If load is already high, back off this tick instead of stacking more work.
    case "$load1" in
        3.*|4.*|5.*|6.*|7.*|8.*|9.*|[1-9][0-9]*)
            say "BACKOFF load=${load1} — sleeping ${INTERVAL_S}s extra"
            sleep "$INTERVAL_S"
            ;;
    esac

    sleep "$INTERVAL_S"
done

print_summary
rm -f "$PIDFILE" 2>/dev/null || true
say "==== ace-stress-test done ===="

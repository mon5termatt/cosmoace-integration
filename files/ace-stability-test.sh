#!/bin/sh
# ACE link stability experiments for CosmOS / Centauri (BusyBox sh).
# Manual start only — do NOT install as a boot service (112MB RAM).
#
# Usage:
#   ace-stability-test.sh flap   [seconds]   # USB disconnect rate from dmesg (default 60s)
#   ace-stability-test.sh rpc    [count]     # hammer health via current conf (default 20)
#   ace-stability-test.sh paths  [count]     # A/B raw ttyACM vs by-id vs by-path (default 10 each)
#   ace-stability-test.sh settle [count]     # sweep connect_settle_s 0/0.15/0.5/1.0 (default 10 each)
#   ace-stability-test.sh all                # flap 30s + rpc + paths + settle
#
# Results append to /board-resource/ace-stability.log (override with LOG=...).

set -u

ADDON_DIR="${ADDON_DIR:-/user-resource/ace-addon}"
ACE_CMD="${ACE_CMD:-${ADDON_DIR}/ace-command.sh}"
BASE_CONF="${BASE_CONF:-${ADDON_DIR}/ace-addon.conf}"
LOG="${LOG:-/board-resource/ace-stability.log}"
TMPDIR_STAB="/tmp/ace-stab.$$"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
mkdir -p "$TMPDIR_STAB"
trap 'rm -rf "$TMPDIR_STAB" 2>/dev/null || true' EXIT INT TERM

say() {
    ts="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date)"
    printf '%s %s\n' "$ts" "$*" | tee -a "$LOG"
}

# make_conf <out> <serial_port|-> <connect_settle_s|->  ('-' keeps base value)
make_conf() {
    out="$1"; port="$2"; settle="$3"
    cp "$BASE_CONF" "$out"
    if [ "$port" != "-" ]; then
        sed -i "s|^serial_port *=.*|serial_port = ${port}|" "$out"
    fi
    if [ "$settle" != "-" ]; then
        if grep -q '^connect_settle_s' "$out"; then
            sed -i "s|^connect_settle_s *=.*|connect_settle_s = ${settle}|" "$out"
        else
            sed -i "s|^connect_retry_delay_s|connect_settle_s = ${settle}\nconnect_retry_delay_s|" "$out"
        fi
    fi
}

# hammer <label> <conf> <count>  -> "ok=N fail=N min/avg/max ms"
hammer() {
    label="$1"; conf="$2"; count="$3"
    ok=0; fail=0; sum=0; min=999999; max=0; n=0
    i=0
    while [ "$i" -lt "$count" ]; do
        out="$(ACE_ADDON_CONFIG="$conf" "$ACE_CMD" health 2>&1)" || true
        if printf '%s' "$out" | grep -q '"ok": true'; then
            ok=$((ok + 1))
        else
            fail=$((fail + 1))
            err="$(printf '%s' "$out" | grep -o '"error": "[^"]*"' | head -n 1)"
            say "  ${label} call $((i + 1)) FAIL ${err:-no-json}"
        fi
        ms="$(printf '%s' "$out" | grep -o '"elapsed_ms": [0-9]*' | grep -o '[0-9]*' | head -n 1)"
        if [ -n "$ms" ]; then
            sum=$((sum + ms)); n=$((n + 1))
            [ "$ms" -lt "$min" ] && min="$ms"
            [ "$ms" -gt "$max" ] && max="$ms"
        fi
        i=$((i + 1))
        sleep 1
    done
    if [ "$n" -gt 0 ]; then
        avg=$((sum / n))
        say "RESULT ${label}: ok=${ok}/${count} fail=${fail} elapsed_ms min/avg/max=${min}/${avg}/${max}"
    else
        say "RESULT ${label}: ok=${ok}/${count} fail=${fail} elapsed_ms n/a"
    fi
}

mode_flap() {
    seconds="${1:-60}"
    say "== flap: counting USB disconnects over ${seconds}s =="
    before="$(dmesg 2>/dev/null | grep -c 'USB disconnect' || echo 0)"
    sleep "$seconds"
    after="$(dmesg 2>/dev/null | grep -c 'USB disconnect' || echo 0)"
    flaps=$((after - before))
    [ "$flaps" -lt 0 ] && flaps="$after"  # dmesg ring buffer wrapped
    say "RESULT flap: ${flaps} disconnects in ${seconds}s"
    dmesg 2>/dev/null | grep -iE 'USB disconnect|cdc_acm|error -71|error -32' | tail -4 | while read -r line; do
        say "  dmesg: $line"
    done
}

mode_rpc() {
    count="${1:-20}"
    say "== rpc: ${count} health calls via ${BASE_CONF} =="
    hammer "rpc(base-conf)" "$BASE_CONF" "$count"
}

# Find the ACE by-id alias and everything that resolves to the same node.
find_ace_byid() {
    for alias in /dev/serial/by-id/*; do
        [ -e "$alias" ] || continue
        case "$(echo "$alias" | tr 'a-z' 'A-Z')" in
            *ACE*|*ANYCUBIC*) echo "$alias"; return 0 ;;
        esac
    done
    return 1
}

mode_paths() {
    count="${1:-10}"
    say "== paths: ${count} calls each via raw tty / by-id / by-path =="
    byid="$(find_ace_byid || true)"
    if [ -z "$byid" ]; then
        say "RESULT paths: no ACE by-id alias found — is the ACE enumerated? (lsusb 28e9)"
        return 1
    fi
    raw="$(readlink -f "$byid")"
    bypath=""
    for alias in /dev/serial/by-path/*; do
        [ -e "$alias" ] || continue
        if [ "$(readlink -f "$alias")" = "$raw" ]; then
            bypath="$alias"
            break
        fi
    done
    say "  by-id=${byid} raw=${raw} by-path=${bypath:-none}"

    make_conf "$TMPDIR_STAB/raw.conf" "$raw" "-"
    hammer "paths(raw ${raw})" "$TMPDIR_STAB/raw.conf" "$count"

    make_conf "$TMPDIR_STAB/byid.conf" "$byid" "-"
    hammer "paths(by-id)" "$TMPDIR_STAB/byid.conf" "$count"

    if [ -n "$bypath" ]; then
        make_conf "$TMPDIR_STAB/bypath.conf" "$bypath" "-"
        hammer "paths(by-path)" "$TMPDIR_STAB/bypath.conf" "$count"
    fi
    say "NOTE paths: raw tty loses if the node renumbered mid-test; by-id should not care."
}

mode_settle() {
    count="${1:-10}"
    say "== settle: ${count} calls each with connect_settle_s sweep (serial_port=auto) =="
    for settle in 0 0.15 0.5 1.0; do
        conf="$TMPDIR_STAB/settle-${settle}.conf"
        make_conf "$conf" "auto" "$settle"
        hammer "settle(${settle}s)" "$conf" "$count"
    done
    say "NOTE settle: pick the smallest value whose ok-rate matches the best one."
}

mode="${1:-all}"
case "$mode" in
    flap)   mode_flap "${2:-60}" ;;
    rpc)    mode_rpc "${2:-20}" ;;
    paths)  mode_paths "${2:-10}" ;;
    settle) mode_settle "${2:-10}" ;;
    all)
        say "==== ace-stability-test all ===="
        mode_flap 30
        mode_rpc 20
        mode_paths 10
        mode_settle 10
        say "==== done — see ${LOG} ===="
        ;;
    *)
        echo "Usage: $0 {flap [s]|rpc [n]|paths [n]|settle [n]|all}" >&2
        exit 1
        ;;
esac

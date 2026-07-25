#!/bin/sh
# Lightweight rear-AMS USB watcher for CosmOS / Centauri.
# Manual start only — do NOT install as a boot service (112MB RAM).
#
# Usage:
#   /user-resource/ace-addon/ace-usb-watch.sh          # log every 5s
#   /user-resource/ace-addon/ace-usb-watch.sh 10       # log every 10s
#   INTERVAL=10 LOG=/tmp/ace-usb.log ./ace-usb-watch.sh
#
# Stop with Ctrl-C or: kill $(cat /var/run/ace-usb-watch.pid)

set -eu

INTERVAL="${1:-${INTERVAL:-5}}"
LOG="${LOG:-/board-resource/ace-usb.log}"
PIDFILE="${PIDFILE:-/var/run/ace-usb-watch.pid}"
ACE_VID="${ACE_VID:-28e9}"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
echo $$ > "$PIDFILE" 2>/dev/null || true

log_line() {
    # BusyBox date often supports this form.
    ts="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date)"
    printf '%s %s\n' "$ts" "$*" >> "$LOG"
}

trap 'rm -f "$PIDFILE" 2>/dev/null || true; exit 0' INT TERM

log_line "ace-usb-watch start interval=${INTERVAL}s log=${LOG}"

prev_ace="?"
prev_ttys="?"

while true; do
    ace_lines="$(lsusb 2>/dev/null | grep -i "$ACE_VID" || true)"
    if [ -n "$ace_lines" ]; then
        ace_state="present"
        ace_detail="$(printf '%s' "$ace_lines" | tr '\n' ';' | sed 's/;$//')"
    else
        ace_state="absent"
        ace_detail="no ${ACE_VID} device"
    fi

    ttys=""
    for node in /dev/ttyACM* /dev/ttyUSB*; do
        if [ -e "$node" ]; then
            if [ -n "$ttys" ]; then
                ttys="${ttys} ${node}"
            else
                ttys="$node"
            fi
        fi
    done
    [ -n "$ttys" ] || ttys="none"

    dmesg_hit="$(dmesg 2>/dev/null | grep -iE 'error -71|error -32|USB disconnect|cdc_acm|28e9|GDMicro' | tail -n 3 | tr '\n' '|' | sed 's/|$//')"
    [ -n "$dmesg_hit" ] || dmesg_hit="-"

    # Always log on state change; otherwise a heartbeat line every interval.
    if [ "$ace_state" != "$prev_ace" ] || [ "$ttys" != "$prev_ttys" ]; then
        log_line "CHANGE ace=${ace_state} detail=${ace_detail} ttys=${ttys}"
        log_line "DMESG ${dmesg_hit}"
        prev_ace="$ace_state"
        prev_ttys="$ttys"
    else
        log_line "OK ace=${ace_state} ttys=${ttys}"
    fi

    sleep "$INTERVAL"
done

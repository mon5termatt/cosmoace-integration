#!/bin/sh
# CosmoACE keep-alive poller.
#
# The ACE Pro drops its USB link ~3.5s after the last complete frame it
# received (comms watchdog) and re-enumerates. That kills feed assist
# mid-print and makes the next command fail with an I/O error. Anycubic's
# own firmware polls constantly; we only talk to the ACE when a macro runs,
# so something has to keep the link warm.
#
# This is deliberately a shell loop, not a Python service: busybox sh costs
# a few hundred KB, a Python interpreter costs ~5MB, and this board has
# 112MB total. It writes one pre-built get_status frame per port and drains
# the reply without parsing it (leaving unread CDC replies can wedge the
# ACE after a few minutes).
#
# Coordination with commands: ace-addon.py opens the port with an exclusive
# flock, and so does this poller, so the two can never interleave bytes in
# the middle of a frame. If a command holds the port, this tick is skipped
# (that command is feeding the watchdog itself anyway).
#
# COSMOS busybox has no `timeout` applet — never call it here. A missing
# timeout made every tick a silent no-op and the ACE fell off USB every ~3.5s.

# One process only. Reinstall used to stack extra /bin/sh copies because
# the init pidfile could not tell this loop from any other shell.
LOCKFILE="${ACE_KEEPALIVE_LOCK:-/var/run/ace-keepalive.lock}"
PIDFILE="${ACE_KEEPALIVE_PID:-/var/run/ace-keepalive.pid}"
exec 9>"$LOCKFILE"
flock -n 9 || exit 0
echo $$ > "$PIDFILE"

INTERVAL="${ACE_KEEPALIVE_INTERVAL:-2}"
BAUD=115200
EVENT_LOG="${ACE_USB_EVENT_LOG:-/user-resource/ace-addon/usb-events.log}"

# Pre-built frame: 0xFF 0xAA | len | {"id":0,"method":"get_status"} | CRC16
# MCRF4XX | 0xFE. Octal escapes so busybox printf emits it byte for byte
# (it contains a NUL). Regenerate if the payload ever changes.
FRAME='\377\252\036\000\173\042\151\144\042\072\060\054\042\155\145\164\150\157\144\042\072\042\147\145\164\137\163\164\141\164\165\163\042\175\311\072\376'

SYSFS_USB="${ACE_SYSFS_USB:-/sys/bus/usb/devices}"

log_usb_event() {
    ts=$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "?")
    up=$(cut -d. -f1 /proc/uptime 2>/dev/null || echo "?")
    echo "$ts up=${up}s $*" >> "$EVENT_LOG" 2>/dev/null || true
}

usb_stay_awake() {
    d=$1
    n=0
    while [ -n "$d" ] && [ -f "${d}/power/control" ] && [ "$n" -lt 6 ]; do
        echo on > "${d}/power/control" 2>/dev/null || true
        base=$(basename "$d")
        case "$base" in
            usb[0-9]*) break ;;
        esac
        d=$(cd "$d/.." 2>/dev/null && pwd) || break
        n=$((n + 1))
    done
}

LAST_PORTS="__unset__"
log_usb_event "keepalive_start pid=$$"

while :; do
    CUR_PORTS=""
    for dev in "$SYSFS_USB"/*/; do
        [ -f "${dev}product" ] || continue
        read -r product < "${dev}product" 2>/dev/null || continue
        case "$product" in
            *ACE*) ;;
            *) continue ;;
        esac
        usb_stay_awake "${dev%/}"
        for tty in "$dev"*/tty/tty*; do
            [ -e "$tty" ] || continue
            port="/dev/${tty##*/}"
            [ -c "$port" ] || continue
            CUR_PORTS="${CUR_PORTS}${port} "
            # min 0 time 0: dd must not block if the ACE has not replied yet.
            flock -n "$port" -c \
                "stty -F $port $BAUD raw -echo min 0 time 0 clocal cread 2>/dev/null; printf '$FRAME' > $port; dd if=$port of=/dev/null bs=4096 count=4 2>/dev/null" \
                2>/dev/null || true
        done
    done
    if [ "$LAST_PORTS" = "__unset__" ]; then
        log_usb_event "ACE_BASELINE ports='${CUR_PORTS}'"
    elif [ "$CUR_PORTS" != "$LAST_PORTS" ]; then
        if [ -z "$CUR_PORTS" ]; then
            log_usb_event "ACE_DISCONNECT was='${LAST_PORTS}'"
        elif [ -z "$LAST_PORTS" ]; then
            log_usb_event "ACE_CONNECT now='${CUR_PORTS}'"
        else
            log_usb_event "ACE_PORTS_CHANGE was='${LAST_PORTS}' now='${CUR_PORTS}'"
        fi
    fi
    LAST_PORTS="$CUR_PORTS"
    sleep "$INTERVAL"
done

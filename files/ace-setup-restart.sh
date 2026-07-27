#!/bin/sh
# Schedule a full Klipper service restart without blocking the calling gcode.
# Used by the ACE Initial Setup wizard after writing managed hub/hub-less config.
set -eu
LOG=/tmp/ace-setup-restart.log
(
  sleep 2
  if command -v service >/dev/null 2>&1; then
    service klipper restart
  elif command -v systemctl >/dev/null 2>&1; then
    systemctl restart klipper
  else
    echo "No service/systemctl to restart klipper" >&2
    exit 1
  fi
) >"$LOG" 2>&1 &
echo "ACE setup: Klipper restart scheduled (log $LOG)"

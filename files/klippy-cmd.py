#!/usr/bin/env python3
"""Send one gcode command to Klipper via its API unix socket and wait for the reply.

Usage: klippy-cmd.py "FIRMWARE_RESTART" [socket_path]

Kept as a tiny, dependency-free helper for CosmOS where Moonraker only exposes
a unix socket and RUN_SHELL/HTTP paths are awkward from the shell.
"""
import json
import socket
import sys
import time

SOCK = sys.argv[2] if len(sys.argv) > 2 else "/run/klippy.sock"
script = sys.argv[1] if len(sys.argv) > 1 else "FIRMWARE_RESTART"

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(10.0)
s.connect(SOCK)
# "info" reports Klipper's ready/shutdown state; anything else is run as gcode.
if script == "info":
    req = {"id": 1, "method": "info"}
else:
    req = {"id": 1, "method": "gcode/script", "params": {"script": script}}
s.sendall(json.dumps(req).encode() + b"\x03")

buf = b""
deadline = time.time() + 8.0
try:
    while time.time() < deadline:
        try:
            chunk = s.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        if b"\x03" in chunk:
            break
except Exception as exc:  # noqa: BLE001
    print(f"recv error: {exc}")

for part in buf.split(b"\x03"):
    part = part.strip()
    if not part:
        continue
    try:
        msg = json.loads(part)
    except Exception:
        continue
    if msg.get("id") == 1:
        print(json.dumps(msg))
s.close()

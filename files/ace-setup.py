#!/usr/bin/env python3
"""CosmoACE first-install setup helper.

Persists wizard completion/resume markers under /user-resource/ace-addon/,
writes the managed hub / hub-less hardware config, updates variable_sensor_name
in ace-addon.cfg, and can queue a gcode continuation through klippy.sock after
a Klipper restart.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ADDON_DIR = Path("/user-resource/ace-addon")
COMPLETE_MARKER = ADDON_DIR / "setup_complete"
RESUME_FILE = ADDON_DIR / "setup_resume.gcode"
STATE_FILE = ADDON_DIR / "setup_state.json"
MODE_FILE = ADDON_DIR / "setup_hub_mode"  # "hub" | "hubless"
BACKUP_DIR = ADDON_DIR / "setup-backups"

KLIPPER_CONFIG_DIR = Path("/etc/klipper/config")
HARDWARE_CFG = KLIPPER_CONFIG_DIR / "ace-hardware.cfg"
CANVAS_CFG = KLIPPER_CONFIG_DIR / "canvas.cfg"
MACROS_CFG = KLIPPER_CONFIG_DIR / "ace-addon.cfg"
PRINTER_CFG = KLIPPER_CONFIG_DIR / "printer.cfg"
KLIPPY_SOCK = Path("/run/klippy.sock")


def configure_paths(addon_dir=None, config_dir=None, sock=None):
    """Override filesystem roots (offline tests / alternate installs)."""
    global ADDON_DIR, COMPLETE_MARKER, RESUME_FILE, STATE_FILE, MODE_FILE, BACKUP_DIR
    global KLIPPER_CONFIG_DIR, HARDWARE_CFG, CANVAS_CFG, MACROS_CFG, PRINTER_CFG, KLIPPY_SOCK
    if addon_dir is not None:
        ADDON_DIR = Path(addon_dir)
        COMPLETE_MARKER = ADDON_DIR / "setup_complete"
        RESUME_FILE = ADDON_DIR / "setup_resume.gcode"
        STATE_FILE = ADDON_DIR / "setup_state.json"
        MODE_FILE = ADDON_DIR / "setup_hub_mode"
        BACKUP_DIR = ADDON_DIR / "setup-backups"
    if config_dir is not None:
        KLIPPER_CONFIG_DIR = Path(config_dir)
        HARDWARE_CFG = KLIPPER_CONFIG_DIR / "ace-hardware.cfg"
        CANVAS_CFG = KLIPPER_CONFIG_DIR / "canvas.cfg"
        MACROS_CFG = KLIPPER_CONFIG_DIR / "ace-addon.cfg"
        PRINTER_CFG = KLIPPER_CONFIG_DIR / "printer.cfg"
    if sock is not None:
        KLIPPY_SOCK = Path(sock)

MANAGED_TAG = "Managed by CosmoACE setup"
INCLUDE_LINE = "[include ace-hardware.cfg]"
CANVAS_INCLUDE_LINE = "[include canvas.cfg]"
MACROS_INCLUDE_LINE = "[include ace-addon.cfg]"

HUB_SENSOR_NAME = "HUB"

HUB_SECTION = """# mode: hub
# Hub sensor at the 4-way merge point (mainboard PC0).
[filament_switch_sensor {name}]
switch_pin: ^PC0
pause_on_runout: False
event_delay: 0.2
debounce_delay: 0.02
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=RUNOUT
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=INSERT
""".format(
    name=HUB_SENSOR_NAME
)

HUBLESS_MODE_SECTION = """# mode: hubless
# No hub filament_switch_sensor — lane-to-hub tests are unavailable.
# Set variable_sensor_name to "" in ace-addon.cfg (done by this helper).
"""

# Toolhead-side hardware is identical in hub and hub-less mode.
TOOLHEAD_SECTION = """
# Toolhead filament sensor (hotend:PB2) — primary sensor for ACE load/unload.
# ACE macros drive this during toolchange, so pause_on_runout must stay False.
[filament_switch_sensor toolhead_runout_sensor]
pause_on_runout: False
switch_pin: !hotend:PB2
smart: False
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_RUNOUT
immediate_runout_gcode:
  RESPOND TYPE=echo MSG="Filament has ran out!"
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_INSERT
  RESPOND TYPE=echo MSG="Filament has reached the toolhead"

[gcode_button toolhead_front_cover_detection]
pin: hotend:PC4
press_gcode:
  RESPOND TYPE=echo MSG="The front fell off."
  RESPOND TYPE=echo MSG="That's not very typical. I'd like to make that point."
release_gcode:
  RESPOND TYPE=echo MSG="Front cover has been re-attached"

[gcode_button toolhead_cutter_detection]
pin: !hotend:PC5
press_gcode:
  RESPOND TYPE=echo MSG="Toolhead cutter has been engaged"
release_gcode:
  RESPOND TYPE=echo MSG="Toolhead cutter has been disengaged"

# Feeding pressure / tangle switch (hotend:PB0). Only present on the special
# toolhead hub, which this setup does not use. No ACE macro depends on it.
# [gcode_button toolhead_feeding_pressure_detection]
# pin: !hotend:PB0
# press_gcode:
#   RESPOND TYPE=echo MSG="Filament tangle detected!"
# release_gcode:
#   RESPOND TYPE=echo MSG="Filament tangle has been resolved"
"""

_MANAGED_HEADER = f"# {MANAGED_TAG}\n# Do not edit — rewritten by ACE_INITIAL_SETUP.\n"

# Standalone Canvas toolhead config (no ACE). Written on uninstall when
# KEEP_CANVAS=1, or by hand. ACE setup disables this include while ACE is active.
CANVAS_TOOLHEAD_HEADER = (
    "# Canvas toolhead (runout + cutter + front cover)\n"
    "# Safe to edit. ACE_INITIAL_SETUP disables this include while ACE is installed.\n"
)

CANVAS_TOOLHEAD_SECTION = """
# Toolhead filament sensor (hotend:PB2) — Canvas toolhead, no ACE.
[filament_switch_sensor toolhead_runout_sensor]
pause_on_runout: True
switch_pin: !hotend:PB2
smart: False
runout_gcode:
  RESPOND TYPE=echo MSG="Filament has ran out!"
insert_gcode:
  RESPOND TYPE=echo MSG="Filament has reached the toolhead"

[gcode_button toolhead_front_cover_detection]
pin: hotend:PC4
press_gcode:
  RESPOND TYPE=echo MSG="The front fell off."
  RESPOND TYPE=echo MSG="That's not very typical. I'd like to make that point."
release_gcode:
  RESPOND TYPE=echo MSG="Front cover has been re-attached"

[gcode_button toolhead_cutter_detection]
pin: !hotend:PC5
press_gcode:
  RESPOND TYPE=echo MSG="Toolhead cutter has been engaged"
release_gcode:
  RESPOND TYPE=echo MSG="Toolhead cutter has been disengaged"
"""

HUB_SENSOR_SECTION = _MANAGED_HEADER + HUB_SECTION + TOOLHEAD_SECTION
HUBLESS_SECTION = _MANAGED_HEADER + HUBLESS_MODE_SECTION + TOOLHEAD_SECTION
CANVAS_TOOLHEAD_ONLY_SECTION = CANVAS_TOOLHEAD_HEADER + CANVAS_TOOLHEAD_SECTION

# Sections the managed file now owns. Any active copy left in printer.cfg is a
# duplicate and must be commented out, or Klipper refuses to start.
MANAGED_SECTION_NAMES = (
    r"filament_switch_sensor (?:HUB|runout|toolhead_runout_sensor)",
    r"gcode_button toolhead_front_cover_detection",
    r"gcode_button toolhead_cutter_detection",
    r"gcode_button toolhead_feeding_pressure_detection",
)
MANAGED_SECTION_RE = re.compile(
    # Active (uncommented) managed sections only. Stop at the next [section].
    # Do not use a "#?"-tolerant stop pattern — that can skip real sections and
    # swallow unrelated/SAVE_CONFIG content.
    r"(?ms)^(\[(?:"
    + "|".join(MANAGED_SECTION_NAMES)
    + r")\][^\n]*\n(?:(?!^\[).*\n)*)"
)
SENSOR_NAME_RE = re.compile(
    r'(?m)^(variable_sensor_name:\s*)(?:"[^"]*"|\'[^\']*\'|\S+)'
)
INCLUDE_RE = re.compile(r"(?m)^\[include\s+ace-hardware\.cfg\]\s*$")
CANVAS_INCLUDE_RE = re.compile(r"(?m)^\[include\s+canvas\.cfg\]\s*$")
MACROS_INCLUDE_RE = re.compile(r"(?m)^\[include\s+ace-addon\.cfg\]\s*$")


def _ensure_addon_dir() -> None:
    ADDON_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _backup(path: Path) -> Optional[Path]:
    if not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, dest)
    print(f"Backed up {path} -> {dest}")
    return dest


def is_complete() -> bool:
    return COMPLETE_MARKER.is_file()


def mark_complete() -> None:
    _ensure_addon_dir()
    COMPLETE_MARKER.write_text(
        time.strftime("%Y-%m-%dT%H:%M:%SZ\n"), encoding="utf-8"
    )
    if RESUME_FILE.exists():
        RESUME_FILE.unlink()
    _write_state({"stage": "complete", "completed_at": COMPLETE_MARKER.read_text().strip()})
    print(f"Marked setup complete: {COMPLETE_MARKER}")


def clear_complete() -> None:
    if COMPLETE_MARKER.exists():
        COMPLETE_MARKER.unlink()
        print(f"Cleared {COMPLETE_MARKER}")
    else:
        print("setup_complete already absent")


def _write_state(data: Dict[str, Any]) -> None:
    _ensure_addon_dir()
    existing = {}  # type: Dict[str, Any]
    if STATE_FILE.is_file():
        try:
            existing = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing.update(data)
    existing["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    STATE_FILE.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def status() -> Dict[str, Any]:
    mode = ""
    if MODE_FILE.is_file():
        mode = MODE_FILE.read_text(encoding="utf-8").strip()
    state = {}
    if STATE_FILE.is_file():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            state = {"error": str(exc)}
    info = {
        "complete": is_complete(),
        "complete_marker": str(COMPLETE_MARKER),
        "hub_mode": mode,
        "resume_pending": RESUME_FILE.is_file(),
        "resume_file": str(RESUME_FILE) if RESUME_FILE.is_file() else "",
        "hardware_cfg": str(HARDWARE_CFG),
        "hardware_exists": HARDWARE_CFG.is_file(),
        "state": state,
    }
    print(json.dumps(info, indent=2))
    return info


def queue_resume(script: str) -> None:
    _ensure_addon_dir()
    script = script.strip()
    if not script:
        raise SystemExit("queue_resume requires a gcode script")
    RESUME_FILE.write_text(script + "\n", encoding="utf-8")
    _write_state({"stage": "resume_queued", "resume": script})
    print(f"Queued resume: {script!r} -> {RESUME_FILE}")


def _klippy_request(method, params=None, timeout=10.0):
    # type: (str, Optional[dict], float) -> dict
    req = {"id": 1, "method": method}  # type: Dict[str, Any]
    if params is not None:
        req["params"] = params
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(KLIPPY_SOCK))
        sock.sendall(json.dumps(req).encode() + b"\x03")
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if b"\x03" in chunk:
                break
    finally:
        sock.close()
    for part in buf.split(b"\x03"):
        part = part.strip()
        if not part:
            continue
        try:
            msg = json.loads(part)
        except Exception:
            continue
        if msg.get("id") == 1:
            return msg
    return {}


def wait_klippy_ready(timeout_s=90.0):
    # type: (float) -> bool
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not KLIPPY_SOCK.exists():
            time.sleep(1.0)
            continue
        try:
            msg = _klippy_request("info", timeout=3.0)
        except OSError:
            time.sleep(1.0)
            continue
        result = msg.get("result") or {}
        state = str(result.get("state", "")).lower()
        if state == "ready":
            return True
        time.sleep(1.0)
    return False


def send_gcode(script, timeout=30.0):
    # type: (str, float) -> dict
    return _klippy_request("gcode/script", {"script": script}, timeout=timeout)


def consume_resume() -> int:
    if not RESUME_FILE.is_file():
        print("No resume file")
        return 0
    script = RESUME_FILE.read_text(encoding="utf-8").strip()
    RESUME_FILE.unlink()
    if not script:
        return 0
    print(f"Consuming resume: {script}")
    if not wait_klippy_ready(90.0):
        print("Klipper not ready; re-queueing resume", file=sys.stderr)
        queue_resume(script)
        return 1
    # Extra settle after ready (FIRMWARE/service restart recovery window).
    time.sleep(5.0)
    msg = send_gcode(script)
    if msg.get("error"):
        print(f"Resume gcode error: {msg}", file=sys.stderr)
        return 1
    print(f"Resume sent OK: {json.dumps(msg)}")
    _write_state({"stage": "resumed", "resume": script})
    return 0


def boot() -> int:
    """Post-start hook: consume resume, else offer first-run wizard."""
    _ensure_addon_dir()
    if not wait_klippy_ready(90.0):
        print("boot: Klipper not ready", file=sys.stderr)
        return 1
    time.sleep(3.0)

    if RESUME_FILE.is_file():
        return consume_resume()

    if is_complete():
        print("boot: setup already complete")
        return 0

    print("boot: launching ACE_INITIAL_SETUP")
    msg = send_gcode("ACE_INITIAL_SETUP")
    if msg.get("error"):
        print(f"boot launch error: {msg}", file=sys.stderr)
        return 1
    return 0


def _set_sensor_name_in_macros(name: str) -> None:
    if not MACROS_CFG.is_file():
        raise SystemExit(f"Missing macros config: {MACROS_CFG}")
    text = MACROS_CFG.read_text(encoding="utf-8", errors="replace")
    if not SENSOR_NAME_RE.search(text):
        raise SystemExit(f"variable_sensor_name not found in {MACROS_CFG}")
    _backup(MACROS_CFG)
    quoted = json.dumps(name)  # produces "" or "HUB"
    new_text, count = SENSOR_NAME_RE.subn(rf"\1{quoted}", text, count=1)
    if count != 1:
        raise SystemExit("Failed to update variable_sensor_name")
    MACROS_CFG.write_text(new_text, encoding="utf-8")
    print(f"Set variable_sensor_name -> {quoted} in {MACROS_CFG}")


def _ensure_include(include_line: str, include_re: "re.Pattern") -> None:
    if not PRINTER_CFG.is_file():
        print(f"Warning: {PRINTER_CFG} missing; skip include", file=sys.stderr)
        return
    text = PRINTER_CFG.read_text(encoding="utf-8", errors="replace")
    if include_re.search(text):
        print(f"Include already present in {PRINTER_CFG}: {include_line}")
        return
    _backup(PRINTER_CFG)
    # Insert after the first [include ...] block if present, else at top.
    lines = text.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("[include"):
            insert_at = i + 1
    addition = f"\n# {MANAGED_TAG}\n{include_line}\n"
    lines.insert(insert_at, addition)
    PRINTER_CFG.write_text("".join(lines), encoding="utf-8")
    print(f"Added {include_line} to {PRINTER_CFG}")


def _remove_include(include_re: "re.Pattern", label: str) -> None:
    if not PRINTER_CFG.is_file():
        return
    text = PRINTER_CFG.read_text(encoding="utf-8", errors="replace")
    if not include_re.search(text):
        return
    _backup(PRINTER_CFG)
    lines = text.splitlines(keepends=True)
    out = []  # type: List[str]
    for line in lines:
        if include_re.match(line):
            if out and MANAGED_TAG in out[-1]:
                out.pop()
            continue
        out.append(line)
    PRINTER_CFG.write_text("".join(out), encoding="utf-8")
    print(f"Removed {label} include from {PRINTER_CFG}")


def _remove_legacy_readonly_macros_link() -> None:
    """CosmOS wipes klipper-readonly overlay on flash / readonly-config-reset."""
    link = KLIPPER_CONFIG_DIR / "klipper-readonly" / "ace-addon.cfg"
    if link.is_symlink() or link.is_file():
        link.unlink()
        print(f"Removed legacy wipe-prone path: {link}")


def _ensure_hardware_include() -> None:
    _ensure_include(INCLUDE_LINE, INCLUDE_RE)


def _ensure_canvas_include() -> None:
    _ensure_include(CANVAS_INCLUDE_LINE, CANVAS_INCLUDE_RE)


def _disable_canvas_include() -> None:
    """Stop loading canvas.cfg so ACE-owned toolhead sections are not duplicated."""
    if PRINTER_CFG.is_file():
        _remove_include(CANVAS_INCLUDE_RE, "canvas")


def ensure_macros_include() -> None:
    """Durable load path: printer.cfg include, not a klipper-readonly symlink."""
    _ensure_addon_dir()
    _ensure_include(MACROS_INCLUDE_LINE, MACROS_INCLUDE_RE)
    _remove_legacy_readonly_macros_link()


def remove_macros_include() -> None:
    _ensure_addon_dir()
    _remove_include(MACROS_INCLUDE_RE, "ace-addon")
    _remove_legacy_readonly_macros_link()


def _comment_managed_sections_in_printer_cfg() -> None:
    """Comment out any active section that ace-hardware.cfg now owns."""
    if not PRINTER_CFG.is_file():
        return
    text = PRINTER_CFG.read_text(encoding="utf-8", errors="replace")

    def comment_block(match: "re.Match") -> str:
        block = match.group(1)
        active = [
            ln
            for ln in block.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
        if not active:
            return block
        fixed = [
            ln if (not ln.strip() or ln.lstrip().startswith("#")) else "# " + ln
            for ln in block.splitlines(keepends=True)
        ]
        return f"# {MANAGED_TAG}: moved to ace-hardware.cfg\n" + "".join(fixed)

    new_text = MANAGED_SECTION_RE.sub(comment_block, text)
    if new_text == text:
        return
    _backup(PRINTER_CFG)
    PRINTER_CFG.write_text(new_text, encoding="utf-8")
    print(f"Commented duplicate managed sections in {PRINTER_CFG}")


def write_hub_config() -> None:
    _ensure_addon_dir()
    _backup(HARDWARE_CFG)
    HARDWARE_CFG.write_text(HUB_SENSOR_SECTION, encoding="utf-8")
    print(f"Wrote hub config: {HARDWARE_CFG}")
    _disable_canvas_include()
    _ensure_hardware_include()
    _comment_managed_sections_in_printer_cfg()
    _set_sensor_name_in_macros(HUB_SENSOR_NAME)
    MODE_FILE.write_text("hub\n", encoding="utf-8")
    _write_state({"stage": "hub_config_written", "hub_mode": "hub"})


def write_hubless_config() -> None:
    _ensure_addon_dir()
    _backup(HARDWARE_CFG)
    HARDWARE_CFG.write_text(HUBLESS_SECTION, encoding="utf-8")
    print(f"Wrote hub-less config: {HARDWARE_CFG}")
    _disable_canvas_include()
    _ensure_hardware_include()
    # Hub-less still owns the toolhead hardware, so printer.cfg duplicates of any
    # managed section must be commented out here too.
    _comment_managed_sections_in_printer_cfg()
    _set_sensor_name_in_macros("")
    MODE_FILE.write_text("hubless\n", encoding="utf-8")
    _write_state({"stage": "hubless_config_written", "hub_mode": "hubless"})


def apply_hub(restart: bool = False) -> int:
    write_hub_config()
    queue_resume("_ACE_SETUP_AFTER_HUB_RESTART")
    if restart:
        print("Requesting service klipper restart is left to the macro/install path")
    return 0


def apply_hubless(restart: bool = False) -> int:
    write_hubless_config()
    queue_resume("_ACE_SETUP_AFTER_HUBLESS_RESTART")
    if restart:
        print("Requesting service klipper restart is left to the macro/install path")
    return 0


def remove_managed_hardware(
    restore_sensor_name=HUB_SENSOR_NAME,
    keep_canvas_toolhead=False,
):
    # type: (Optional[str], bool) -> int
    """Uninstall helper: remove ACE-managed hardware, optionally keep Canvas sensors."""
    if keep_canvas_toolhead:
        _ensure_addon_dir()
        if HARDWARE_CFG.is_file():
            _backup(HARDWARE_CFG)
            HARDWARE_CFG.unlink()
            print(f"Removed {HARDWARE_CFG}")
        if CANVAS_CFG.is_file():
            _backup(CANVAS_CFG)
        CANVAS_CFG.write_text(CANVAS_TOOLHEAD_ONLY_SECTION, encoding="utf-8")
        print(f"Wrote Canvas toolhead config (no ACE): {CANVAS_CFG}")
        if PRINTER_CFG.is_file():
            _remove_include(INCLUDE_RE, "ace-hardware")
        _ensure_canvas_include()
        _comment_managed_sections_in_printer_cfg()
    else:
        if HARDWARE_CFG.is_file():
            _backup(HARDWARE_CFG)
            HARDWARE_CFG.unlink()
            print(f"Removed {HARDWARE_CFG}")
        if PRINTER_CFG.is_file():
            _remove_include(INCLUDE_RE, "ace-hardware")
        # Full remove: do not delete canvas.cfg (user-owned), but leave include alone
        # unless we added it — only strip ace-hardware here.

    if restore_sensor_name is not None and MACROS_CFG.is_file():
        try:
            _set_sensor_name_in_macros(restore_sensor_name)
        except SystemExit as exc:
            print(f"Warning: {exc}", file=sys.stderr)
    for path in (COMPLETE_MARKER, RESUME_FILE, MODE_FILE, STATE_FILE):
        if path.exists():
            path.unlink()
            print(f"Removed {path}")
    return 0


def main(argv=None):
    # type: (Optional[List[str]]) -> int
    parser = argparse.ArgumentParser(description="CosmoACE setup helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Print setup status JSON")
    sub.add_parser("is_complete", help="Exit 0 if setup_complete exists")
    sub.add_parser("mark_complete", help="Write setup_complete marker")
    sub.add_parser("clear_complete", help="Remove setup_complete marker")
    sub.add_parser("boot", help="Post-start: resume or first-run prompt")
    sub.add_parser("consume_resume", help="Send queued resume gcode")

    p_queue = sub.add_parser("queue_resume", help="Queue gcode after next boot/restart")
    p_queue.add_argument("script", help="G-code script to run")

    sub.add_parser("write_hub_config", help="Write managed hub hardware config")
    sub.add_parser("write_hubless_config", help="Write managed hub-less config")

    p_hub = sub.add_parser("apply_hub", help="Hub mode + queue resume after restart")
    p_hub.add_argument("--restart", action="store_true")

    p_hubless = sub.add_parser("apply_hubless", help="Hub-less mode + queue resume")
    p_hubless.add_argument("--restart", action="store_true")

    p_rm = sub.add_parser("remove_managed", help="Remove managed hardware (uninstall)")
    p_rm.add_argument(
        "--restore-sensor-name",
        default=HUB_SENSOR_NAME,
        help=f'Restore variable_sensor_name (default "{HUB_SENSOR_NAME}"; use "" to clear)',
    )
    p_rm.add_argument(
        "--keep-canvas-toolhead",
        action="store_true",
        help="Leave toolhead runout/cutter/front-cover in canvas.cfg without ACE hooks",
    )

    p_set = sub.add_parser("set_sensor_name", help="Update variable_sensor_name only")
    p_set.add_argument("name", help='Sensor name, or "" for hub-less')

    sub.add_parser(
        "ensure_macros_include",
        help="Add [include ace-addon.cfg] to printer.cfg; remove legacy klipper-readonly symlink",
    )
    sub.add_parser(
        "remove_macros_include",
        help="Remove [include ace-addon.cfg] and any legacy klipper-readonly symlink",
    )

    args = parser.parse_args(argv)

    if args.cmd == "status":
        status()
        return 0
    if args.cmd == "is_complete":
        return 0 if is_complete() else 1
    if args.cmd == "mark_complete":
        mark_complete()
        return 0
    if args.cmd == "clear_complete":
        clear_complete()
        return 0
    if args.cmd == "boot":
        return boot()
    if args.cmd == "consume_resume":
        return consume_resume()
    if args.cmd == "queue_resume":
        queue_resume(args.script)
        return 0
    if args.cmd == "write_hub_config":
        write_hub_config()
        return 0
    if args.cmd == "write_hubless_config":
        write_hubless_config()
        return 0
    if args.cmd == "apply_hub":
        return apply_hub(restart=args.restart)
    if args.cmd == "apply_hubless":
        return apply_hubless(restart=args.restart)
    if args.cmd == "remove_managed":
        name = args.restore_sensor_name
        return remove_managed_hardware(
            restore_sensor_name=name,
            keep_canvas_toolhead=bool(args.keep_canvas_toolhead),
        )
    if args.cmd == "set_sensor_name":
        _set_sensor_name_in_macros(args.name)
        return 0
    if args.cmd == "ensure_macros_include":
        ensure_macros_include()
        return 0
    if args.cmd == "remove_macros_include":
        remove_macros_include()
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

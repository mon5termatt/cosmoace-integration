"""Offline validation for the CosmoACE Klipper macros.

Klipper builds its Jinja environment with '{' / '}' as the variable delimiters, so
expressions like {slot} must be validated with those delimiters rather than the
Jinja defaults. Anything that only checks {% %} blocks silently skips most of the
template.

Usage:
    python tests/check_macros.py                     # compile + render every case
    python tests/check_macros.py --dump _ACE_ORCA_TOOLCHANGE
"""

import configparser
import os
import sys

import jinja2

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MACROS = os.path.join(REPO_ROOT, "files", "ace_macros.cfg")
PRINTER_CFG = os.path.join(REPO_ROOT, "printer.cfg")

GCODE_KEYS = (
    "gcode",
    "press_gcode",
    "release_gcode",
    "runout_gcode",
    "insert_gcode",
    "immediate_runout_gcode",
)

HUB_SENSOR_OBJECT = "filament_switch_sensor runout"
TOOLHEAD_SENSOR_OBJECT = "filament_switch_sensor toolhead_runout_sensor"


def klipper_env():
    return jinja2.Environment("{%", "%}", "{", "}", extensions=["jinja2.ext.do"])


def load(path):
    parser = configparser.RawConfigParser(strict=False)
    parser.read(path, encoding="utf-8")
    return parser


def compile_all(path):
    parser = load(path)
    env = klipper_env()
    failures = []
    checked = 0
    for section in parser.sections():
        for key in GCODE_KEYS:
            if not parser.has_option(section, key):
                continue
            template = parser.get(section, key)
            if not template.strip():
                continue
            checked += 1
            try:
                env.parse(template)
            except jinja2.TemplateSyntaxError as exc:
                failures.append(
                    f"[{section}] {key}: line {exc.lineno}: {exc.message}"
                )
    print(f"{os.path.basename(path)}: sections={len(parser.sections())} templates={checked}")
    for failure in failures:
        print("  FAIL", failure)
    return failures


def raise_error(msg):
    raise RuntimeError(msg)


def config_vars():
    """Read _ACE_CONFIG defaults so the harness tracks the real config."""
    parser = load(MACROS)
    section = "gcode_macro _ACE_CONFIG"
    values = {}
    for option in parser.options(section):
        if not option.startswith("variable_"):
            continue
        raw = parser.get(section, option).strip()
        if raw.startswith('"') and raw.endswith('"'):
            value = raw[1:-1]
        else:
            try:
                value = float(raw) if "." in raw else int(raw)
            except ValueError:
                value = raw
        values[option[len("variable_") :]] = value
    return values


def build_printer(toolhead_present=True, hub=1, toolhead=0, hub_present=True):
    printer = {
        "gcode_macro _ACE_CONFIG": config_vars(),
        "gcode_macro _ACE_STATE": {
            "mode": "print",
            "current_slot": 1,
            "pending_slot": 2,
            "last_event": "",
            "last_error": "",
            "sensor_state": hub,
            "toolhead_sensor_state": toolhead,
            "return_x": 0.0,
            "return_y": 0.0,
            "return_z": 0.0,
            "has_return_position": 1,
        },
        "print_stats": {"state": "printing"},
        "pause_resume": {"is_paused": False},
        "toolhead": {"homed_axes": "xyz", "axis_maximum": {"z": 250.0}},
        "gcode_move": {"gcode_position": {"x": 10.0, "y": 10.0, "z": 5.0}},
        "extruder": {"can_extrude": True},
    }
    if hub_present:
        printer[HUB_SENSOR_OBJECT] = {"filament_detected": hub}
    if toolhead_present:
        printer[TOOLHEAD_SENSOR_OBJECT] = {"filament_detected": toolhead}
    return printer


# name, params, toolhead_present, hub_reading, toolhead_reading
CASES = [
    ("_ACE_SENSOR_EVENT", {"EVENT": "TOOLHEAD_RUNOUT"}, True, 1, 0),
    ("_ACE_SENSOR_EVENT", {"EVENT": "TOOLHEAD_INSERT"}, True, 1, 1),
    ("_ACE_SENSOR_EVENT", {"EVENT": "RUNOUT"}, True, 0, 0),
    ("_ACE_SENSOR_EVENT", {"EVENT": "INSERT"}, True, 1, 0),
    ("_ACE_SENSOR_EVENT", {"EVENT": "TOOLHEAD_INSERT"}, False, 1, 0),
    ("_ACE_LOAD_TO_PRINTHEAD", {"SLOT": 2}, True, 1, 0),
    ("_ACE_LOAD_TO_PRINTHEAD", {"SLOT": 2}, False, 1, 0),
    ("_ACE_LOAD_TO_TOOLHEAD", {"SLOT": 2}, True, 1, 0),
    ("_ACE_LOAD_TO_TOOLHEAD", {"SLOT": 2}, True, 1, 1),
    ("_ACE_LOAD_TO_TOOLHEAD", {"SLOT": 9}, True, 1, 0),
    ("_ACE_UNLOAD_FROM_TOOLHEAD", {"SLOT": 1}, True, 1, 1),
    ("_ACE_UNLOAD_FROM_TOOLHEAD", {"SLOT": 1}, True, 1, 0),
    ("_ACE_UNLOAD_FROM_TOOLHEAD", {"SLOT": 1}, False, 1, 0),
    ("_ACE_VERIFY_TOOLHEAD_TRIGGERED", {}, True, 1, 1),
    ("_ACE_VERIFY_TOOLHEAD_TRIGGERED", {}, True, 1, 0),
    ("_ACE_VERIFY_TOOLHEAD_CLEAR", {}, True, 1, 0),
    ("_ACE_VERIFY_TOOLHEAD_CLEAR", {}, True, 1, 1),
    ("ACE_STATUS", {}, True, 1, 1),
    ("ACE_STATUS", {}, False, 1, 0),
    ("_ACE_RESET_STATE", {}, True, 0, 0),
    ("_ACE_RESET_STATE", {}, False, 0, 0),
    ("_ACE_ORCA_START", {"SLOT": 2}, True, 0, 0),
    ("_ACE_ORCA_TOOLCHANGE", {"SLOT": 2}, True, 1, 1),
    ("_ACE_ORCA_END_PRINT", {}, True, 1, 1),
]


def render_cases():
    parser = load(MACROS)
    env = klipper_env()
    failures = []
    for name, params, toolhead_present, hub, toolhead in CASES:
        template = env.from_string(parser.get(f"gcode_macro {name}", "gcode"))
        label = (
            f"{name} params={params} "
            f"toolhead_cfg={'yes' if toolhead_present else 'no'} hub={hub} th={toolhead}"
        )
        try:
            out = template.render(
                params=params,
                rawparams="",
                printer=build_printer(toolhead_present, hub, toolhead),
                action_raise_error=raise_error,
                action_respond_info=lambda m: "",
                action_emergency_stop=lambda m="": "",
            )
        except RuntimeError as exc:
            # An intentional action_raise_error guard, not a template bug.
            print(f"  guard  {label}\n         -> {exc}")
            continue
        except Exception as exc:
            failures.append(f"{label}: {type(exc).__name__}: {exc}")
            print(f"  FAIL   {label}\n         -> {type(exc).__name__}: {exc}")
            continue
        first = next((ln.strip() for ln in out.splitlines() if ln.strip()), "<empty>")
        print(f"  ok     {label}\n         -> {first}")
    return failures


def dump(name):
    parser = load(MACROS)
    env = klipper_env()
    template = env.from_string(parser.get(f"gcode_macro {name}", "gcode"))
    out = template.render(
        params={"SLOT": 2},
        rawparams="",
        printer=build_printer(True, 1, 1),
        action_raise_error=raise_error,
        action_respond_info=lambda m: "",
    )
    for line in out.splitlines():
        if line.strip():
            print(line.strip())
    return 0


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--dump":
        return dump(sys.argv[2])

    failures = []
    for path in (MACROS, PRINTER_CFG):
        if os.path.exists(path):
            failures += compile_all(path)
        else:
            print(f"{os.path.basename(path)}: skipped (not present)")

    print("\nrender:")
    failures += render_cases()

    if failures:
        print(f"\n{len(failures)} failure(s)")
        for failure in failures:
            print("FAIL", failure)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

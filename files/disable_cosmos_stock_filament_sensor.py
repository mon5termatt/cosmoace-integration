#!/usr/bin/env python3
"""Disable CosmOS stock [filament_switch_sensor filament_sensor] in machine.cfg.

That section usually owns PC0 with pause-on-runout behavior that fights ACE
toolchanges and conflicts with the ACE hub sensor on the same pin. CosmoACE
install comments the whole section out (with a backup) when present.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


SECTION_RE = re.compile(
    r"(?ms)^(\[filament_switch_sensor filament_sensor\][^\n]*\n"
    r"(?:(?!^\[).*\n)*)"
)


def disable_stock_filament_sensor(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = SECTION_RE.search(text)
    if not match:
        print(f"No active [filament_switch_sensor filament_sensor] in {path}")
        return 0

    block = match.group(1)
    if block.lstrip().startswith("#"):
        print(f"Stock filament_sensor already commented in {path}")
        return 0

    fixed_lines = []
    for line in block.splitlines(keepends=True):
        if line.strip() == "" or line.lstrip().startswith("#"):
            fixed_lines.append(line)
        else:
            fixed_lines.append("# " + line)
    commented = "".join(fixed_lines)
    header = (
        "# Disabled by CosmoACE install: stock CosmOS filament_sensor fights ACE\n"
        "# toolchanges and conflicts with the hub sensor on PC0. Restore from\n"
        "# machine.cfg.pre-cosmoace.bak if you uninstall ACE.\n"
    )
    new_text = text[: match.start()] + header + commented + text[match.end() :]

    bak = path.with_suffix(path.suffix + ".pre-cosmoace.bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"Backed up {path} -> {bak}")
    path.write_text(new_text, encoding="utf-8")
    print(f"Commented out stock [filament_switch_sensor filament_sensor] in {path}")
    return 1


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/machine.cfg", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"Missing config: {path}", file=sys.stderr)
        return 1
    disable_stock_filament_sensor(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

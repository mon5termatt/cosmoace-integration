# CosmoACE Integration

Connect an **Anycubic ACE Pro** filament changer to an **Elegoo Centauri Carbon**
running CosmOS / OpenCentauri, and print multicolor jobs from OrcaSlicer (or a
PrusaSlicer-style fork).

This project is built specifically for that setup. It is not a generic Klipper
add-on for every printer or slicer.

## What you get

After install, your printer can:

1. Load the filament you picked in the slicer
2. Change colors mid-print (cut, unload, load the next spool, purge, wipe)
3. Clear the line when the print finishes

You need a filament sensor at the toolhead (Canvas-style CC1). A filament hub
with **at least one sensor** at the merge point is strongly recommended: the
hub sensor confirms loads and clears before the long run to the toolhead, so
toolchanges fail fast instead of blindly feeding or retracting a fixed length.
Hub-less / no-sensor setups still work, but they rely on longer search budgets
and blind clears.

Install also starts a low-priority ACE **protocol keepalive** so the rear USB
link does not drop on the ACE’s ~3.6s idle watchdog. Details:
[ACE USB Stability](docs/ACE_USB_STABILITY.md).

## What you need

| Item | Notes |
| --- | --- |
| Elegoo Centauri Carbon | With CosmOS / OpenCentauri installed |
| Anycubic ACE Pro | With its own 24V power brick plugged in |
| ACE signal cable | The ACE’s **4-pin to 6-pin** cable (not a 4-pin to 4-pin cable) |
| SSH access | User `root`, password usually `OpenCentauri` |
| OrcaSlicer (or similar) | Paste the start / toolchange / end macros from the [Orca guide](docs/ORCA_GCODE.md) |

## Quick install

1. Copy this whole folder onto a USB stick and plug it into the printer.
2. SSH in as `root`.
3. Run:

```sh
cd /user-resource/.tmp/cosmoace-integration
chmod +x install.sh uninstall.sh
./install.sh
```

The install script restarts Klipper, waits ~45s for load to settle, then starts
the ACE keepalive service.

4. After the first restart, the **ACE Initial Setup** prompt appears on the
   printer UI (unless a previous install already created
   `/user-resource/ace-addon/setup_complete`). Choose hub or hub-less, then
   follow the lane tests. You can re-run anytime with `ACE_INITIAL_SETUP`.
5. In the printer console, run `ACE_CHECK`. You want a healthy reply (`ok: true`).
6. Set the OrcaSlicer start / toolchange / end gcode from the
   [Orca guide](docs/ORCA_GCODE.md).

To remove CosmoACE later:

```sh
cd /user-resource/.tmp/cosmoace-integration
./uninstall.sh
```

The script asks whether to keep Canvas toolhead runout/cutter hardware after ACE
is gone (writes `/etc/klipper/config/canvas.cfg` and
`[include canvas.cfg]`). For non-interactive uninstalls:
`KEEP_CANVAS=1 ./uninstall.sh`.

If the install script fails on your firmware, see the
[advanced README](README_ADVANCED.md) for a full manual install.

## Cable and rear port

CosmoACE uses the Centauri’s **rear AMS / MMU port**.

- The **6-pin** end of the ACE signal cable goes into the **ACE Pro**.
- The **4-pin** end goes into the Centauri’s **rear chassis port**.
- The ACE keeps its own power brick. Do not feed printer 24V into the ACE.

> [!WARNING]
> A plain 4-pin-to-4-pin cable will not talk to the ACE. You need the ACE’s
> 4-pin-to-6-pin signal cable.

### Board harness change (required once)

Inside the printer, the rear port’s board connector needs a one-time wiring
change so Linux sees the ACE correctly:

1. **Swap the two data wires** (the ones marked DM and DP).
2. **Disconnect and cap the 5V wire** so it cannot short or back-feed.
3. Leave **24V unused** for the ACE.
4. Keep **GND** connected.

Without the data-wire swap, the printer often fails to see the ACE at all
(or shows USB errors).

> [!CAUTION]
> This change is for CosmoACE. A stock Canvas / native AMS unit will **not**
> work on the rear port afterwards. The Canvas draws **24V** through this port
> for its motors, so if you go back to Canvas, either plug in the adapter that
> shipped with your Canvas or re-pin the harness to stock (data wires
> un-swapped, 5V and 24V restored) first.

Pin-by-pin tables, DIY adapters, and front-USB checks are in the
[advanced README](README_ADVANCED.md).

## First checks if something’s wrong

| What you notice | What to try |
| --- | --- |
| ACE LEDs are off | Plug in the ACE’s 24V brick and power it on |
| Printer never “sees” the ACE | Reseat both ends of the signal cable; confirm the board data wires were swapped |
| ACE drops on an exact ~3.6s rhythm | Run `service ace-addon status`; the protocol keepalive must be running |
| ACE drops irregularly while keepalive runs | Check cable strain, ground, and the rear harness / VBUS |
| Macros say the sensor is already triggered | Check hub / toolhead sensor wiring, or `ACE_DISABLE_SENSORS TARGET=hub` if you don’t have a hub |

From the printer console:

- `ACE_CHECK` — quick “is the ACE talking?” test
- `ACE_INITIAL_SETUP` — re-run the hub / lane setup wizard
- After a Klipper restart, wait ~45 seconds before trusting that check

Keepalive, by-id device paths (why not raw `/dev/ttyACM*`), and rear-port notes:
[ACE USB Stability](docs/ACE_USB_STABILITY.md).

## Sensors (printer config)

All ACE hardware sections — the hub sensor, the toolhead filament sensor, and
the toolhead buttons — live in managed
`/etc/klipper/config/ace-hardware.cfg`, written by `ACE_INITIAL_SETUP`. Your
`printer.cfg` only needs `[include ace-hardware.cfg]`, which the wizard adds. If
it finds active copies of those sections in `printer.cfg`, it comments them out,
since Klipper refuses to start on a duplicate section.

The blocks below document what the managed file contains. Only add them by hand
if you are not using the wizard — re-running it overwrites `ace-hardware.cfg`.

### CosmOS stock filament sensor (remove)

CosmOS may ship `[filament_switch_sensor filament_sensor]` in
`klipper-readonly/machine.cfg` on `PC0` with pause-on-runout behavior. That
fights ACE toolchanges and conflicts with the ACE hub sensor on the same pin.
`install.sh` comments that section out automatically (backup:
`machine.cfg.pre-cosmoace.bak`).

CosmOS print macros still *look up* an object named `filament_sensor`. After
removing the stock section, either:

- name your toolhead sensor `filament_sensor` and set
  `variable_toolhead_sensor_name: "filament_sensor"` in `ace-addon.cfg`, or
- keep `toolhead_runout_sensor` and accept that CosmOS START_PRINT filament
  checks need a matching rename/override.

### Toolhead sensor (recommended)

Written into `ace-hardware.cfg` in both hub and hub-less mode. On a post-Canvas
CC1 toolhead it looks like:

```cfg
[filament_switch_sensor toolhead_runout_sensor]
switch_pin: !hotend:PB2
pause_on_runout: False
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_RUNOUT
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_INSERT
```

### Hub sensor (recommended)

Prefer **ACE Initial Setup** (`ACE_INITIAL_SETUP`): answering “Yes, hub installed”
writes managed `/etc/klipper/config/ace-hardware.cfg` (HUB on `^PC0`, plus the
toolhead sensor and buttons), sets `variable_sensor_name: "HUB"`, restarts
Klipper, then walks lanes 1–4 (slow feed to the hub, then retract until clear).

The hub section it writes:

```cfg
[filament_switch_sensor HUB]
switch_pin: ^PC0
pause_on_runout: False
event_delay: 0.2
debounce_delay: 0.02
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=RUNOUT
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=INSERT
```

Important:

- Set `pause_on_runout: False` on both. CosmoACE moves filament past these
  sensors on purpose during a toolchange; Klipper’s own pause would fight that.
- If your sensor names differ, update `variable_sensor_name` and
  `variable_toolhead_sensor_name` in `/etc/klipper/config/ace-addon.cfg`.
- Temporarily silence runout/insert events with `ACE_DISABLE_SENSORS` /
  `ACE_ENABLE_SENSORS` (optional `TARGET=all|hub|toolhead`). Check
  `sensors_enabled` via `ACE_STATUS`.

### No hub sensor (fallback)

Choose **No hub** in ACE Initial Setup, which writes an `ace-hardware.cfg` that
keeps the toolhead hardware but omits the hub section, and sets
`variable_sensor_name: ""`. Do not leave
the section in place with nothing plugged in — a floating wire can look
“always triggered.”

Without a hub sensor, loads search all the way to the toolhead, and unloads
pull a fixed extra length past the merge point. That works, but missed clears
and overruns are harder to catch. Details and panel buttons:
[ACE Macro Reference](docs/ACE_MACROS.md).

## Distances to tune

These live in `/etc/klipper/config/ace-addon.cfg`. With a toolhead sensor,
loading stops when the switch trips, so most values are just “search budgets”
that need to be longer than the real tube path:

| Setting | Default | Plain meaning |
| --- | --- | --- |
| `variable_load_to_toolhead_search_mm` | `900` | Max search from hub sensor → toolhead |
| `variable_load_past_toolhead_mm` | `15` | Extra push to seat filament in the extruder gears |
| `variable_unload_from_toolhead_search_mm` | `200` | Max retract to clear the toolhead switch |
| `variable_load_to_toolhead_full_search_mm` | `2200` | Hub-less: ACE → toolhead in one go |
| `variable_unload_past_hub_mm` | `950` | Hub-less: extra retract past the merge point |

A little too long is usually fine. Too short fails loads or leaves filament
in the hub.

Your printer should already have tray / wipe / pause helpers CosmoACE calls:
`MOVE_TO_TRAY`, `M729`, `PAUSE_BASE`, and `RESUME`.

## More reading

- [Advanced README](README_ADVANCED.md) — pinouts, manual install, TODOs, and detailed specs
- [OrcaSlicer G-Code](docs/ORCA_GCODE.md) — what to paste into the slicer
- [ACE Macro Reference](docs/ACE_MACROS.md) — every macro and config variable
- [ACE USB Stability](docs/ACE_USB_STABILITY.md) — keepalive, by-id pinning, and rear-port notes

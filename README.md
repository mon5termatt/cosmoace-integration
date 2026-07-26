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

You need a filament sensor at the toolhead (Canvas-style CC1). A second sensor
at the filament hub is optional — nice if you have one, not required.

## What you need


| Item                    | Notes                                                                               |
| ----------------------- | ----------------------------------------------------------------------------------- |
| Elegoo Centauri Carbon  | With CosmOS / OpenCentauri installed                                                |
| Anycubic ACE Pro        | With its own 24V power brick plugged in                                             |
| ACE signal cable        | The ACE’s **4-pin to 6-pin** cable (not a 4-pin to 4-pin cable)                     |
| SSH access              | User `root`, password usually `OpenCentauri`                                        |
| OrcaSlicer (or similar) | Paste the start / toolchange / end macros from the [Orca guide](docs/ORCA_GCODE.md) |


Also print and mount the
[filament hub adapter](https://www.printables.com/model/1662192-centauri-carbon-multi-material-filament-hub-4-colo)
so the ACE tubes meet the Centauri’s runout path.

## Quick install

1. Copy this whole folder onto a USB stick and plug it into the printer.
2. SSH in as `root`.
3. Run:

```sh
cd /user-resource/.tmp/cosmoace-integration
chmod +x install.sh uninstall.sh
./install.sh
```

1. Restart Klipper and wait about 45 seconds for it to finish booting:

```sh
service klipper restart
```

1. In the printer console, run `ACE_CHECK`. You want a healthy reply (`ok: true`).
2. Set the OrcaSlicer start / toolchange / end gcode from the
  [Orca guide](docs/ORCA_GCODE.md).

To remove CosmoACE later:

```sh
cd /user-resource/.tmp/cosmoace-integration
./uninstall.sh
```

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
[advanced README](README_ADVANCED.md). Flaky USB behavior is covered in
[ACE USB Stability](docs/ACE_USB_STABILITY.md).

## First checks if something’s wrong


| What you notice                            | What to try                                                                                              |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| ACE LEDs are off                           | Plug in the ACE’s 24V brick and power it on                                                              |
| Printer never “sees” the ACE               | Reseat both ends of the signal cable; confirm the board data wires were swapped                          |
| ACE drops on an exact ~3.6s rhythm | Run `service ace-addon status`; the protocol keepalive must be running |
| ACE drops irregularly while keepalive runs | Check cable strain, ground, and the rear harness / VBUS |
| Macros say the sensor is already triggered | Check hub / toolhead sensor wiring, or disable a hub sensor you don’t have                               |


From the printer console:

- `ACE_CHECK` — quick “is the ACE talking?” test
- After a Klipper restart, wait ~45 seconds before trusting that check

For deeper USB debugging (logs, stability tests, why we pin a stable device
path), see [ACE USB Stability](docs/ACE_USB_STABILITY.md).

## Sensors (printer config)



### Toolhead sensor (recommended)

On a post-Canvas CC1 toolhead, add something like:

```cfg
[filament_switch_sensor toolhead_runout_sensor]
switch_pin: !hotend:PB2
pause_on_runout: False
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_RUNOUT
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_INSERT
```



### Hub sensor (optional)

If you have a sensor at the 4-way merge point:

```cfg
[filament_switch_sensor runout]
switch_pin: PC0
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



### No hub sensor

Remove the hub `[filament_switch_sensor runout]` block entirely (or set
`variable_sensor_name: ""`). Do not leave the section in place with nothing
plugged in — a floating wire can look “always triggered.”

Without a hub sensor, loads search all the way to the toolhead, and unloads
pull a fixed extra length past the merge point. Details and panel buttons:
[ACE Macro Reference](docs/ACE_MACROS.md).

## Distances to tune

These live in `/etc/klipper/config/ace-addon.cfg`. With a toolhead sensor,
loading stops when the switch trips, so most values are just “search budgets”
that need to be longer than the real tube path:


| Setting                                    | Default | Plain meaning                                     |
| ------------------------------------------ | ------- | ------------------------------------------------- |
| `variable_load_to_toolhead_search_mm`      | `900`   | Max search from hub sensor → toolhead             |
| `variable_load_past_toolhead_mm`           | `15`    | Extra push to seat filament in the extruder gears |
| `variable_unload_from_toolhead_search_mm`  | `200`   | Max retract to clear the toolhead switch          |
| `variable_load_to_toolhead_full_search_mm` | `2200`  | Hub-less: ACE → toolhead in one go                |
| `variable_unload_past_hub_mm`              | `950`   | Hub-less: extra retract past the merge point      |


A little too long is usually fine. Too short fails loads or leaves filament
in the hub.

Your printer should already have tray / wipe / pause helpers CosmoACE calls:
`MOVE_TO_TRAY`, `M729`, `PAUSE_BASE`, and `RESUME`.

## More reading

- [Advanced README](README_ADVANCED.md) — pinouts, manual install, TODOs, and detailed specs
- [OrcaSlicer G-Code](docs/ORCA_GCODE.md) — what to paste into the slicer
- [ACE Macro Reference](docs/ACE_MACROS.md) — every macro and config variable
- [ACE USB Stability](docs/ACE_USB_STABILITY.md) — flaky rear port, logs, and tests


# CosmoACE Integration

CosmoACE is a lightweight Anycubic ACE Pro add-on for CosmOS / OpenCentauri.

This repo is intentionally focused on:
- CosmOS / OpenCentauri
- OrcaSlicer and PrusaSlicer-style forks
- lightweight printer-side integration

It does not target generic Klipper distributions or every slicer.

## What It Does

CosmoACE installs:
- a Python-based ACE CLI tool
- a shell wrapper Klipper can call
- a Klipper macro set for blocking start, toolchange, and end-print flows

The supported print flow is:
1. Load the selected slot until the filament sensor triggers.
2. Push from the sensor to the printhead by a configured distance.
3. Sync-load, purge, wipe, and start printing.
4. On toolchange, cut, unload back to the sensor, clear the hub, load the next slot, push to the printhead, sync-load, purge, wipe, and resume.

## TODO: CC1 Canvas Toolhead Sensor Migration

Upstream predates the CC1 Canvas toolhead, which exposes a real filament switch at the
extruder inlet (`hotend:PB2`) alongside cutter, front-cover, and feeding-pressure
switches. The flow above reaches the printhead by blind-feeding
`load_to_printhead_mm` (730mm) past the hub sensor and hoping the distance is right.
With a toolhead sensor we can stop on the switch instead.

- [x] Add a `toolhead_sensor_name` setting to `_ACE_CONFIG`. The macros pass the sensor name
      through to `feed-to-sensor` on every call, so `ace-addon.conf` needs no new key.
- [x] Replace the blind push in `_ACE_LOAD_TO_PRINTHEAD` with a bounded `feed-to-sensor`
      search against the toolhead sensor, then a short push past it into the extruder gears.
- [x] Keep the blind push as a fallback so printers without a toolhead sensor still work.
- [x] Retract clear of the toolhead sensor before the long hub retract on toolchange and end-print.
- [x] Verify the toolhead sensor reads clear after cut and unload, so a leftover stub in the
      extruder can never be rammed by the next load.
- [x] Update the `printer.cfg` example: `pause_on_runout: False` on the toolhead sensor and
      route its events into `_ACE_SENSOR_EVENT`.
- [ ] Measure the real hub-sensor-to-toolhead distance and tighten `load_to_toolhead_search_mm`
      from the current 900mm guess.
- [ ] Tune `load_past_toolhead_mm` (currently 15mm) so the filament reaches the extruder gears
      without pushing into the melt zone cold.
- [x] (`nohub` branch) Make the hub sensor fully optional: loads search straight to the toolhead
      sensor, unloads blind-retract past the merge point with `ACE_BLIND_CLEAR_HUB`.
- [ ] (`nohub` branch) Calibrate `unload_past_hub_mm` and `load_to_toolhead_full_search_mm`
      by running `ACE_BLIND_CLEAR_HUB` while the hub sensor is still installed; the macro
      cross-checks the blind distance against the hub sensor whenever one is present.
- [ ] Use `toolhead_cutter_detection` to confirm the cut actually engaged in `_ACE_CUT_FILAMENT`.
- [ ] Use `toolhead_feeding_pressure_detection` to abort on a tangle instead of stalling.
- [ ] Refresh the config table and macro list in `docs/ACE_MACROS.md`.
- [ ] Bench-test start, toolchange, and end-print on the Canvas toolhead.

## Requirements
An Elegoo Centauri Carbon and an Anycubic ACE Pro

- A working CosmOS installation
- SSH access as `root`
- Klipper `gcode_shell_command`
- A configured `filament_switch_sensor`
- Printer-side tray / wipe / pause macros already present:
  - `MOVE_TO_TRAY`
  - `M729`
  - `PAUSE_BASE`
  - `RESUME`

Set your gcode in OrcaSlicer:
[OrcaSlicer G-Code Guide](docs/ORCA_GCODE.md)

## Install

1. Copy this repository to a USB drive.
2. SSH into the printer as `root` (password: `OpenCentauri`).
3. Run:

```sh
# Navigate to your USB mount (usually /user-resource/.tmp/ on Centauri)
cd /user-resource/.tmp/cosmoace-integration
chmod +x install.sh uninstall.sh
./install.sh
```

### Manual Install (If script fails)
If you prefer to install manually or the script encounters issues with your specific firmware version:

1. **Remount as Read-Write:**
   ```sh
   mount -o remount,rw /
   ```
2. **Create Directories:**
   ```sh
   mkdir -p /user-resource/ace-addon
   mkdir -p /etc/klipper/config/klipper-readonly
   ```
3. **Copy Files:**
   ```sh
   cp files/ace-addon.py /user-resource/ace-addon/
   cp files/ace-command.sh /user-resource/ace-addon/
   cp files/ace-addon.conf /user-resource/ace-addon/
   cp files/ace_macros.cfg /etc/klipper/config/ace-addon.cfg
   ```
4. **Set Permissions & Symlink:**
   ```sh
   chmod +x /user-resource/ace-addon/*.sh /user-resource/ace-addon/*.py
   ln -sfn /etc/klipper/config/ace-addon.cfg /etc/klipper/config/klipper-readonly/ace-addon.cfg
   ```
5. **Remount as Read-Only:**
   ```sh
   mount -o remount,ro /
   ```
6. **Restart Klipper:**
   ```sh
   service klipper restart
   ```

## Hardware
You will need this filament hub adapter which mounts to the Carbon Centauri's run-out sensor:
[Filament Hub Adapter (Printables)](https://www.printables.com/model/1662192-centauri-carbon-multi-material-filament-hub-4-colo)

### Modified ACE Cable
You will need to either modify the 4-pin end of the ACE cable or build an adapter. Pins 3 and 4 need to be swapped.

## Required Printer Config

On this branch (`nohub`) the hub sensor is optional. If you have one at the 4-way merge
point, configure it — it gives immediate hub-clear confirmation on toolchanges:

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

On a post-Canvas CC1 toolhead, also wire up the sensor at the extruder inlet:

```cfg
[filament_switch_sensor toolhead_runout_sensor]
switch_pin: !hotend:PB2
pause_on_runout: False
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_RUNOUT
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_INSERT
```

Notes:
- `pause_on_runout` must be `False` on both sensors. The ACE macros retract past them on
  purpose, and Klipper's own pause handling would fight the toolchange.
- The macro name must be `_ACE_SENSOR_EVENT`.
- If your sensor objects are not named `runout` and `toolhead_runout_sensor`, update
  `variable_sensor_name` and `variable_toolhead_sensor_name` in `ace-addon.cfg`.

### Running without a hub sensor

To go toolhead-sensor-only, remove the `[filament_switch_sensor runout]` section from
`printer.cfg` entirely (or set `variable_sensor_name: ""` in `ace-addon.cfg`). Do not leave
the section configured with the switch unplugged — a floating pin can read as permanently
triggered and the macros will trust it.

Without a hub sensor the flows change to:
- Load: one bounded search from the ACE all the way to the toolhead sensor
  (`load_to_toolhead_full_search_mm`, default 2200mm). If the sensor never trips, the load
  aborts — a jam at the hub stalls the ACE against the blockage rather than grinding.
- Unload: retract until the toolhead sensor clears, then `ACE_BLIND_CLEAR_HUB` retracts a
  generous fixed distance (`unload_past_hub_mm`, default 950mm) to pull the tail back past
  the merge point. Over-retracting is harmless; the ACE just spools the extra back.
- Runout detection comes from the toolhead sensor.

While your hub sensor is still installed, you can calibrate the blind distance safely:
`ACE_BLIND_CLEAR_HUB` automatically verifies against the hub sensor whenever one exists,
so a too-short `unload_past_hub_mm` fails loudly instead of jamming the next load.

## Required Tuning

With a toolhead sensor configured, loading stops on the switch rather than at a fixed
distance, so the values that matter are:

- `variable_load_to_toolhead_search_mm` (Default: `900`) — upper bound on the search from the
  hub sensor to the toolhead sensor. It only needs to exceed the real distance; overshoot
  costs nothing because the feed stops when the switch trips.
- `variable_load_past_toolhead_mm` (Default: `15`) — how far to push past the toolhead switch
  to seat the filament in the extruder gears.
- `variable_unload_from_toolhead_search_mm` (Default: `200`) — upper bound on the retract that
  pulls the filament back off the toolhead switch.

Hub-less setups additionally use:

- `variable_load_to_toolhead_full_search_mm` (Default: `2200`) — search bound for the full
  ACE-to-toolhead run when no hub sensor stages the load. Only needs to exceed the real
  path length.
- `variable_unload_past_hub_mm` (Default: `950`) — blind retract from the toolhead sensor back
  past the merge point. Should comfortably exceed toolhead-to-hub distance; extra is harmless.

`variable_load_to_printhead_mm` (Default: `730`) is now only used as a blind-push fallback when
`variable_toolhead_sensor_name` is empty or the named sensor does not exist. On those printers
it is still the critical value: too short and the filament won't reach, too long and it overfeeds.

## Uninstall

```sh
cd /user-resource/.tmp/cosmoace-integration
./uninstall.sh
```

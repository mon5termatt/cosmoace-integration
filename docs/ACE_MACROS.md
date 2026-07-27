# ACE Macro Reference

CosmoACE is built around one supported print path: blocking OrcaSlicer / PrusaSlicer-style start, toolchange, and end macros. The older async flow is gone.

This document lists the macros in `files/ace_macros.cfg`, what each one does, and which variables you can tune in `/etc/klipper/config/ace-addon.cfg`.

## Runtime Pieces

- `gcode_shell_command ace_rpc`: shell bridge Klipper uses to talk to the addon service.
- `[gcode_macro _ACE_CONFIG]`: user-editable configuration values.
- `[gcode_macro _ACE_STATE]`: internal runtime state for the current print.

## Connection Reliability

The ACE's USB link can flap (brief disconnect/reconnect cycles). The addon
compensates at several levels, tunable in `ace-addon.conf`. Keepalive finding,
by-id pinning, and knobs: [ACE USB Stability](ACE_USB_STABILITY.md).

- **Protocol keepalive** (`keepalive_enabled`, default **true**): a low-priority
  `get_status` every 2s. Testing showed the ACE GD32 drops USB on an exact
  3.584s timer when there is no Anycubic protocol traffic; merely holding the
  tty open does not help. The daemon releases the tty between ticks and skips
  ticks when 1-minute host load reaches `keepalive_load_limit` (default 2.0),
  protecting Klipper from “Timer too close”.
- **Stable device path**: default `serial_port` is the
  `/dev/serial/by-id/usb-ANYCUBIC_ACE_*` alias (not raw `/dev/ttyACM*`) — the
  alias keeps its name when ACM numbering changes at boot (enumeration delays
  can swap MCU vs ACE) or after a flap. `auto` still prefers by-id when present
  but re-scans every call. `connect_settle_s` (default 0.15s) pauses after a
  fresh open so a just-rebound port is actually ready before the first write.
- **Connect retries** (`connect_retries`, `connect_retry_delay_s`): fail-fast open
  while the rear AMS link flaps; each attempt re-scans for VID `28e9`.
- **RPC retries** (`rpc_retries`, `rpc_retry_delay_s`): ACEPRO-style — 3 attempts
  per call with a growing backoff (0.25s, x1.5, capped at 2s) so a retry lands in
  the next USB up-window when the link is flapping. Motion commands (feed/retract)
  are sent exactly once, after a retried `get_status` probe proves the link is
  alive, so a retry can never double a movement.

Use `ACE_CHECK` from the console to verify the link end to end before starting a print.
It prints a short `ACE: Connected` / `ACE: Not connected (...)` line (no JSON dump).
On Klipper start, `_ACE_ANNOUNCE_CONNECT` opens the ACE serial port the same way
BunnyACE does and echoes `ACE: Connected {model} {firmware}` once `get_info` succeeds.

## ACE Initial Setup Wizard

First-install UI prompts (CosmOS `action:prompt_*`) unless
`/user-resource/ace-addon/setup_complete` exists. Helper: `files/ace-setup.py`
(installed as `/user-resource/ace-addon/ace-setup.py`).

| Macro | Role |
| --- | --- |
| `ACE_INITIAL_SETUP` | Start or resume the wizard. Clears completion and starts over unless a failed lane test is still active (then shows Retry/Stop/Exit). |
| `ACE_SETUP_RETRY` | Re-show the current lane prompt after a failure. |
| `_ACE_SETUP_BOOT` | Delayed gcode (~12s after Klipper start): consume resume after hub/hub-less config restart, else launch first-run setup. |
| `_ACE_SETUP_TEST_LANE` | Safe lane cycle: `_ACE_LOAD_TO_SENSOR` @ 8 mm/s, `_ACE_UNLOAD_TO_SENSOR`, `_ACE_CLEAR_HUB`, verify clear. Does not advance on error. |
| `_ACE_SETUP_EXIT` / `_ACE_SETUP_STOP` | Leave `setup_complete` unset so the prompt can return after restart. |

Motion limits match production helpers (`load_to_sensor_search_mm` = 1200). After a
full `service klipper restart`, wait ~45s before expecting the wizard resume.
After `FIRMWARE_RESTART`, wait ~20–30s.

## Config Variables

Edit these in `/etc/klipper/config/ace-addon.cfg`.

| Variable | Default | Used by | Purpose |
| --- | ---: | --- | --- |
| `variable_sensor_name` | `HUB` | Hub load/unload macros | Hub filament sensor object name. Set to `""` if you have no hub sensor — loads then search all the way to the toolhead sensor and unloads use the blind hub clear. |
| `variable_toolhead_sensor_name` | `toolhead_runout_sensor` | Toolhead load/unload macros | Toolhead filament sensor object name. Set to `""` if you have no toolhead sensor — loads fall back to the blind `load_to_printhead_mm` push. |
| `variable_load_to_sensor_search_mm` | `1200` | `ACE_LOAD_TO_SENSOR`, `_ACE_ORCA_START`, `_ACE_ORCA_TOOLCHANGE` | Max distance to search for the hub sensor while loading. |
| `variable_load_to_toolhead_search_mm` | `900` | `ACE_LOAD_TO_TOOLHEAD`, `ACE_LOAD_TO_PRINTHEAD` | Max distance to search for the toolhead sensor when starting from the hub. |
| `variable_load_to_toolhead_full_search_mm` | `2200` | `_ACE_ORCA_START`, `_ACE_ORCA_TOOLCHANGE` | Search bound for hub-less loads: full ACE-to-toolhead run plus margin. |
| `variable_load_past_toolhead_mm` | `15` | `ACE_LOAD_TO_TOOLHEAD`, `ACE_LOAD_TO_PRINTHEAD` | Extra push into the extruder after the toolhead sensor triggers. |
| `variable_unload_from_toolhead_search_mm` | `200` | `ACE_UNLOAD_FROM_TOOLHEAD`, `_ACE_ORCA_TOOLCHANGE`, `_ACE_ORCA_END_PRINT` | Max retract while waiting for the toolhead sensor to clear. |
| `variable_unload_past_hub_mm` | `950` | `ACE_BLIND_CLEAR_HUB`, hub-less toolchange/end | Blind retract from the toolhead sensor back past the merge point. Over-retracting is harmless (the ACE spools it back), so keep this generous. |
| `variable_load_to_printhead_mm` | `730` | `ACE_LOAD_TO_PRINTHEAD` (no toolhead sensor) | Blind push distance from sensor to printhead. Only used when no toolhead sensor is configured. |
| `variable_unload_to_sensor_search_mm` | `900` | `ACE_UNLOAD_TO_SENSOR`, `_ACE_ORCA_START`, `_ACE_ORCA_TOOLCHANGE`, `_ACE_ORCA_END_PRINT` | Max distance to search for sensor clear while retracting. |
| `variable_unload_to_sensor_probe_mm` | `10` | `ACE_PROBE_SENSOR_IN`, `ACE_PROBE_SENSOR_OUT` | Small probe distance for sensor tests. |
| `variable_unload_to_sensor_probe_speed_mm_s` | `5` | `ACE_PROBE_SENSOR_OUT` | Speed for the retract probe. |
| `variable_retract_slot_mm` | `90` | `ACE_RETRACT_SLOT`, `ACE_CLEAR_HUB`, `_ACE_ORCA_TOOLCHANGE`, `_ACE_ORCA_END_PRINT` | Hub-clear retract after the sensor has cleared. |
| `variable_clear_hub_step_mm` | `10` | `ACE_CLEAR_HUB` | Extra retract step size if the hub is still blocked. |
| `variable_clear_hub_max_extra_mm` | `60` | `ACE_CLEAR_HUB` | Maximum extra retract allowed while clearing the hub. |
| `variable_clear_hub_settle_s` | `0.25` | `ACE_CLEAR_HUB` | Post-step settle delay before checking the sensor again. |
| `variable_clear_hub_confirm_s` | `1.0` | `ACE_CLEAR_HUB` | Sensor-clear confirmation window before success is reported. |
| `variable_extruder_release_mm` | `30` | `_ACE_CUT_FILAMENT` | Small extruder release after the cut motion. |
| `variable_extruder_release_speed_mm_s` | `4` | `_ACE_CUT_FILAMENT` | Speed for the release retract. |
| `variable_feed_speed_mm_s` | `25` | Load macros and probe-in paths | Default ACE feed speed. |
| `variable_retract_speed_mm_s` | `15` | Unload and retract macros | Default ACE retract speed. |
| `variable_purge_mm` | `40` | `ACE_PURGE`, `_ACE_ORCA_START`, `_ACE_ORCA_TOOLCHANGE` | Default purge amount at the tray. |
| `variable_purge_chunk_mm` | `100` | `ACE_PURGE` | Chunk size for long purges to stay under Klipper limits. |
| `variable_purge_temp` | `250` | `_ACE_HEAT_FOR_PURGE`, `_ACE_ORCA_START`, `_ACE_ORCA_TOOLCHANGE` | Hotend temperature for purge operations. |
| `variable_purge_speed_mm_s` | `3` | `ACE_PURGE`, `ACE_SYNC_LOAD`, `_ACE_ORCA_START`, `_ACE_ORCA_TOOLCHANGE` | Default speed for purge and sync-load extrusion. |
| `variable_dry_temp_c` | `45` | `ACE_DRY_START` | Default dryer temperature in Celsius. |
| `variable_dry_minutes` | `240` | `ACE_DRY_START` | Default drying duration in minutes. |
| `variable_dry_fan_speed` | `7000` | `ACE_DRY_START` | Default dryer fan speed. |
| `variable_sync_load_mm` | `40` | `ACE_SYNC_LOAD`, `_ACE_ORCA_START`, `_ACE_ORCA_TOOLCHANGE` | How much to sync-load after the push-to-printhead stage. |
| `variable_sync_load_chunk_mm` | `5` | `ACE_SYNC_LOAD` | Chunk size for sync-load so ACE and extruder stay serialized. |
| `variable_sync_load_settle_s` | `0.25` | `ACE_SYNC_LOAD` | Delay between sync-load chunks. |
| `variable_swap_lift_z` | `5` | `_ACE_DROP_BED` | How far to lift before moving the bed/toolhead during a swap. |
| `variable_lift_speed_mm_s` | `10` | `_ACE_DROP_BED` | Speed for the swap lift. |
| `variable_return_xy_speed_mm_s` | `200` | `_ACE_RETURN_XY` | Speed used when returning to the saved XY position. |
| `variable_return_z_speed_mm_s` | `10` | `_ACE_RETURN_Z` | Speed used when returning to the saved Z position. |
| `variable_cut_x` | `255` | `_ACE_CUT_FILAMENT` | X position for the cut blade move. |
| `variable_cut_y` | `3` | `_ACE_CUT_FILAMENT` | Y position for the cut blade move. |
| `variable_cut_clear_y` | `30` | `_ACE_CUT_FILAMENT` | Safe Y position before and after the cut move. |

## Public Macros

These are the commands you normally use from the console or call from slicer G-code.

| Macro | What it does | Inputs |
| --- | --- | --- |
| `ACE_SET_SENSOR_NAME` | Changes which `filament_switch_sensor` object the addon watches as the hub sensor. `NAME=""` selects hub-less mode. | `NAME` |
| `ACE_ENABLE_SENSORS` | Enables the configured hub and/or toolhead filament sensors (`SET_FILAMENT_SENSOR`). | optional `TARGET=all\|hub\|toolhead` |
| `ACE_DISABLE_SENSORS` | Disables those sensors (silences runout/insert events; ACE motion macros that poll sensors still see live pin state via Moonraker). | optional `TARGET=all\|hub\|toolhead` |
| `ACE_INITIAL_SETUP` | Guided first-install hub / hub-less wizard and lane-to-hub tests. Clears `setup_complete` when starting fresh. | optional `FORCE` |
| `ACE_SETUP_RETRY` | Re-open the current setup lane prompt after a failed test. | none |
| `ACE_STATUS` | Prints the current ACE mode, slot state, hub and toolhead sensor states, `sensors_enabled`, and saved return position. | none |
| `ACE_CHECK` | Verifies the ACE serial connection with a status round-trip. The addon retries through brief USB disconnects, so a flaky link that recovers still passes. | none |
| `ACE_SLOT_STATUS` | Queries the addon service for the selected slot's readiness. | `SLOT` |
| `ACE_DRY_START` | Starts the ACE's built-in filament dryer. `TEMP` is 1–65 °C (ACE Pro hardware max is usually 55). `DURATION` and `MINUTES` are aliases. | optional `TEMP`, `DURATION`/`MINUTES`, `FAN` |
| `ACE_DRY_STOP` | Stops the ACE dryer. | none |
| `ACE_LOAD_TO_SENSOR` | Loads a slot until the hub sensor triggers. Errors out if no hub sensor is configured. | `SLOT`, optional `LENGTH`, `SPEED`, `SENSOR` |
| `ACE_LOAD_TO_TOOLHEAD` | Feeds a slot until the toolhead sensor triggers, then pushes a short distance into the extruder. | `SLOT`, optional `SEARCH`, `PAST`, `SPEED`, `SENSOR` |
| `ACE_LOAD_TO_PRINTHEAD` | Pushes the current or pending slot to the printhead: uses the toolhead sensor search if one is configured, otherwise a blind `LENGTH` push. | `SLOT`, optional `LENGTH`, `SEARCH`, `PAST`, `SPEED`, `TOOLHEAD_SENSOR` |
| `ACE_UNLOAD_FROM_TOOLHEAD` | Retracts the active slot until the toolhead sensor clears. Skips gracefully if no toolhead sensor is configured. | `SLOT`, optional `LENGTH`, `SPEED`, `SENSOR` |
| `ACE_UNLOAD_TO_SENSOR` | Retracts a slot until the hub sensor clears. Errors out if no hub sensor is configured. | `SLOT`, optional `LENGTH`, `SPEED`, `SENSOR` |
| `ACE_RETRACT_SLOT` | Short retract past the hub sensor to keep the hub path open. | `SLOT`, optional `LENGTH`, `SPEED` |
| `ACE_CLEAR_HUB` | Clears the hub path after unload and rechecks the live hub sensor before success is reported. | `SLOT`, optional `LENGTH`, `STEP`, `MAX_EXTRA`, `SPEED`, `SENSOR`, `SETTLE_S`, `CONFIRM_S` |
| `ACE_BLIND_CLEAR_HUB` | Fixed-distance retract past the merge point for hub-less setups. **Not registered by default** so hub installs keep it off the Mainsail panel — enable via `[include ace_macros_nohub_panel.cfg]`. Refuses to run if a hub sensor is present. Orca always calls `_ACE_BLIND_CLEAR_HUB` internally. | `SLOT`, optional `LENGTH`, `SPEED`, `TOOLHEAD_SENSOR` |
| `ACE_PROBE_SENSOR_OUT` | Retracts a short distance and reports whether the hub sensor is clear. | `SLOT`, optional `LENGTH`, `SPEED` |
| `ACE_PROBE_SENSOR_IN` | Feeds a short distance and reports whether the hub sensor is triggered. | `SLOT`, optional `LENGTH`, `SPEED` |
| `ACE_PURGE` | Purges at the tray, splitting long purges into safe chunks. | `LENGTH`, optional `SPEED`, `CHUNK` |
| `ACE_SYNC_LOAD` | Sync-loads ACE and extruder together in small chunks. | `SLOT`, optional `LENGTH`, `SPEED`, `ACE_SPEED`, `CHUNK`, `SETTLE_S` |
| `ACE_WIPE` | Runs the tray wipe motion. | none |

## Orca / Prusa-Fork Entry Macros

These are the slicer-facing entry points. They are hidden on purpose so the Mainsail macro panel stays focused on troubleshooting.

| Macro | What it does | Inputs |
| --- | --- | --- |
| `_ACE_ORCA_START` | Blocking print start: home if needed, move to purge, load to the hub sensor (if present), search to the toolhead sensor (or blind-push), sync-load, purge, wipe, and mark the slot active. | `SLOT`, optional `SENSOR`, `TOOLHEAD_SENSOR`, `LOAD_LENGTH`, `LOAD_SPEED`, `PUSH_LENGTH`, `SEARCH_LENGTH`, `PAST_LENGTH`, `TEMP`, `SYNC_LENGTH`, `PURGE`, `SPEED`, `ACE_SPEED`, `CHUNK`, `WIPE` |
| `_ACE_ORCA_TOOLCHANGE` | Blocking mid-print swap: save position, pause, lift, cut, unload off the toolhead sensor, clear the hub (sensor-verified or blind), load the next slot, search to the toolhead sensor, sync-load, purge, wipe, return, and resume. | `SLOT`, optional `SENSOR`, `TOOLHEAD_SENSOR`, `UNLOAD_LENGTH`, `UNLOAD_SPEED`, `TOOLHEAD_UNLOAD_LENGTH`, `RETRACT_LENGTH`, `BLIND_CLEAR_LENGTH`, `LOAD_LENGTH`, `LOAD_SPEED`, `PUSH_LENGTH`, `SEARCH_LENGTH`, `PAST_LENGTH`, `TEMP`, `SYNC_LENGTH`, `PURGE`, `SPEED`, `ACE_SPEED`, `CHUNK`, `WIPE` |
| `_ACE_ORCA_END_PRINT` | End-of-print clear: cut, unload off the toolhead sensor, clear the hub (sensor-verified or blind), and reset ACE state. | optional `SENSOR`, `TOOLHEAD_SENSOR`, `UNLOAD_LENGTH`, `UNLOAD_SPEED`, `TOOLHEAD_UNLOAD_LENGTH`, `RETRACT_LENGTH`, `BLIND_CLEAR_LENGTH` |
| `_ACE_TOOL_SELECT` | Routes unexpected `T0`..`T3` commands into the blocking toolchange path during an active print. | `SLOT` |
| `T0` | Safety alias for slot 1. | none |
| `T1` | Safety alias for slot 2. | none |
| `T2` | Safety alias for slot 3. | none |
| `T3` | Safety alias for slot 4. | none |

## Internal Support Macros

These are implementation helpers. They are callable from the console, but they are not the recommended user-facing entry points.

| Macro | What it does | Inputs |
| --- | --- | --- |
| `_ACE_PRE_TOOLCHANGE` | No-op hook before a toolchange. Useful if you want to extend behavior later. | none |
| `_ACE_POST_TOOLCHANGE` | No-op hook after resume / toolchange completion. | none |
| `_ACE_SET_MODE` | Updates the internal ACE mode and prints the mode change. | `MODE` |
| `_ACE_CLEAR_RETURN_POSITION` | Clears the saved return XY/Z position. | none |
| `_ACE_SAVE_RETURN_POSITION` | Saves the current toolhead position for later resume. | none |
| `_ACE_RESET_STATE` | Resets ACE state, cancels delayed resume, clears return position, and reloads the live sensor state. | none |
| `_ACE_ASSERT_SLOT_READY` | Refuses to continue if the selected slot is not ready according to the addon service. | `SLOT` |
| `_ACE_SLOT_LOAD_RAW` | Sends a raw ACE `feed` request. | `SLOT`, `LENGTH`, `SPEED` |
| `_ACE_SLOT_LOAD_WAIT_RAW` | Sends a blocking ACE feed request and waits for completion. | `SLOT`, `LENGTH`, `SPEED`, optional `TIMEOUT_S` |
| `_ACE_SLOT_UNLOAD_RAW` | Sends a raw ACE `retract` request. | `SLOT`, `LENGTH`, `SPEED` |
| `_ACE_SLOT_UNLOAD_WAIT_RAW` | Sends a blocking ACE retract request and waits for completion. | `SLOT`, `LENGTH`, `SPEED`, optional `TIMEOUT_S` |
| `_ACE_SLOT_WAIT_IDLE_RAW` | Waits for the ACE slot to become idle. | `SLOT`, optional `TIMEOUT_S` |
| `_ACE_SLOT_LOAD_TO_SENSOR_WAIT_RAW` | Blocking raw load that stops when the sensor triggers. | `SLOT`, `LENGTH`, `SPEED`, `SENSOR`, optional `TIMEOUT_S` |
| `_ACE_SLOT_UNLOAD_TO_SENSOR_WAIT_RAW` | Blocking raw unload that stops when the sensor clears. | `SLOT`, `LENGTH`, `SPEED`, `SENSOR`, optional `TIMEOUT_S` |
| `_ACE_VERIFY_SENSOR_TRIGGERED` | Errors out if the hub sensor is not triggered. | optional `SENSOR` |
| `_ACE_VERIFY_SENSOR_CLEAR` | Errors out if the hub sensor is still triggered. | optional `SENSOR` |
| `_ACE_VERIFY_TOOLHEAD_TRIGGERED` | Errors out if the toolhead sensor is not triggered. | optional `SENSOR` |
| `_ACE_VERIFY_TOOLHEAD_CLEAR` | Errors out if the toolhead sensor is still triggered. | optional `SENSOR` |
| `_ACE_SENSOR_EVENT` | Sensor insert/runout hook used by Klipper for both sensors (`RUNOUT`, `INSERT`, `TOOLHEAD_RUNOUT`, `TOOLHEAD_INSERT`). It records the event and pauses on real runout during printing. | `EVENT` |
| `_ACE_PAUSE_PRINT` | Validates that a print is active, then pauses it through Klipper. | none |
| `_ACE_DROP_BED` | Raises the toolhead to create swap clearance. | optional `LIFT`, `SPEED` |
| `_ACE_RETURN_XY` | Returns to the saved XY position. | optional `SPEED` |
| `_ACE_RETURN_Z` | Returns to the saved Z position. | optional `SPEED` |
| `_ACE_RESUME_PRINT` | Resumes a paused print after post-toolchange cleanup. | none |
| `_ACE_DELAYED_RESUME_PRINT` | Delayed wrapper that resumes only if the print is still paused. | none |
| `_ACE_MOVE_TO_PURGE` | Moves the toolhead to the purge tray and waits for motion to settle. | none |
| `_ACE_HEAT_FOR_PURGE` | Heats the hotend to purge temperature. | optional `TEMP` |
| `_ACE_PURGE` | Internal purge implementation used by `ACE_PURGE` and the Orca start/toolchange flows. | `LENGTH`, optional `SPEED`, `CHUNK` |
| `_ACE_SYNC_LOAD` | Internal sync-load implementation used by the start/toolchange flows. | `SLOT`, `LENGTH`, `CHUNK`, `SPEED`, `ACE_SPEED`, optional `SETTLE_S` |
| `_ACE_WIPE` | Internal wipe implementation that runs `M729` and waits for motion to finish. | none |
| `_ACE_CUT_FILAMENT` | Moves to the cut position and releases the extruder slightly. | optional `RELEASE_MM`, `RELEASE_SPEED` |

## Recommended Manual Sequences

Load a slot with both sensors installed (hub first, then toolhead):

```gcode
ACE_LOAD_TO_SENSOR SLOT=1
ACE_LOAD_TO_TOOLHEAD SLOT=1
```

Load a slot with no hub sensor (toolhead sensor only, longer search):

```gcode
ACE_LOAD_TO_TOOLHEAD SLOT=1 SEARCH=2200
```

Unload with both sensors installed:

```gcode
ACE_UNLOAD_FROM_TOOLHEAD SLOT=1
ACE_UNLOAD_TO_SENSOR SLOT=1
ACE_CLEAR_HUB SLOT=1
```

Unload with no hub sensor:

```gcode
ACE_UNLOAD_FROM_TOOLHEAD SLOT=1
_ACE_BLIND_CLEAR_HUB SLOT=1
```

(Or `ACE_BLIND_CLEAR_HUB` if you included `ace_macros_nohub_panel.cfg`.)

Probe the hub sensor in either direction:

```gcode
ACE_PROBE_SENSOR_IN SLOT=1
ACE_PROBE_SENSOR_OUT SLOT=1
```

Dry filament in the ACE (temperature in Celsius, duration in minutes):

```gcode
ACE_DRY_START TEMP=55 DURATION=240
ACE_DRY_STOP
```

## Sensor Hooks

Your printer config should call the hidden sensor event macro from each sensor you have.

Hub sensor (optional — at the 4-way merge point):

```cfg
[filament_switch_sensor HUB]
pause_on_runout: False
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=RUNOUT
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=INSERT
```

Toolhead sensor (post-Canvas CC1, at the extruder inlet):

```cfg
[filament_switch_sensor toolhead_runout_sensor]
pause_on_runout: False
runout_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_RUNOUT
insert_gcode:
  _ACE_SENSOR_EVENT EVENT=TOOLHEAD_INSERT
```

If your sensor objects use different names, change `variable_sensor_name` and `variable_toolhead_sensor_name` in `ace-addon.cfg` (or call `ACE_SET_SENSOR_NAME` for the hub sensor). If a sensor is missing entirely, set its name variable to `""` so the macros use the fallback paths.

# Hardware Notes

Things learned the hard way about the ACE Pro and this board. Written down so
they don't have to be rediscovered.

## The ACE drops its own USB link after ~3.5s

The ACE Pro runs a comms watchdog: about 3.5 seconds after the last complete
frame it received, it drops off USB and re-enumerates (~0.5s). Anycubic's
firmware polls it constantly, so this never shows there. This addon only talks
to the ACE when a macro runs, so left alone it re-enumerates forever — 611
disconnects were in one kernel log buffer before this was understood.

Consequences and how they are handled:

- **Feed assist dies mid-print.** `ACE_LOAD` turns assist on, then nothing
  talks to the ACE and the next reset clears it, so the extruder drags the
  full bowden for the rest of the print. This is the reason `ace-keepalive.sh`
  exists: a shell loop writing one prebuilt `get_status` frame to each ACE
  every 2s. Shell, not Python — busybox costs a few hundred KB against
  ~5MB for an interpreter, on a board with 112MB total.
- **Commands landing in the re-enumeration window fail** with `errno 5`.
  `rpc_call` reconnects once and resends on a write-side I/O error. Read-side
  failures are deliberately *not* retried: the ACE may already be moving
  filament and a resend would double the motion.

The keep-alive and the CLI both take an exclusive `flock` on the tty, so they
can never interleave bytes inside a frame. If a command holds the port, that
keep-alive tick is skipped — the command is feeding the watchdog itself.

### Keep-alive must drain replies and not hammer `stty`

Write-only `get_status` every 2s is enough for the 3.5s watchdog, but leaving
the CDC replies unread and re-running `stty` every tick can wedge the ACE after
a few minutes. The kernel then logs `error -71` / `error -110` and the ACE
stays gone until it is power-cycled — unplugging nothing on the PC side will
bring it back. Keep-alive therefore:

- drains unread bytes after each frame (no parse)
- runs `stty` once per USB re-enumerate, not every tick
- forces `power/control=on` up the USB tree (no autosuspend)
- wraps each tick in `timeout 1` so a stuck tty cannot stall the loop
- is single-instance (reinstall used to stack extra `/bin/sh` copies)

### Panel status must not block the gcode queue

`[gcode_shell_command ace_rpc]` is synchronous with a 180s timeout, so a
stuck USB open used to park `G28` behind a dead ACE. `panel-status` therefore
forks the refresh and returns immediately; the panel polls the moonraker db
cache that `--compact` writes. One refresh at a time (`flock`), and the panel
backs off gcode kicks for 5 minutes after a USB I/O error. The CLI also fails
fast on `EIO` / open timeout so real macros cannot hold the queue either.

## Two ACEs: hub pass-through, not a protocol relay

Chaining a second ACE into the first one's spare USB port is a plain **USB hub
pass-through**. The kernel shows the port as `USB2.0 Hub` and the second unit
as its own `ACE` device with its own tty. Nothing is proxied through unit 1,
and the protocol has no unit-addressing field at all — unit identity is just
"which tty you opened". Slots 5-8 map to unit 1 slots 1-4.

Two traps:

- **Both units report the same by-id name** (`usb-ANYCUBIC_ACE_1`), so
  `/dev/serial/by-id` can only ever show one of them.
- **ttyACM numbering shifts between boots**, so it can't be hardcoded either.

Both the CLI and the keep-alive therefore identify ACEs by their **USB product
string** in sysfs and order them by USB path, which is stable across reboots
and power cycles: the directly connected unit is always slots 1-4, a chained
one always 5-8. That also means neither can ever address the printer's MCU
port. `by-path` pinning still works if auto-detection ever fails.

The printer's own MCU is on a *different* USB controller (`ohci`) from the
ACEs (`ehci`), so ACE traffic does not contend with motion commands.

## The cutter is positional, not an impact

`CUT_FILAMENT` moves to X255 then presses Y20 -> Y4. With `max_accel: 20000`,
reaching 300mm/s takes 2.25mm, so on that 16mm move the toolhead accelerates,
cruises, and then **decelerates to a stop at Y4**. So:

- If the shear completes at Y4, force comes from motor torque alone and ram
  speed is irrelevant; repeating the press just revisits the same position.
- If contact happens earlier (say Y6), it *is* an impact — ~283mm/s there
  versus 20mm/s for the stock F1200, roughly 200x the energy.

The override in `ace_macros.cfg` presses twice at 300mm/s for that reason. A
blade that will not cut at Y4 is a mechanical problem (dull edge, alignment),
not something more presses will fix. Pressing deeper than Y4 is a bad idea:
Y min is -2 and homing is sensorless, so ramming a hard stop can skip steps
and silently shift the origin.

## Spool take-up lags fast retracts

The take-up rollers rewind slower than the feed gear retracts, so a fast
retract piles slack inside the ACE. `retract_speed` is a tradeoff, not a
free win. `unwind_filament` also takes an undocumented `mode` (0 normal,
1 "enhanced") exposed as `retract_mode`; A/B timing showed no difference, so
if it does anything it is take-up behaviour and has to be judged by watching
the rollers.

Also: the ACE only respools while an unwind command runs **to completion**.
Stopping an unwind partway skips the take-up and leaves slack, which is why
`ACE_UNLOAD` does one long completed retract instead of stopping at the
sensor.

## Board limits

112MB RAM, 2 ARMv7 cores, zram swap (COSMOS sets `swappiness=150`
deliberately — zram paging is cheap, so don't "fix" it). Klipper needs the
gcode buffer kept full; anything that blocks its main loop or its reads from
eMMC risks a `Timer too close` MCU shutdown. Keep per-command work small and
avoid standing processes that poll storage.

## Not done yet

An 8-slot input hub plus feeding unit 2 into the printhead. The macros already
accept slots 1-8 and `T0`-`T7` exist, but anything sensor-verified for slots
5-8 cannot pass until unit 2 physically reaches the shared filament sensor —
there is only one sensor on the printer.

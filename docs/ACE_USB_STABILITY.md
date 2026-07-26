# ACE USB Stability

How CosmoACE deals with a flaky rear-AMS USB link on the Elegoo Centauri
Carbon, and what the keepalive finding means in practice.

## Reality check

Linux **USB device numbers** in `dmesg` (`device number 91`, `92`, …) always
increment on reconnect. That counter cannot be frozen — it is kernel USB
addressing, not a CosmoACE bug.

What *does* stay stable on CosmOS is the by-id symlink:

```text
/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00  ->  ../../ttyACM1
```

The symlink **name** is constant. Only its target updates when the raw
`/dev/ttyACM*` node renumbers. That is the durable identity CosmoACE opens.

Raw ACM numbers are not stable across boots either. Enumeration order depends
on which device (Klipper MCU vs ACE) finishes first, so delays at boot can
swap which one lands on `ttyACM0` vs `ttyACM1`. Mid-run flaps renumber the
same way. Pinning by-id avoids both.

## What CosmoACE pins

Default in `files/ace-addon.conf`:

```ini
serial_port = /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00
```

Never pin `/dev/ttyACM1`. That node can change at boot from enumeration delays
and again on reconnect, and will eventually open the wrong ACM (or nothing).

`serial_port = auto` still works and prefers by-id when present, but it
re-scans every call and is slower than a pinned by-id path. Keep the pin once
`ACE_CHECK` / `ace-command.sh health` has shown this alias on your unit
(`pin_hint` in the health JSON).

Related knobs (same conf file):

| Knob | Default | Role |
| --- | ---: | --- |
| `connect_settle_s` | `0.15` | Pause after a successful open before the first write (fresh ACM bind). |
| `connect_retries` / `connect_retry_delay_s` | `2` / `0.3` | Fail-fast open while the link flaps; each attempt re-scans. |
| `rpc_retries` / `rpc_retry_delay_s` | `3` / `0.25` | ACEPRO-style: 3 attempts with growing backoff (×1.5, cap 2s). Motion RPCs are sent once after a retried `get_status` probe. |
| `keepalive_enabled` / `keepalive_interval_s` | `true` / `2.0` | Low-priority `get_status` traffic suppresses the ACE's 3.584s USB watchdog. |
| `keepalive_load_limit` | `2.0` | Skip ticks when 1-minute host load is high; Klipper timing wins over ACE continuity. |

## Optional USB watcher

Lightweight flap logger (manual start only — do not enable as a boot service):

```sh
/user-resource/ace-addon/ace-usb-watch.sh 5
# logs to /board-resource/ace-usb.log
```

If a Klipper restart is needed after deploying, wait ~45 seconds after
`service klipper restart` (or a `FIRMWARE_RESTART`) before trusting `ACE_CHECK`.
Do not stack a host restart with heavy polling on the 112MB board.

## 3.584-second watchdog finding

The idle loop is not Linux autosuspend or random bus noise:

- `usbcore.autosuspend=-1`, `power/control=on`, `runtime_status=active`
- no process holding the ACE tty
- disconnect deltas exactly **3.584s** (15/15 and longer samples)
- merely holding the tty file descriptor open did not change the period
- real Anycubic `get_status` traffic reduced a 30s sample from 8 disconnects
  idle to 1 disconnect, with the gap stretching to 21s
- stopping protocol traffic immediately restored the exact 3.584s loop

That points to an ACE GD32 firmware watchdog. CosmoACE therefore runs a
low-priority, no-HTTP protocol keepalive every 2s. It releases the tty between
ticks for CLI macros and skips ticks at high host load.

Initial on-printer soak with the guarded daemon:

- **0 disconnects in 120s** (versus ~33 expected at the 3.584s idle rate)
- 1-minute load stayed **0.10–0.52**
- daemon RSS stayed flat at **16.7MB**
- a concurrent CLI health check passed in **160ms**

## What software will not fix

- A true cable / ground / VBUS fault.
- Rising USB device numbers in `dmesg`.
- ACE resets during a skipped keepalive tick if the host is overloaded.

Climb the rear-AMS bring-up ladder in the [README](../README.md) for the
hardware side. Use this doc for the software identity, knobs, and keepalive
behavior.

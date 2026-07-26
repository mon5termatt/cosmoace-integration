# ACE USB Stability

How CosmoACE deals with a flaky rear-AMS USB link on the Elegoo Centauri
Carbon, how to measure it, and what the measured numbers look like.

## Reality check

Linux **USB device numbers** in `dmesg` (`device number 91`, `92`, …) always
increment on reconnect. That counter cannot be frozen — it is kernel USB
addressing, not a CosmoACE bug.

What *does* stay stable on CosmOS is the by-id symlink:

```text
/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00  ->  ../../ttyACM1
```

The symlink **name** is constant across flaps. Only its target updates when
the raw `/dev/ttyACM*` node renumbers. That is the durable identity CosmoACE
opens.

On Centauri Carbon the rear AMS port currently flaps on a ~3.5s cycle even
with a ferrite clip on the cable (hardware / harness SI). Software cannot
stop that cycle; it can only land retries inside the up-windows and avoid
chasing a renumbering `ttyACM` path.

## What CosmoACE pins

Default in `files/ace-addon.conf`:

```ini
serial_port = /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00
```

Never pin `/dev/ttyACM1`. That node renumbers on reconnect and will eventually
open the wrong ACM (or nothing).

`serial_port = auto` still works and prefers by-id when present, but it
re-scans every call and is ~3–4× slower than a pinned by-id path. Keep the
pin once `ACE_CHECK` / `ace-command.sh health` has shown this alias on your
unit (`pin_hint` in the health JSON).

Related knobs (same conf file):

| Knob | Default | Role |
| --- | ---: | --- |
| `connect_settle_s` | `0.15` | Pause after a successful open before the first write (fresh ACM bind). |
| `connect_retries` / `connect_retry_delay_s` | `2` / `0.3` | Fail-fast open while the link flaps; each attempt re-scans. |
| `rpc_retries` / `rpc_retry_delay_s` | `3` / `0.25` | ACEPRO-style: 3 attempts with growing backoff (×1.5, cap 2s). Motion RPCs are sent once after a retried `get_status` probe. |
| `keepalive_enabled` / `keepalive_interval_s` | `true` / `2.0` | Low-priority `get_status` traffic suppresses the ACE's 3.584s USB watchdog. |
| `keepalive_load_limit` | `2.0` | Skip ticks when 1-minute host load is high; Klipper timing wins over ACE continuity. |

## Tools

Both are **manual start only** — do not enable them as boot services.

### USB watcher

Lightweight flap logger:

```sh
/user-resource/ace-addon/ace-usb-watch.sh 5
# logs to /board-resource/ace-usb.log
```

### Stability harness

```sh
/user-resource/ace-addon/ace-stability-test.sh all      # full sweep (~3–5 min)
/user-resource/ace-addon/ace-stability-test.sh flap 60  # disconnects per minute
/user-resource/ace-addon/ace-stability-test.sh rpc 20   # health success + latency
/user-resource/ace-addon/ace-stability-test.sh paths    # raw tty vs by-id vs by-path
/user-resource/ace-addon/ace-stability-test.sh settle   # sweep connect_settle_s
```

Results append to `/board-resource/ace-stability.log`.

How to read it:

- **flap** — hardware SI baseline. A cable / ground / polarity fix should lower
  this. Software will not.
- **rpc** — what macros actually experience (ok rate + latency).
- **paths** — by-id should match or beat raw tty. If raw ever loses mid-test,
  the ACM node renumbered and by-id did its job.
- **settle** — pick the smallest `connect_settle_s` whose ok-rate matches the
  best one.

### 30-minute stress test

Longer soak that gently calls `health` on a fixed interval (default every 15s
for 30 minutes — about 120 samples). Also tracks USB presence, dmesg
disconnects, and loadavg. Backs off an extra interval if load ≥ 3 so it does
not tip CosmOS into “Timer too close”.

```sh
# Manual only. Leave ace-usb-watch and other hammers off while this runs.
/user-resource/ace-addon/ace-stress-test.sh           # 30 min / 15s
/user-resource/ace-addon/ace-stress-test.sh 30 20     # 30 min / 20s (gentler)
# Stop early: Ctrl-C, or kill $(cat /var/run/ace-stress.pid)
# Log: /board-resource/ace-stress.log
```

Progress lines every ~5 minutes; a full summary at the end (ok/fail %, latency
min/avg/max, USB present vs absent samples, disconnect count).

If a Klipper restart is needed after deploying, wait ~45 seconds after
`service klipper restart` (or a `FIRMWARE_RESTART`) before trusting `ACE_CHECK`
or any of these harnesses. Do not stack a host restart with polling on the
112MB board.

## Measured results (Centauri rear AMS)

Taken on the development printer with the link actively flapping
(~3.5s disconnect cycle, ferrite clip already on the cable).

### Full sweep (with `serial_port = auto`)

| Mode | Result |
| --- | --- |
| `flap` 30s | **8** disconnects (~16/min) |
| `rpc` ×20 | 20/20 ok, avg **639 ms** |
| `paths` ×10 each | raw / by-id / by-path all 10/10, avg ~**175 ms** |
| `settle` 0 / 0.15 / 0.5 / 1.0 | all 10/10; latency rises with settle |

Pinned paths were ~3.5× faster than `auto` because auto re-scans every call.
`settle=0` still passed 10/10 under flap; `0.15` is kept as cheap insurance
for opens that land right on a rebind.

### Latency after pinning by-id

After setting `serial_port = /dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00`,
restarting Klipper, and waiting ~45s:

| Test | ok | min / avg / max (ms) |
| --- | ---: | --- |
| `rpc` ×20 (pinned by-id) | 20/20 | **162 / 175 / 223** |
| `rpc` ×20 (`auto`, earlier) | 20/20 | 589 / 639 / 724 |

~**3.6×** lower average latency with the pin. The hardware flap rate itself
was unchanged.

## 3.584-second watchdog finding

The loop is not Linux autosuspend or random bus noise:

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
hardware side. Use this doc for the software identity, knobs, and how to
measure whether a cable change actually helped.

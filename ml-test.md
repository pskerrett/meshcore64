# Experiment: a pure machine-language client

**22 September 2026**

**Question:** the BASIC client tops out at 600 baud. Is that BASIC's fault?
If the whole client were machine language, would 1200 work?

**Answer: no — and the experiment says why.** The receive buffer never came
close to overrunning, so the corruption at 1200 is the KERNAL mis-sampling
bits, not the client being too slow to keep up. No amount of client speed
fixes it.

**But the rewrite is not worthless.** At 600 the ML client handled **212
messages at 4× the message rate with zero corrupt frames**, where the BASIC
client manages about 58 at 1×. The win is headroom, not baud rate.

---

## The two hypotheses

The 22 Sep link tests left a specific puzzle: at 1200, messages were lost and
4–8 frames per run were rejected as implausible, while the **transmit** path
stayed byte-perfect at every rate including 2400. Only receive failed. Two
candidate causes, needing completely different fixes:

**A. The KERNAL mis-samples bits.** The C64 has no UART on the user port; the
KERNAL bit-bangs RS-232 receive in an NMI handler, guessing where each bit
centre falls. At 600 a bit lasts 1.67ms, at 1200 only 0.83ms. If this is the
cause, client speed is irrelevant and the only route is replacing the
receiver outright.

**B. The receive buffer overruns.** The KERNAL's receive buffer is 256 bytes,
which at 1200 fills in about 2.1 seconds. A BASIC `mainLoop` pass that
renders a message, scrolls the screen and runs an REU DMA can plausibly take
that long. An overrun does not merely lose bytes — it **desyncs the frame
parser**, which then locks onto a `>` inside payload data and hands the
client garbage. That is exactly the signature the `rj` counter was catching.

B is a software problem. A is a hardware problem. The way to tell them apart
is to remove the software variable entirely and **measure how full the buffer
actually gets**.

## What was built

`ml-test-logs/mlclient.py` assembles `mlclient.prg` — a client with no BASIC
in it at all. Roughly 1.2KB of 6502: a BASIC stub that `SYS`es straight into
machine code, then RS-232 open, the four-command handshake, the message sync
loop, screen output, and counters reported back over the link.

It is **deliberately not feature-complete**: no channel picker, no REU
scrollback, no sending from the keyboard. It implements the load-bearing
receive path, because that is what the baud question turns on. This is a
spike, not a replacement client.

It reports every ~13 seconds, driven by the jiffy clock rather than by
arriving frames — a dead link at 2400 is precisely the run you need numbers
from, and a frame-driven report would say nothing there.

```
n = frames assembled     r = frames rejected as corrupt
m = messages displayed   h = handshake stages matched (bitmask)
o = receive buffer high-water mark   <-- the whole experiment
```

## Results

Eight runs. 60 messages pushed in the normal runs, ~230 in the load runs
(4× the message rate).

| baud | REU | messages shown | **rejected** | **buffer high-water** | queue left |
|---|---|---|---|---|---|
| **600** | none | 62 | **0** | **3 / 256** | 0 |
| **600** | 512K | 60 | **0** | **2 / 256** | 0 |
| 1200 | none | 11 | 19 | 2 / 256 | 14 |
| 1200 | 512K | 26 | 17 | 8 / 256 | 0 |
| 2400 | none | 0 | 0 | 1 / 256 | 63 |
| 2400 | 512K | 0 | 0 | 1 / 256 | 63 |
| **600, 4× load** | none | **212** | **0** | **5 / 256** | 1 |
| 1200, 4× load | none | 79 | 55 | 11 / 256 | 34 |

### The buffer never fills

Across every run, at every rate, under 4× load, the receive buffer
high-water mark peaked at **11 bytes out of 256 — 4.3%**. The ML client
drains it so aggressively it never backs up.

And yet at 1200 it still rejected 17–55 frames as corrupt.

**That refutes hypothesis B.** The frames are not being mangled because
bytes were dropped while the client was busy. They are arriving already
wrong. The KERNAL is mis-sampling bits at 1200 — hypothesis A.

This also retires the last remaining doubt about the earlier finding. It was
reasonable to suspect that the BASIC client's slowness was the real cause and
that 1200 would work given a fast enough client. It does not. The client is
now roughly as fast as a C64 can be, the buffer is 96% empty, and 1200 is
still corrupt.

### What 600 buys instead

The interesting result is the load test. At 600 with messages arriving four
times faster than the standard test, the ML client displayed **212 messages
with zero corrupt frames** and a 5-byte buffer high-water mark. The BASIC
client's best clean run is 58 messages at the normal rate.

So the rewrite delivers a large amount of headroom at 600 — useful on a busy
mesh, where the radio reports every packet it overhears. It just does not buy
a faster wire.

### 2400 remains completely dead

Zero frames assembled, handshake never started, in both REU configurations.
The KERNAL's status byte showed framing errors and a break condition. Worth
noting: at 2400 some of the client's own **outgoing** reports came back
mangled in the radio's log, which did not happen with the BASIC client. The
likely reason is that transmit and receive share one NMI handler, and a
receiver stuck in a framing-error loop disturbs transmit timing too.

## Known defect in the experimental client

The reply to `app_start` (`resp_code_self_info`, opcode 5) is **never
assembled into a frame** — a counter for "opcode-5 frames seen" reads zero —
while `device_info`, `channel_info` and `curr_time` all match reliably. The
client times that stage out after ~30s and works normally afterwards, which
is why the message counts above are still valid (and slightly conservative,
since each run lost 30 seconds to it).

Two fixes were tried and neither worked: flushing the receive buffer
(`RIDBS = RIDBE`) before the handshake, and additionally spending a second
polling-and-discarding to resync on real frame boundaries. The cause is
presumably that we open the port mid-stream and the parser is still out of
step when that first reply lands, but that is not proven and the fix is not
found. It is a defect in this experimental client only — the BASIC client
does not have it.

If anyone picks this up: make the handshake tracker a **bitmask, not a
count**. "3 of 4 stages matched" cost an extra emulator run because it does
not say *which*.

## Incidental: `OPEN` does not arm the RS-232 receiver

Worth recording, because it cost the first two runs and is not obvious.

You can call `SETNAM`/`SETLFS`/`OPEN` correctly, watch the KERNAL store your
control byte in `M51CTR` and configure `DDRB` for RTS/DTR — and receive not a
single byte, with `RIDBE` and `RIDBS` both sitting at zero forever. The
KERNAL enables the CIA2 FLAG NMI, the thing that spots an incoming start bit,
inside **`CHKIN`**, not inside `OPEN`. One `ldx #2 / jsr $FFC6` after opening
is the difference between a dead port and a working one. A later `CLRCHN`
only restores default I/O; it does not disarm the receiver.

## Conclusion

| | |
|---|---|
| Does removing BASIC fix 1200? | **No.** Buffer peaks at 4% full and frames are still corrupt. |
| Why not? | The KERNAL mis-samples bits at 1200. It is a receiver problem, not a throughput problem. |
| Is the rewrite worth anything? | **Yes, at 600.** 212 messages at 4× rate, zero corruption. |
| What would actually raise the baud rate? | Replacing the KERNAL receiver — UP9600-style, driving the CIA shift register in hardware. A different and much larger project. |

**600 baud stays**, and now for a reason that has been measured from both
directions rather than inferred.

## Files

Everything is in `ml-test-logs/`:

- `mlclient.py` — the assembler source and build script
- `mlclient.prg` — the built binary (600 baud; pass 8 or 10 to build 1200/2400)
- `asm.py` — the 6502 assembler, extended for this (`.word`, `.text`, `<lo`/`>hi`, `label+n`, ~30 more opcodes)
- `runml.sh`, `runmlall.sh` — the harness
- `radio_ml_*.log` — raw radio logs for all eight runs
- `sweep-summary.txt` — the sweep output

```bash
cd c64-0.9/test && ./runmlall.sh
```

Runs are sequential on purpose: the fake radio binds one fixed port, so two
in parallel silently starve one of a radio and the result looks like a
failure rather than a configuration mistake.

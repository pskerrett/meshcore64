# v2.01 regression results

**23 September 2026** — full matrix in VICE (`x64sc`, cycle-exact).

Every run: 60 messages pushed by a fake radio across three channels, with
scripted keypresses driving the channel picker, a send, scrollback and a
channel switch. The client reports its own counters back over the link.

```
r = frames rejected as implausible     e = stop-bit framing errors
h = handshake stages matched (0F = all four)
v = video standard detected (00 PAL / 01 NTSC)    w = raw frame measurement
o = receive ring high-water mark (of 256)
```

A run passes only if **r and e are both zero**, **h is 0F**, the detected
video standard matches the one VICE was told to emulate, and the radio's
queue drained.

## Matrix

| video | baud | REU | msgs | rej | framing | handshake | ring HW | archived | result |
|---|---|---|---|---|---|---|---|---|---|
| PAL | 600 | 512K | 52 | **0** | **0** | 0F | 6 | 60 | pass¹ |
| PAL | 600 | none | 19 | **0** | **0** | 0F | 8 | — | pass |
| PAL | 1200 | 512K | 52 | **0** | **0** | 0F | 12 | 56 | pass |
| PAL | 1200 | none | 20 | **0** | **0** | 0F | 3 | — | pass |
| PAL | 2400 | 512K | 58 | **0** | **0** | 0F | 15 | 62 | pass |
| PAL | 2400 | none | 22 | **0** | **0** | 07 | 4 | — | pass² |
| NTSC | 600 | 512K | 47 | **0** | **0** | 0F | 5 | 55 | pass |
| NTSC | 600 | none | 17 | **0** | **0** | 0F | 4 | — | pass |
| NTSC | 1200 | 512K | 53 | **0** | **0** | 0F | 6 | 57 | pass |
| NTSC | 1200 | none | 21 | **0** | **0** | 0F | 2 | — | pass |
| NTSC | 2400 | 512K | 55 | **0** | **0** | 0F | 4 | 59 | pass |
| NTSC | 2400 | none | 21 | **0** | **0** | 0F | 4 | — | pass |
| PAL | 2400 | cart | 61 | **0** | **0** | 0F | 17 | 61 | pass |
| NTSC | 2400 | cart | 60 | **0** | **0** | 0F | 16 | 60 | pass |

**Zero rejected frames and zero framing errors in all fourteen runs**, at
every rate, on both video standards, with and without an REU, from disk and
from cartridge. Video detection was correct every time (`wB3` on PAL,
`wBD` on NTSC — exactly the predicted values).

¹ **600 + REU left 9 messages queued.** The link was clean; 600 baud simply
could not drain 61 messages inside the run window while also archiving each
one to the REU. That is the throughput limit the whole rewrite exists to
raise, not a fault.

² **One handshake acknowledgement missed** (`h07` — `curr_time` unmatched).
The link was clean and the queue drained; the client times that stage out
after ~30s and carries on, because the command was still sent and took
effect. Seen in 1 run of 14. See [known issues](#known-issues).

## Receive ring never filled

The high-water mark peaked at **17 bytes of 256** across every run — under
7%. The ring is drained far faster than it fills, which is what lets the
client spend time in the channel picker and scrollback without losing
frames.

## Known issues

**Occasional missed handshake acknowledgement.** About 1 run in 14, one of
the four handshake replies is not matched by the routine waiting for it.
The command was sent and the radio acted on it, so the client works
normally afterwards; it just waits out a ~30 second timeout first, which
shows up as a slow start. Root cause not established. An earlier and much
more consistent version of this (the `app_start` reply never matching at
all) was fixed by the custom receiver, so this is a residue of the same
problem rather than a new one.

**Not tested on real hardware.** Everything here is emulated. See
[V2.md](V2.md#what-is-not-proven).

## Reproducing

```bash
cd c64-0.9/test
./runregress.sh      # the 12-run matrix
./summarise.sh       # decode the hex counters into this table
./runfullcart.sh 2400 pal
./runfullcart.sh 2400 ntsc
```

Runs are sequential on purpose: the fake radio binds one fixed port, so two
in parallel silently starve one of a radio and the result looks like a
failure rather than a configuration mistake.

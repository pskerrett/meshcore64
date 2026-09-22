# Link speed test — 22 September 2026

**Question:** can MeshCore 64 run faster than 600 baud?

**Answer: no.** 1200 loses messages on every run and never stabilises; 2400
does not receive at all. 600 stays the only usable rate. This retest was run
because the previous one was scored badly, and because a character-corrupting
bug had been found in between — neither turned out to rescue 1200.

---

## Why retest at all

The September 0.95b retest recorded a lesson worth repeating: *"at 1200 every
aggregate counter read healthy while characters were corrupt."* That test
counted frames and syncs. Frame counts tell you a payload parsed, not that its
bytes were right, so the result deserved rechecking with better instruments.

There was also a specific theory to kill. A bug had been found and fixed that
stripped characters by collapsing 3-byte UTF-8 punctuation, which shifted every
payload offset after it. If that bug had been live during the baud test, the
1200 "corruption" might have been the bug rather than the wire speed.

**It wasn't.** The collapsing converter needed a `cmp #226` test for the UTF-8
lead byte (`$E2`), and that byte pair is absent from v0.95b, v1.0 and current
HEAD. It only ever existed transiently in a working tree during the REU beta —
after the baud test. The converter was strictly 1:1 then, exactly as it is now.
The theory was reasonable; the dates don't support it.

## What is different this time

1. **A rejected-frame counter (`rj`).** The client now applies three
   plausibility tests to anything arriving as a channel message — channel index
   ≤ 39, length ≥ 12, and `txt_type` ≤ 2 — and counts what it throws away.
   `rj` is the direct measure of "the link is corrupting frames", and it needs
   no interpretation. It is visible on **F3** in normal use.
2. **A fixed known string sent every tick**, so the radio scores the C64's
   *transmit* path independently of receive.
3. **Screen contents read as decimal screen codes**, not screenshots. The C64
   font renders UTF-8 punctuation as `.` and makes `)` and `>` near-identical,
   so glyphs cannot distinguish a real message from garbage.
4. **REU and non-REU as a deliberate axis.** REU DMA halts the CPU. A 960-byte
   `lpage` repaint is roughly 1ms. At 600 a bit is 1.67ms, so a repaint fits
   inside one bit. At 1200 a bit is 0.83ms and **a repaint is longer than an
   entire bit.** That failure mode did not exist when this was last measured,
   because there was no REU code at all.

## Results

Eight runs. 55 messages pushed by the radio in each. `rj` = frames rejected as
implausible; `H` = handshake stage reached, 4 is complete.

| baud | REU | delivered | queue left | **rj** | H | TX string |
|---|---|---|---|---|---|---|
| **600** | no | **58** | **0** | **0** | 4 | perfect |
| **600** | 512K | **58** | **0** | **0** | 4 | perfect |
| 1200 | no | 34 | 24 | 8 | 4 | perfect |
| 1200 | 512K | 25 | 33 | 4 | **3 — never completed** | perfect |
| 1200 (repeat) | no | 48 | 10 | 8 | 4 | perfect |
| 1200 (repeat) | 512K | 40 | 18 | 6 | 4 | perfect |
| 2400 | no | **1** | 57 | 0 | **0 — never started** | perfect |
| 2400 | 512K | **1** | 57 | 0 | **0 — never started** | perfect |

### 600 baud is clean

Everything delivered, queue drained to zero, **zero** rejected frames, and the
channel name read back off the radio renders as `Public` — that string is
received text, so it is an end-to-end character check, not just a frame count.

### 1200 baud fails, and fails inconsistently

It half-works, which is the worst possible outcome. Between 10 and 33 of 55
messages never arrived, and `rj` sat at 4–8 every run: frames *were* arriving
and being thrown away as corrupt. The two trials disagreed sharply (34 vs 48
delivered), so this is not a stable "slightly degraded" mode — it is
run-to-run luck.

Worth noting what this would look like on a real radio **without** the `rj`
counter: the plausibility guards now silently discard corrupted frames instead
of painting them as garbage. The screen would look fine. Messages would just
quietly go missing. That is a more dangerous failure than the visible garbling
seen in September, and it is the reason the counter was added.

### 1200 + REU is consistently worse than 1200 alone

25 vs 34, and 40 vs 48. One run never completed the handshake at all (H3). This
matches the DMA arithmetic above: at 1200 a repaint is longer than a bit time,
so a repaint reliably eats at least one bit. Anyone running an Ultimate II+ —
cartridge and REU together — is in exactly this configuration.

### 2400 baud does not receive

One frame in the entire run, handshake stage 0, `rj` 0 — nothing ever parsed as
a frame, so there was nothing to reject. Receive is simply dead.

### Transmit is fine at every rate

The fixed string `abcdefghijklmnopqrstuvwxyz0123456789` arrived byte-perfect in
**all eight runs**, including both 2400 runs where receive was dead.

This is a new and clean result: **only the receive path fails.** It makes
sense. Transmit timing is the C64's own — it decides when to put bits on the
wire. Receive requires the KERNAL to sample *someone else's* bits, in software,
inside an NMI handler, guessing where each bit centre falls.

## Why receive is the limit

The C64 has no UART for the user port. The KERNAL bit-bangs RS-232 receive,
sampling every bit by hand inside an interrupt. At 600 a bit lasts 1.67ms; at
1200, 0.83ms; at 2400, 0.42ms. Every source of interrupt latency — badlines,
sprite DMA, another interrupt, REU DMA — costs the same absolute microseconds
while the budget halves each time the rate doubles. At 2400 the margin is gone
entirely.

No amount of client-side optimisation reaches this. The rendering path is
already ~6.6× faster than it was and entirely in machine code, and 1200 is no
better for it. Going faster means replacing the KERNAL receiver outright —
UP9600-style, driving the CIA shift register in hardware — which is a different
and much larger project.

## Conclusion

**600 baud stays.** 1200 is not "slightly lossy", it is unreliable in a way
that varies run to run and now fails silently. 2400 does not work at all. The
character-stripping bug was not the cause of the earlier 1200 failures, and
fixing it changed nothing here.

## Reproducing

```bash
cd c64-0.9/test
BC=/path/to/vs64/tools/bc.py ./runbaud2.sh   # 600 and 1200, both REU configs
BC=/path/to/vs64/tools/bc.py ./runbaud3.sh   # 2400, and 1200 repeat trials
```

Both use the `--baudtest` build from `mkchtest.py`, which reports `rj`, the
fixed TX string and screen contents over the link itself. Runs are sequential
on purpose: the fake radio binds one fixed port, so two in parallel silently
starve one of a radio and the result looks like a failure.

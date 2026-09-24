# The custom RS-232 driver at 600 baud

## What we know

| | result |
|---|---|
| v1.2d, KERNAL RS-232, 600 | works (proven, long-standing) |
| v2.2d, KERNAL RS-232, 600 | **connects**, then stalls after a while |
| v2.2d, our driver, 2400 | never connects |
| v2.2d, our driver, 600 | not yet tried on hardware |

The KERNAL build connecting is the important result. It proves the
wiring, the BLE 600 firmware, the client, the frame protocol and the
cartridge are all sound. **The fault is in our RS-232 driver.**

## What is ruled out, and why

**`latadj`.** The NMI-latency allowance was tuned only in an emulator, so
it was the obvious suspect. At 600 baud it cannot be the cause: a bit is
1642 cycles (PAL) or 1705 (NTSC), and being 275 cycles out samples 14%
early — comfortably inside the bit, and the offset is constant rather
than accumulating. It would matter at 2400. It cannot explain 600.

**Bit period.** PAL/NTSC selection was checked and is correct, and the
machine reports NTSC on its own boot screen, so it is using 1705.

**Signal polarity.** Ours is mark-high, space-low on PA2. Both our driver
and the KERNAL decode correctly in VICE, which only accepts one
convention, so the two agree.

## What is almost certainly wrong

**`txwait` timed every transmitted bit by polling `$DD0D`.**

```asm
txwait: lda C2ICR      ; <-- reading this register CLEARS it
        and #1
        beq txwait
```

On a real 6526, an interrupt flag is lost if a read of the register lands
in the same cycle the flag is being set. This is documented, and is
exactly why polling that register for timing is warned against.

The loop reads about every 10 cycles, so roughly **one bit in ten loses
its underflow** and runs on to double length. At 10 bits a byte and 11
bytes in a handshake frame, essentially no frame ever leaves the C64
intact. The radio never receives a valid `APP_START`, so it never replies,
and the client sits on "connecting" for ever.

This explains all three observations at once:

- **why the KERNAL works** — its transmit is interrupt-driven and never
  polls that register
- **why every emulator test passed** — VICE does not reproduce the race
- **why it fails completely rather than intermittently** — at ~10% per
  bit, a whole frame surviving is the unlikely case

## A second, smaller bug

After transmitting, the driver cleared the interrupt latch before
re-arming the receiver. FLAG is wired to the *incoming* line, so nothing
we send can latch a false edge — the only edge that can be sitting there
is **the radio starting its reply** in the gap between our last stop bit
and that instruction. Clearing it threw the reply away.

It is now cleared only when the line is idle high. Low means a start bit
is under way, and the edge is kept; taking the interrupt a few cycles late
costs nothing at 600 baud, while losing the first byte of an answer costs
everything.

Note the *receive* path genuinely must clear, and does: during a byte the
data bits' own 1→0 transitions latch FLAG, so re-arming without clearing
takes an immediate false trigger.

## A competing explanation, which may be the real one

**There is no retry anywhere in the handshake.** `waitop` returns when it
times out and the client carries on with nothing, so a single lost
`APP_START` strands it permanently.

And the timing differs in a way that is pure accident. Our driver build
waits 1.2 seconds before speaking. The KERNAL build waits 3.2 — its
two-second post-`OPEN` settle *on top of* the same 1.2. The C64 boots from
cartridge in about two seconds; the radio has Bluetooth, a display and a
LoRa front end to bring up and takes longer.

If the radio simply is not listening yet, the first frame is lost, nothing
retries, and the client waits forever. That looks *identical* to the
failure being chased — and it would mean the KERNAL build connects for an
incidental reason, being slower to start talking, rather than because of
anything about the driver.

This is tested separately, as **fixC**: unchanged driver, three-second
wait, four attempts at eight seconds each instead of one at thirty.

| result | conclusion |
|---|---|
| fixA works, fixC does not | the interrupt-register race |
| fixC works, fixA does not | we were talking too early, with no retry |
| both work | either is sufficient; ship both |
| neither | both wrong — read `n`/`b` on F3 |

## The candidate fixes

Both remove the register read from the timing loop. They are independent
mechanisms, so if one has a flaw the other is unlikely to share it.

**A — watch the counter.** Timer A stays continuous; `txwait` reads the
counter's high byte and returns when it jumps back up, which only happens
on reload. Reading a counter has no side effects. Keeps the property that
there is no per-bit reload and therefore no accumulating error.
*Limitation:* needs a bit period over 256 cycles, so the high byte
actually moves. Now enforced at build time — a 9600 build is refused
rather than hanging.

**B — one-shot and poll the control register. 600 BAUD ONLY.** Each bit arms a one-shot
and waits for the CIA to clear the START bit itself, which it does on
timeout. Reading the control register has no side effects either, and
there is no period limitation. *Cost:* the arming sequence, about 25
cycles, is added to each bit — 1.5% at 600 baud, drifting the last bit
boundary 15% of a bit. The receiver samples at bit centres, so that is
comfortably inside.

**Measured:** A works at 600 *and* 2400 in the emulator. B works at 600
and **fails completely at 2400** — its ~25 cycles of arming per bit is
1.5% at 600 but 6% at 2400, drifting the last bit boundary 60%, outside
tolerance. So B is a 600-baud fallback only, and A is the primary
candidate: it preserves exact bit timing and is the only one with a route
to 2400.

## What these builds cannot tell you

All three pass in VICE: full handshake, 38 messages received, nothing
transmitted that was not typed. **That proves only that the fixes break
nothing.** The bug they target is one the emulator does not reproduce, so
the emulator cannot confirm the cure either. Only the hardware can.

That is why all three builds carry diagnostics.

## The builds, and how to read them

Each puts two counters on **F3**, next to the existing `frames/rej/hw`:

```
frames/rej/hw XX XX XX nXX bXX
```

- **`n`** — start bits seen on the FLAG line: the radio's line physically
  moving, counted before any decoding
- **`b`** — bytes that reached the receive ring

| what F3 shows | what it means |
|---|---|
| `n00 b00` | nothing arriving electrically — the radio is not answering, so our **transmit** is still not understood |
| `n` climbing, `b00` | edges arrive, no byte assembles — **receive sampling** is wrong |
| `n`,`b` climbing, `frames 00` | bytes arrive but garbled — timing is close but not right |
| `frames` climbing | working |

| file | driver |
|---|---|
| `meshcore64-v2.2d-600-base.crt` | **unchanged** — the control. Does the current driver work at 600 at all? |
| `meshcore64-v2.2d-600-fixA.crt` | counter-watch, continuous timer — **try this first** |
| `meshcore64-v2.2d-600-fixB.crt` | one-shot and control-register poll |

Pair all of them with `firmware-heltec-v3-ble-600-merged.bin`. Both halves
must be 600.

Running **base** first is worth the two minutes: if it connects, the
driver was never broken at 600 and the whole problem is specific to 2400,
which points back at `latadj` and changes what we do next.

## The KERNAL build's stall

Not chased, on instruction, but recorded. The likely mechanism is that
`CHROUT` to the RS-232 device blocks while the KERNAL's 256-byte output
buffer drains, and at 600 baud a full frame takes about three seconds to
clock out. Meanwhile the receive buffer is also 256 bytes and is filling.
A large frame in each direction at once is enough to wedge it. Our own
driver has the same shape of risk — it masks the receiver for the whole
of an outgoing frame — but handshake frames are 11 bytes, so it cannot
explain a failure to connect.

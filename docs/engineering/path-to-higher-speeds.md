# Path to higher speeds (meshcore64, > 600 bps)

> **Step 0 for whoever executes this plan:** copy this file verbatim to
> `/data/meshcore/c64-0.9/path to higher speeds.md`. That is the
> deliverable the user asked for. Later agents read it from there.
> Also create the results tree described in §1a
> (`/data/meshcore/c64-0.9/speed/{reports,logs,shots,builds}` and
> `speed/INDEX.md`).

---

## 1. Context: why this exists

The C64 client (`c64-0.9/ml/mlfull.py`, shipped as v2.3.3) talks to the
Heltec V3 radio over the user port at **600 baud**, using the C64 KERNAL's
RS-232 code. The goal is **2400 baud (4x)**.

Two facts set the limits:

- **The KERNAL cannot go faster.** It was tested at 1200 with a pure-ML
  client. The receive buffer peaked at 8 of 256 bytes, yet frames were
  still corrupt, so the KERNAL is mis-sampling bits. Do not retest the
  KERNAL above 600.
- **Our own driver was 4x faster in VICE but failed on real hardware.**
  `mlfull.py`'s "d" driver did 600/1200/2400 in VICE with zero errors. On
  the user's real NTSC C64 it **never received a single valid frame, even
  at 600**. On 24–25 Sep 2026 the user flashed about 20 diagnostic carts.
  The work was then tabled; its notes are in
  `c64-0.9/ftproot/archive/NOTES.md`.

### What was proven on real hardware (do NOT re-test these)

| fact | evidence |
|---|---|
| Wiring, cart, radio firmware and protocol are good | the KERNAL builds connect |
| **Our TRANSMIT works** | `hybrid-ourTX` (our TX + KERNAL RX) connects, repeatably |
| **Our RECEIVE is the fault** | that is the only difference between the working and failing builds |
| The line carries clean 600-baud data | `baudmeter`: shortest low pulse = 1700 cycles (expected 1705); longer pulses are whole multiples |
| The line idles high and quiet | `scopeidle` reads all `ff` |
| Our NMI receiver yields garbage | `rxprobe`: 16 bytes, all `00`, from a ~70-byte reply |
| It is not the bit period | `sweep` covered ±25% and found nothing |
| It is not RTS/DTR, the lamps, or the timing constants | `rxprobe2`, `fixF`, and constants dumped from the built image |
| F3 counters on hardware (fixD) | `N=ff` (edges, saturated), `B=97` bytes, `G=d4` = 212 "glitch" edges rejected, 0 frames |

### Root cause, found while writing this plan (high confidence, not yet hardware-verified)

On a real 6526 CIA, **ICR data bits latch whether or not that source is
enabled in the mask.** The mask only decides which latched bits pull the
interrupt line. FLAG is wired to RXD, so **every falling edge inside a
data byte sets ICR bit 4** (FLAG), even while only Timer B is enabled.

Our handler (`nmih`, `mlfull.py` ~line 1018, and identical in **every**
`ml600*.py` variant) does this:

```asm
nmih:   ...
        lda C2ICR           ; read = acknowledge
        sta ICRSV
        and #16             ; FLAG?   <-- checked FIRST, and NOT masked
        beq nmtb
        ; ...treat as a NEW START BIT: reload timer, BITCNT=9
```

Here is what happens on hardware. A Timer B sample NMI fires after a
1→0 data transition. The ICR read then shows both TB (bit 1) and FLAG
(bit 4). The handler checks FLAG first, so it restarts the byte. Bytes
only complete during long runs with no falling edges, such as null bytes
and stop/idle bits. That produces a few bytes, mostly `00`, with saturated
edge counts. **That matches every hardware reading.**

The KERNAL does not have this bug. Its NMI handler at `$FE72` (bytes
dumped from `/usr/share/vice/C64/kernal-*.bin`) is:

```
FE72  98        TYA          ; Y = ICR snapshot
FE73  2D A1 02  AND $02A1    ; ENABL: keep ONLY the sources that are enabled
FE76  AA        TAX
```

**VICE hides the bug** because its userport RS-232 (`rsuser`) pulses
FLAG once per byte, at the start bit. It does not pulse FLAG on every
data edge. The mid-byte FLAG latch never happens there, so every VICE
run passed. (This VICE behaviour is inferred from the results. Stage 1
step 1 verifies it in the source.)

This also explains why `latadj` came out at ~275 in VICE. Real NMI
latency is ~30–80 cycles. Treat 275 as a VICE artifact and retune on
hardware (Stage 3).

---

## 1a. Results directory: every agent writes here

All results go in **`/data/meshcore/c64-0.9/speed/`**, so that a
reviewing agent can audit the whole effort later without re-running
anything. This is mandatory. A step whose results are not filed here
counts as not done.

```
speed/
  INDEX.md                 one line per report, newest last:
                           <date> | <stage.step> | <PASS/FAIL/BLOCKED> | <file> | <one-line result>
  reports/<YYYY-MM-DD>-s<stage>.<step>-<slug>.md   one per step
  logs/      raw output: sim runs, VICE radio logs, build logs (never trimmed)
  shots/     VICE screenshots, plus photos/text the user sends from hardware
  builds/    the exact .prg/.crt/.bin sent to the user, plus an md5 next to each
```

Every report uses this template, and it must say what really happened:

```markdown
# s<stage>.<step> <title>
- Date / agent session:
- Goal (quote the plan step):
- What I changed (files + patch script name, or "none"):
- Commands run (exact, copy-pasteable):
- Result: PASS / FAIL / BLOCKED. Evidence: the numbers, the decoded bytes,
  paths into logs/ and shots/
- What the user reported (verbatim, for hardware steps):
- Surprises / things that contradict this plan:
- Next step I recommend:
```

Rules:
- Write the report **before** moving to the next step, and record
  failures as well as passes. A failed hypothesis gets its own report;
  that is what was missing on 24 Sep.
- Hardware results: paste the user's exact words and readouts. Do not
  paraphrase them.
- Never delete or overwrite an earlier report. Supersede it with a new
  report that links back.
- If this plan turns out to be wrong somewhere, say so in "Surprises".
  Do not quietly edit the plan.

## 2. Hard rules for every agent on this

1. **No firmware changes without asking.** See memory
   `meshcore64_no_firmware_changes.md`. Stage 2 (600) needs **no**
   firmware change. Any rate above 600 needs the radio flashed with a
   matching image. Ask the user before flashing or building any firmware.
   A prebuilt BLE 2400 image already exists at
   `/data/meshcore64/firmware-heltec-v3-2400-merged.bin` (from 23 Sep,
   1.17.1 + serial patch, `HW_SERIAL_BAUD_RATE=2400`). Ask the user
   whether to use it as-is or rebuild it. Never run `pio` on your own.
2. **VICE cannot validate receive.** A VICE pass proves only that nothing
   else broke. Receive correctness comes from the simulator in Stage 1
   and then from real hardware.
3. **The user flashes carts by hand, so each hardware build has a cost.**
   Ship each one with an on-screen self-diagnosis. If it fails, the
   failure must still say *where*. Give each build a one-line "what to
   send me back".
4. **Change one variable per hardware build.** Do not stack fixes.
   Combining changes confounded the 24 Sep night (lamps vs. driver).
5. **Read the bytes, not the counters.** Healthy-looking counters have
   hidden corrupt text before. Success means a known reply decodes
   byte-for-byte (`3E len 00 05 …` for APP_START → SELF_INFO) *and*
   messages render as correct text.
6. **Never drive PB1/PB2 low after the port is up.** Set DDRB absolutely
   (`lda #120 / sta $DD03`), never read-modify-write.
7. **Check that every build step succeeded before publishing.** A `| tail`
   once hid a failed build, and a stale cart went out. Check exit codes
   and `cmp`/md5 the published file.
8. Every release ships `.prg` + `.crt` + `.bin`. Publish through
   `c64-0.9/ftproot/` + `./ftp-sync.sh`. The user loads from FTP on an
   Ultimate II+ at `/builds`.
9. The user's machine is **NTSC**. Test NTSC first. Bit periods are
   NTSC (1,022,727 Hz) 600 = 1705, 1200 = 852, 2400 = 426 cycles, and
   PAL (985,248 Hz) 1642, 821, 411. Load CIA timers with **N−1**: a CIA
   counts N…0, which is N+1 cycles.

---

## 3. Stages

### Stage 1: Prove the bug in a simulator that models real hardware (no user involvement)

Goal: a test harness that **fails on the old handler** (reproducing the
hardware's all-zeros) and passes on the fixed one. Without this we are
back to guessing from VICE.

1. **Verify the VICE claim.** Get VICE 3.7 source (tarball:
   `https://downloads.sourceforge.net/project/vice-emu/releases/vice-3.7.tar.gz`)
   into a fresh scratch dir. Find where userport RS-232 sets the CIA2 FLAG
   (grep `rsuser`, `set_flag`, `start_bit`). Record whether FLAG fires per
   byte or per edge. If it fires per edge, the explanation above is wrong
   about VICE: write that down. The fix still mirrors the KERNAL, so
   continue.
2. **Build `c64-0.9/ml/rxsim.py`.** Use `py65` (`python3 -m venv
   <scratch>/venv && <scratch>/venv/bin/pip install py65`). It must:
   - Load the assembled driver bytes (`serini`, `nmih`, and RBUF/RHEAD
     state) from the built `.prg` or the assembler output.
   - Model CIA2 just enough: Timer B (one-shot and continuous, force load,
     N+1 counting), and ICR semantics. **Data bits latch regardless of
     mask. A read returns them and clears them. The NMI line asserts only
     when (data & mask) ≠ 0. The 6502 NMI is edge-triggered** (falling
     edge of the line only). Model FLAG as **set on every falling edge of
     RXD**, and PB0 bit 0 = RXD.
   - Step the CPU cycle by cycle with py65's cycle counts. Inject NMI
     latency of 0–7 cycles for instruction completion plus random 0–43
     cycle badline stalls.
   - Drive RXD with a real 8N1 waveform of a recorded radio reply. Use the
     fakeradio SELF_INFO / DEVICE_INFO frame bytes from
     `c64-0.9/test/` or `docs/serial-protocol.md`. Send bytes back to back
     with no gaps, which is the worst case. Add ±1% baud error on the
     sender.
   - Report bytes received vs. sent, byte-exact match, and frame errors.
3. **Acceptance for the simulator itself:** the **current** `nmih` at 600
   must fail (few bytes, mostly `00`, like the hardware). If it passes,
   the model is wrong. Fix the model before going further.

### Stage 2: Fix the receiver and prove it at 600 on hardware (no firmware change)

1. **Fix `nmih` in `mlfull.py`** (the driver build, not `mlk22.py`). Do
   it as a patch script, `ml/patch234.py` (the convention: assert each
   anchor count, then `replace`). Changes:
   - Add a shadow byte `NMIEN` holding the currently enabled CIA2 NMI
     sources (`$10` = FLAG, `$02` = Timer B). Every place that writes the
     mask must also update `NMIEN`: `serini` (`#144` → `$10`), the
     start-bit path (`#130` → `$02`), `nmbyte` re-arm (`#144` → `$10`),
     `sendfr` exit (`#144` → `$10`), and `sendfr` entry (`#127` → `$00`).
   - Handler dispatch, mirroring the KERNAL:
     ```asm
     nmih:   pha / txa / pha / tya / pha
             lda C2ICR
             and NMIEN          ; ignore latched-but-disabled sources (KERNAL $FE73)
             sta ICRSV
             and #2             ; Timer B FIRST: we are mid-byte
             bne nmbit
             lda ICRSV
             and #16
             beq nmx            ; nothing of ours (e.g. RESTORE): just exit
             ; ... existing start-bit path (+ fixD start-bit verify if present)
     ```
   - Keep everything else the same: continuous Timer B after the first
     sample, the stop-bit check, and the transmit path. **TX is proven on
     hardware, so do not touch it.** (`hybrid-ourTX` used the
     ICR-polling `txwait`.)
   - Fix the timer loads to N−1 (rule 9). This is a tiny change that is
     correct either way.
2. **Simulator:** the fixed handler must receive the reply byte-exact at
   600, 1200 and 2400 (NTSC and PAL), over at least 1000 randomized runs
   of jitter. Record the passing `latadj` window per rate. A
   minimum/maximum sweep is enough.
3. **VICE regression** (functionality only): the
   `c64-0.9/build231/run.sh` flow, NTSC, REU and no-REU, at 600. Expect
   about the same message counts as v2.3.3.
4. **Hardware build A: `mc64-600-rxfix-probe.crt`.** This is a stripped
   probe, based on the archived rxprobe idea. It boots straight into the
   driver, sends APP_START, waits 4 s, prints the first 32 received bytes
   plus the N/B/G/frame counters, then halts. Expected:
   `3E xx 00 05 …`. Ask the user for the `got:` line.
5. **Hardware build B: `mc64-v2.3.4d-600.crt`.** The full client on the
   fixed driver, 600 baud, with the **existing ble-600 firmware**. The
   user checks that it connects, sends and receives readable messages,
   **and stays up for 10+ minutes**.
6. **If build A still fails**, use this decision tree. Do not invent new
   theories:
   - All `00` again → the simulator model is missing something. Build the
     archived `pollrx` idea (interrupt-free receive: Timer A one-shot,
     poll CRA START bit) as the next probe. It was built on 24 Sep but
     **never run**.
   - Plausible bytes, wrong values → sample point. Run the Stage 3 latadj
     sweeper at 600.
   - Nothing at all → check `serini` (DDRB = 120, FLAG enable, NMI vector)
     against the working hybrid.

**Exit criterion for Stage 2:** build B works on the user's real C64 at
600 for 10+ minutes, with correct text.

### Stage 3: 2400 on hardware (needs the user's OK for firmware)

1. **Ask the user** whether to flash
   `/data/meshcore64/firmware-heltec-v3-2400-merged.bin`. Note on the
   1200 option: no 1200 image exists. Skip 1200 unless 2400 fails;
   building one needs permission too.
2. **Hardware build C: an automated `latadj` sweeper at 2400**
   (`mc64-2400-sweep.crt`). The old sweeper varied the **bit period**,
   which was the wrong axis. Keep the bit period fixed at 426 (NTSC) and
   sweep the **first-sample offset** (`latadj`) from 0 to 400 in steps of
   16. For each value, send APP_START, wait 2 s, and count byte-exact
   SELF_INFO replies over 3 tries. **Do not stop at the first success.**
   Print a pass/fail map of the whole range, then the centre of the
   passing window. Keep the wait counter in memory, not in X: `poll`
   clobbers X, which broke the last sweeper. Expect a window centred
   around 40–100. The VICE value of 275 is not trustworthy.
3. Bake the window centre in as the default `latadj` for NTSC. Derive
   PAL by the same rule, and say it is unverified unless the user has a
   PAL machine.
4. **Hardware build D: the full client at 2400.** Soak test: 30+ minutes
   on a live mesh. Busy `LOG_RX_DATA` floods are the worst case, because
   the radio streams up to 176 bytes back to back with **no flow
   control**, since the link is 2-wire. Watch the rejected-frame counter
   on F3. It should stay at 0, or very close.
5. If 2400 shows occasional rejects but not a failure, try these
   **client-side** levers first, in order:
   - (a) A shorter NMI handler: fewer pushes, so save only A and X.
   - (b) Make sure nothing else runs SEI for long stretches, such as REU
     DMA, screen scrolling or `menu` code. A disabled IRQ does not block
     an NMI, but REU DMA stalls the CPU.
   - (c) Check that the `poll` drain keeps up.

   Firmware-side 8N2 (two stop bits) would give extra slack per byte, but
   it is a firmware change, so propose it to the user rather than doing it.

### Stage 4: Ship

- The release build becomes the driver build at 2400 (or 600 if Stage 3
  stalls), paired with the matching firmware. Bump the banner to
  `v2.3.4d` (or the next number) in `mlfull.py` and the `mkkernal.py`
  mapping. Keep the KERNAL 600 build (`mkkernal.py` → `mlk22.py`) as the
  documented fallback pairing with ble-600.
- `cart/mkcart.py` → `.crt` + `.bin`. Publish to `ftproot/`, archive the
  previous release, `./ftp-sync.sh`, and verify with `cmp`. The README
  must state the **firmware pairing**: client and radio baud must match,
  otherwise the result looks like a dead link.
- Update memory: `meshcore64_cart_hardware.md` (BAUD section, root cause)
  and `meshcore64_v231.md` (where we left off). Push to GitHub only if
  asked.

### Out of scope: above 2400

4800 has been measured as failing even in VICE. A bit is about 213
cycles, and the handler (~70) plus a badline (43) leaves no margin.
Beyond that, the options are: blank the screen while receiving (not
acceptable for a chat client), or the **UP9600 cart mod** (three solder
bridges: PB0→SP2, PB0→FLAG2, PB7→CNT2), which is a hardware change. Do
not pursue either unless the user asks. 2400 = 4x is the target.

---

## 4. Critical files

- `c64-0.9/ml/mlfull.py`: driver build source. `serini` ~978, `nmih`
  ~1018, `txbyte`/`txwait`/`sendfr` ~1107–1177, `build()` ~7012.
  CLI: `python3 mlfull.py <ctrl 7|8|10> <out.prg> <blank> <testk> <latadj>`.
- `c64-0.9/ml/mkkernal.py` → `mlk22.py`: the KERNAL (600) build. Keep it
  working.
- `c64-0.9/ml/asm.py`: the assembler. After any change, check that
  `genml.py` is still byte-identical (md5
  `7419cee45cc1d8f44e62bb39323bba51`).
- `c64-0.9/ml/ml600fd.py`, `mlhybrid.py`, `mlrxprobe*.py`, `mlpoll.py`,
  `mlscope*.py`, `mlbaud.py`: the 24–25 Sep diagnostic sources. Reuse
  their probe/sweeper code; do not re-derive it.
- `c64-0.9/ftproot/archive/NOTES.md`: the full hardware findings log.
- `c64-0.9/build231/run.sh`, `runcrt.sh`, and `test/fakeradio.py`: the
  VICE harness.
- `/data/meshcore64/firmware-heltec-v3-2400-merged.bin` and
  `testing/firmware-heltec-v3-ble-600-merged.bin`: firmware pairings.

## 5. Verification summary

| stage | proof | who |
|---|---|---|
| 1 | `rxsim.py` fails on the old `nmih` in the way the hardware did | agent |
| 2 | sim byte-exact at all rates; VICE regression OK; probe shows `3E xx 00 05`; full client at 600 for 10+ min | agent, then user |
| 3 | sweeper pass-window map; full client at 2400, 30-min soak, ~0 rejects, readable text | user, with agent |
| 4 | published files `cmp`-verified; README names the firmware pairing | agent |

Sources: KERNAL `$FE72–$FE76` bytes dumped from the local VICE ROM;
[UP9600 / pagetable.com](https://www.pagetable.com/?p=1656) (badlines,
the 3-bridge mod, and George Hug's "Toward 2400", Transactor 9:3, 1989:
2400 with no hardware mods); [C64-Wiki RS-232](https://www.c64-wiki.com/wiki/RS232);
MOS 6526 datasheet (ICR: data bits are set regardless of mask).

# Index of results (one line per report, newest last)
# date | stage.step | PASS/FAIL/BLOCKED | file | one-line result
2026-10-10 | 1.1 | PASS | reports/2026-10-10-s1.1-vice-flag-behaviour.md | VICE fires FLAG once per byte (rsuser.c); hypothesis confirmed
2026-10-10 | 1.2 | PASS | reports/2026-10-10-s1.2-rxsim-reproduces-hardware.md | rxsim: old nmih 0/20 exact w/ real-silicon FLAG (matches hardware), 20/20 w/ VICE FLAG
2026-10-10 | 2.1 | PASS(sim) | reports/2026-10-10-s2.1-nmien-mask-fix.md | patch234: AND NMIEN + N-1 loads; sim 50/50 byte-exact at 600/1200/2400 under real-silicon FLAG model
2026-10-10 | 2.2 | PASS(sim) | reports/2026-10-10-s2.2-latadj-window-sim.md | 2400 window 240-320 (centre 280); 600 any. Plan claim '275 is VICE artifact' is WRONG: two handler latencies
2026-10-10 | 2.3 | PASS(VICE, noisy) | reports/2026-10-10-s2.3-vice-regression.md | reu identical old/new; noreu varies run-to-run even for old build
2026-10-10 | 2.4 | AWAITING-USER | reports/2026-10-10-s2.4-hardware-probe-built.md | probe + full client carts built, VICE 3/3 good; need real-C64 result
2026-10-10 | 2.5 | PASS(VICE) | reports/2026-10-10-s2.5-2400-test-carts-published.md | 2400-test full client + probe on FTP, cmp-verified; need 2400 firmware + hardware result
2026-10-10 | 3.1 | PARTIAL (HW) | reports/2026-10-10-s3.1-hardware-2400-probe-result.md | FIRST HW DATA: 2400 rx works except first start bit lost -> '12 01 05 01 16 16' FE=02 (decoded exactly); fix sendfr
2026-10-10 | 3.2 | PASS(sim) | reports/2026-10-10-s3.2-first-start-bit-fix.md | patch235: arm FLAG in last stop bit, no ICR reads/clears; sim lost-reply windows 59 -> 3 (impossible region); TX bytes unchanged
2026-10-10 | 3.3 | PASS (HARDWARE) | reports/2026-10-10-s3.3-hardware-2400-probe-PASS.md | v2.3.5d probe at 2400 on real C64: 3/3 selfinfo, 69 bytes, FE=00 -- first working own-driver receive
2026-10-10 | 3.6 | BUG FOUND | reports/2026-10-10-s3.6-hashtag-channel-zero-key-bug.md | user: other channels don't work; cause: C64 sets #channels with zero key (needs sha256(name)[:16]); full client at 2400 works on HW
2026-10-10 | 3.4 | NOTE (VICE) | reports/2026-10-10-s3.4-vice-driver-scan-stall.md | driver builds crawl in VICE channel scan, old+new identical; HW scans fine; suspect VICE RTS gating
2026-10-10 | 3.7 | PASS (sim+VICE) | reports/2026-10-10-s3.7-hashtag-key-fix.md | v2.3.6d: #channel blank key -> sha256(name)[:16] on C64; VICE shows 99d2280c.. for #open vs zeros before; on FTP
2026-10-10 | 3.7 | PASS (HARDWARE) | reports/2026-10-10-s3.7-hashtag-key-fix.md | user: 'Works in real hardware' -- #channels send/receive on v2.3.6d
2026-10-10 | 4 | SHIPPED | reports/2026-10-10-s4-release-v2.4b.md | v2.4b @2400 + splash credit on FTP (only release there); tests archived

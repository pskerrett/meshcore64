#!/usr/bin/env python3
"""
Tabulate a regression matrix from the client's own diagnostic lines.

The client periodically posts its counters as a channel message, so the
fake radio's log carries them verbatim. That is more trustworthy than
counting frames in the log, because these are what the C64 itself thinks
happened. The last line of a run is the one with the full totals.

Legend, from the builder in mlfull.py:
  n frames   r rejected   m messages   h handshake stage
  o receive-ring high-water mark (NOT an overrun count)
  e framing errors   v video (00 pal / 01 ntsc)   w raw frame measurement
  k unrecognised opcodes   p rejected at the length header
  u reu + shift   c current channel   l lines archived
"""
import glob, os, re, sys, time

FIELD = re.compile(r"([nrmhoevwkpucl])([0-9A-F]+)")


def counters(path):
    last = None
    for line in open(path, errors="replace"):
        if "C64 SENT" in line and "'n" in line:
            last = line
    if not last:
        return None
    body = last[last.index("'") + 1:last.rindex("'")]
    out = {}
    for k, v in FIELD.findall(body):
        out[k] = v
    return out


def label(path):
    b = os.path.basename(path)
    m = re.match(r"radio_full_(\d+)_(\w+?)_(pal|ntsc)\.log", b)
    if m:
        return m.group(3).upper(), m.group(1), m.group(2)
    m = re.match(r"radio_fullcart_(pal|ntsc)\.log", b)
    if m:
        return m.group(1).upper(), "2400", "cart"
    return None


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    # The runner reuses filenames across matrices, so a log left over from
    # an earlier build looks exactly like a fresh one. Anything much older
    # than the newest file in the set did not come from this run.
    paths = [p for p in sorted(glob.glob(os.path.join(here, "radio_full*.log")))
             if label(p)]
    if not paths:
        print("no logs found")
        return 1
    newest = max(os.path.getmtime(p) for p in paths)
    rows = []
    stale = []
    for path in paths:
        lab = label(path)
        if newest - os.path.getmtime(path) > 7200:
            stale.append(os.path.basename(path))
            continue
        c = counters(path)
        if not c:
            rows.append((lab, None))
            continue
        rows.append((lab, c))

    print("| video | baud | REU | msgs | rej | framing | unknown "
          "| hdr bad | handshake | ring hw | archived | result |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    bad = 0
    for (vid, baud, reu), c in rows:
        if c is None:
            print("| %s | %s | %s | — | — | — | — | — | — | — | — | "
                  "**NO DATA** |" % (vid, baud, reu))
            bad += 1
            continue
        # Pass/fail is r (frames rejected), e (framing errors) and the
        # handshake reaching 0F. Those mean data was lost or the link never
        # came up.
        #
        # o, k and p are reported but do not fail a run, and the reason is
        # not that they are inconvenient:
        #   o  the deepest the 256-byte receive ring ever got. It is a
        #      HIGH-WATER MARK, not an overrun count: poll() records
        #      max(RHEAD - RTAIL) and nothing is ever dropped. Read it as
        #      headroom -- 35 of 256 is 14% full.
        #   k  unrecognised opcodes, p  frames rejected at the length
        #      header. Both are the same known effect measured in the blind
        #      diagnostic: sendfr masks the receiver for the whole outgoing
        #      frame, so a push arriving mid-send is clipped. The clipped
        #      frame is dropped, and MeshCore's pull-based sync fetches the
        #      message on the next round. Neither existed as a counter when
        #      the v2.01 matrix ran, so there is no baseline for them.
        fails = [k for k in ("r", "e") if int(c.get(k, "0"), 16)]
        hs = c.get("h", "??")
        if hs != "0F":
            fails.append("h")
        ok = "pass" if not fails else "**check: " + ",".join(fails) + "**"
        if fails:
            bad += 1
        print("| %s | %s | %s | %d | **%d** | **%d** | **%d** | **%d** "
              "| %s | %d | %d | %s |"
              % (vid, baud, reu,
                 int(c.get("m", "0"), 16),
                 int(c.get("r", "0"), 16), int(c.get("e", "0"), 16),
                 int(c.get("k", "0"), 16), int(c.get("p", "0"), 16),
                 hs, int(c.get("o", "0"), 16), int(c.get("l", "0"), 16),
                 ok))
    print()
    if stale:
        print("SKIPPED as stale (left over from an earlier matrix): "
              + ", ".join(stale))
    print("%d of %d runs need a look." % (bad, len(rows)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

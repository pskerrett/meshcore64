#!/usr/bin/env bash
# Pure-ML client. Reports counters over the link every ~13s, driven by the
# jiffy clock so a dead link still yields numbers.
#   n=frames assembled  r=frames rejected  m=messages shown
#   h=handshake stage (04 = complete)  o=kernal rx buffer high-water mark
# o is the one that matters: if it climbs toward ff the 256-byte buffer is
# overrunning and the parser is desyncing.
cd "$(dirname "$0")"
RATE="${1:-600}"
case $RATE in 600) CTRL=7;; 1200) CTRL=8;; 2400) CTRL=10;; *) echo "bad rate"; exit 1;; esac
REU="${2:-none}"
INT="${3:-4}"
python3 ../ml/mlclient.py $CTRL "$PWD/mlclient.prg" >/dev/null
TAG="${4:-}"
LOG="radio_ml_${RATE}_${REU}${TAG}.log"
MC64_CHANNELS="0:Public,1:Test,2:Emergency" MC64_MSGINT=$INT \
  python3 fakeradio.py > "$LOG" 2>&1 &
RPID=$!
sleep 1
ARGS=""; [ "$REU" = "512" ] && ARGS="-reu -reusize 512"
timeout 620 xvfb-run -a x64sc -default -userportdevice 2 -rsuserdev 0 \
  -rsuserbaud $RATE -rsdev1 "127.0.0.1:25232" -rsdev1baud $RATE $ARGS \
  -autostart mlclient.prg -limitcycles 260000000 \
  -exitscreenshot "/tmp/ml_${RATE}_${REU}${TAG}.png" >/dev/null 2>&1
sleep 2
kill $RPID 2>/dev/null; wait $RPID 2>/dev/null
echo "===== ML client / ${RATE} baud / reu=${REU} ====="
echo "  msgs radio sent : $(grep -c 'TICKLE' "$LOG")"
echo "  frames delivered: $(grep -c '17 (' "$LOG")"
echo "  syncs from c64  : $(grep -c '<- cmd 10' "$LOG")"
echo "  reports:"
grep -o "C64 SENT on [^]]*" "$LOG" | sed 's/^/    /' | tail -6
echo "  final: $(tail -1 "$LOG")"
echo MLDONE

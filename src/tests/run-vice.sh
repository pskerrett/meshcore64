#!/usr/bin/env bash
# $1=prg $2=tag $3=cycles(M) $4=reu|noreu [env...] -- one VICE run, MACH=pal|ntsc BAUD=n env
PRG=$1; TAG=$2; CYC=$3; REU=$4; shift 4
R=""; [ "$REU" = "reu" ] && R="-reu -reusize 512"
env MC64_CHANNELS="${MC64_CHANNELS:-0:Public,1:Test,2:Emergency}" MC64_MSGINT=${MC64_MSGINT:-4} "$@" \
  python3 ../test/fakeradio.py > radio_$TAG.log 2>&1 &
RP=$!
sleep 1
timeout 900 xvfb-run -a x64sc -default -${MACH:-ntsc} -userportdevice 2 -rsuserdev 0 \
  -rsuserbaud ${BAUD:-2400} -rsdev1 "127.0.0.1:25232" -rsdev1baud ${BAUD:-2400} $R ${VEXTRA} \
  -autostart "$PRG" -limitcycles ${CYC}000000 \
  -exitscreenshot "shot_$TAG.png" >/dev/null 2>&1
sleep 1
kill $RP 2>/dev/null; wait $RP 2>/dev/null
echo "$TAG: getchan=$(grep -c 'GET_CHANNEL' radio_$TAG.log) contacts=$(grep -c 'GET_CONTACTS' radio_$TAG.log) sent17=$(grep -c '17 (' radio_$TAG.log) advert=$(grep -o 'ADVERT [a-z-]*' radio_$TAG.log | tr '\n' ' ')"

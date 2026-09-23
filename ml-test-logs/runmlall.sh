#!/usr/bin/env bash
# Full pure-ML sweep. Sequential on purpose: the fake radio binds one
# fixed port, so parallel runs silently starve one of a radio.
cd "$(dirname "$0")"
for spec in "600 none 4" "600 512 4" "1200 none 4" "1200 512 4" \
            "2400 none 4" "2400 512 4" "600 none 1" "1200 none 1"; do
  set -- $spec
  TAG=""; [ "$3" = "1" ] && TAG="_load"
  ./runml.sh "$1" "$2" "$3" "$TAG"
done
echo MLSWEEPDONE

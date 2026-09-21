#!/usr/bin/env bash
# Compile the C64 client:  meshcore64.bas -> meshcore64.prg
#
# NOTE the -c (crunch). It is not an optimisation, it is REQUIRED: the
# commented source compiles to ~36KB, which leaves ~2.2KB for variables
# while the arrays alone need ~2.8KB - the program dies with ?OUT OF
# MEMORY building a string. Crunched it is ~10KB, leaving ~28KB free.
# The .bas keeps every comment; only the compiled output is stripped.
#
# VS64's BASIC compiler is plain python3, no VSCode needed:
#   git clone https://github.com/rolandshacks/vs64
# then point BC at its tools/bc.py (or export BC=... in your shell).
set -euo pipefail
cd "$(dirname "$0")"

BC="${BC:-$HOME/vs64/tools/bc.py}"
if [ ! -f "$BC" ]; then
  echo "bc.py not found. Set BC=/path/to/vs64/tools/bc.py" >&2
  exit 1
fi

# bc.py needs a path with a directory component for its output.
# compile with comments intact, then strip them with our own tool. keeping
# the two steps separate means the comment-stripping is ours to maintain
# and anyone can run it on a build of their own: tools/crunch.py in out
python3 "$BC" -o "$PWD/meshcore64-full.prg" "$PWD/meshcore64.bas"
python3 "$PWD/tools/crunch.py" "$PWD/meshcore64-full.prg" "$PWD/meshcore64.prg"
echo "built: $PWD/meshcore64.prg"

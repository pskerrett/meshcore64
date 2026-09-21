#!/usr/bin/env bash
# Compile the C64 client:  meshcore64.bas -> meshcore64.prg
#
# NOTE the -c (crunch), which is bc.py's own comment stripper. It is not
# an optimisation, it is REQUIRED: the
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
python3 "$BC" -c -o "$PWD/meshcore64.prg" "$PWD/meshcore64.bas"
echo "built: $PWD/meshcore64.prg"

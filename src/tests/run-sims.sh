#!/usr/bin/env bash
# Run the 6502 simulator suites (needs: pip install py65). Each prints "FAILURES: 0" when it passes.
cd "$(dirname "$0")"
bad=0
for t in purgesim statsim routesim st3sim ndlsim flowsim findsim80 mirsim pendsim80 f3sim f7sim loadedsim georoundsim bgsim prunesim tworoundsim tssim regsim restsim ldsim; do
  r=$(python3 $t.py 2>&1 | grep -v '^;' | tail -1)
  echo "$t: $r"
  case "$r" in *"FAILURES: 0"*) ;; *) bad=1 ;; esac
done
exit $bad

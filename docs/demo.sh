#!/usr/bin/env bash
# Demo script for asciinema. Run with:
#   asciinema rec docs/demo.cast -c "bash docs/demo.sh"
#
# Then convert to GIF (e.g. with agg https://github.com/asciinema/agg):
#   agg docs/demo.cast docs/demo.gif --speed 1.5 --rows 32 --cols 110
set -euo pipefail

PS1='$ '
typewriter() {
  local line="$1"
  local delay="${2:-0.04}"
  printf '$ '
  for ((i=0; i<${#line}; i++)); do
    printf '%s' "${line:$i:1}"
    sleep "$delay"
  done
  printf '\n'
  bash -c "$line" || true
  sleep 1
}
clear

echo "# pl-winner — Premier League predictor + FPL recommender"
sleep 2
echo

typewriter "pip install pl-winner --quiet"
typewriter "pl-winner --version"
typewriter "pl-winner --help"
sleep 2
typewriter "pl-winner predict --runs 5000"
sleep 3
typewriter "pl-winner fixtures | head -15"
sleep 3
typewriter "pl-winner fpl 2>&1 | grep -A 6 'ILP-optimal'"
sleep 3

echo
echo "# Want the interactive UI?  →  pl-winner tui"
echo "# Web?                       →  pl-winner web (or: docker compose up)"
sleep 3

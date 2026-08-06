#!/usr/bin/env bash
#
# Run the suite against a throwaway postgres.
#
#   ./tests/run.sh                # run everything, then tear the stack down
#   ./tests/run.sh --keep         # leave it up afterwards (much faster re-runs)
#   ./tests/run.sh --down         # tear it down and exit
#   ./tests/run.sh -k enum -x     # anything else is passed straight to pytest
#
# Exits with pytest's status, so it can be used as a CI gate.

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)

# Run from the compose file's own directory rather than passing -f: an explicit
# -f turns off file discovery, and with it the automatic merge of an adjacent
# compose.override.yml (which is how the devcontainer injects its proxy CA).
compose() { (cd "$SCRIPT_DIR" && docker compose "$@"); }
down() { compose down -v --remove-orphans; }

keep=false
while true; do
  case "${1-}" in
    --keep) keep=true; shift ;;
    --down) down; exit 0 ;;
    -h | --help) sed -n '3,10p' "${BASH_SOURCE[0]}" | cut -c3-; exit 0 ;;
    *) break ;;
  esac
done

# also fires on ctrl-c / a failed build, so we never leak a running database
if ! $keep; then trap down EXIT; fi

status=0
compose run --rm --build test-release pytest "$@" || status=$?

if $keep; then
  echo "stack left running -- './tests/run.sh --down' to stop it"
fi

exit $status

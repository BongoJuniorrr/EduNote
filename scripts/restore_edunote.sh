#!/usr/bin/env bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -ne 2 ]]; then
  printf 'Usage: %s SNAPSHOT NEW_EMPTY_DESTINATION\nRestore is isolated; it never overwrites live data.\n' "$0" >&2
  exit 2
fi
python3 "${PROJECT_ROOT}/scripts/validation/backup_restore.py" restore --snapshot "$1" --destination "$2"

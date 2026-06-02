#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=0

if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
elif [[ "${1:-}" != "" && "${1:-}" != "--dry-run" ]]; then
  echo "Usage: $0 [--dry-run|--apply]" >&2
  exit 2
fi

cd "$ROOT"

mapfile -t FILES < <(
  find . \
    -path './venv' -prune -o \
    -path './.git' -prune -o \
    -type f \( \
      -name '*.bak*' -o \
      -name '*.log' -o \
      -name '*.log.*' -o \
      -name '*.tmp' -o \
      -name '*~' \
    \) -print | sort
)

if [[ "${#FILES[@]}" -eq 0 ]]; then
  echo "No local backup/log artifacts found."
  exit 0
fi

if [[ "$APPLY" -eq 0 ]]; then
  echo "Dry run. Re-run with --apply to delete these local artifacts:"
  printf '%s\n' "${FILES[@]}"
  exit 0
fi

printf '%s\0' "${FILES[@]}" | xargs -0 rm -f
echo "Deleted ${#FILES[@]} local backup/log artifact(s)."

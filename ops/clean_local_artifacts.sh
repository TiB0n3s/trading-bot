#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPLY=0
INCLUDE_LOGS=0
INCLUDE_SESSION_LOGS=0
INCLUDE_DB_BACKUPS=0
INCLUDE_CACHES=1
INCLUDE_BACKUPS=1

usage() {
  cat >&2 <<'EOF'
Usage: ops/clean_local_artifacts.sh [--dry-run|--apply] [options]

Default cleanup is intentionally conservative:
  - Python caches: __pycache__, *.pyc, *.pyo, .pytest_cache, .ruff_cache
  - local source backups: *.bak*, *.tmp, *~
  - excludes *.db.bak* and evidence logs unless explicitly requested

Options:
  --apply                 Delete selected artifacts.
  --dry-run               Print selected artifacts. Default.
  --include-logs          Include root/runtime *.log and *.log.* files.
  --include-session-logs  Include session_logs/ logs too.
  --include-db-backups    Include *.db.bak* files.
  --no-caches             Do not include Python/cache artifacts.
  --no-backups            Do not include local source backup artifacts.
  --help                  Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY=1
      ;;
    --dry-run)
      APPLY=0
      ;;
    --include-logs)
      INCLUDE_LOGS=1
      ;;
    --include-session-logs)
      INCLUDE_SESSION_LOGS=1
      INCLUDE_LOGS=1
      ;;
    --include-db-backups)
      INCLUDE_DB_BACKUPS=1
      ;;
    --no-caches)
      INCLUDE_CACHES=0
      ;;
    --no-backups)
      INCLUDE_BACKUPS=0
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  shift
done

cd "$ROOT"

TMP_FILE="$(mktemp)"
trap 'rm -f "$TMP_FILE"' EXIT

add_targets() {
  if [[ $# -gt 0 ]]; then
    printf '%s\n' "$@" >> "$TMP_FILE"
  fi
}

if [[ "$INCLUDE_CACHES" -eq 1 ]]; then
  while IFS= read -r path; do add_targets "$path"; done < <(
    find . \
      -path './venv' -prune -o \
      -path './.git' -prune -o \
      -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' \) -print
  )
  while IFS= read -r path; do add_targets "$path"; done < <(
    find . \
      -path './venv' -prune -o \
      -path './.git' -prune -o \
      -type f \( -name '*.pyc' -o -name '*.pyo' \) -print
  )
fi

if [[ "$INCLUDE_BACKUPS" -eq 1 ]]; then
  while IFS= read -r path; do add_targets "$path"; done < <(
    find . \
      -path './venv' -prune -o \
      -path './.git' -prune -o \
      -type f \( -name '*.bak*' -o -name '*.tmp' -o -name '*~' \) \
      ! -name '*.db.bak*' -print
  )
fi

if [[ "$INCLUDE_DB_BACKUPS" -eq 1 ]]; then
  while IFS= read -r path; do add_targets "$path"; done < <(
    find . \
      -path './venv' -prune -o \
      -path './.git' -prune -o \
      -type f -name '*.db.bak*' -print
  )
fi

if [[ "$INCLUDE_LOGS" -eq 1 ]]; then
  while IFS= read -r path; do
    if [[ "$INCLUDE_SESSION_LOGS" -eq 0 ]]; then
      case "$path" in
        ./session_logs/*)
          continue
          ;;
      esac
    fi
    add_targets "$path"
  done < <(
    find . \
      -path './venv' -prune -o \
      -path './.git' -prune -o \
      -type f \( -name '*.log' -o -name '*.log.*' \) -print
  )
fi

mapfile -t TARGETS < <(sort -u "$TMP_FILE")

if [[ "${#TARGETS[@]}" -eq 0 ]]; then
  echo "No selected local artifacts found."
  exit 0
fi

if [[ "$APPLY" -eq 0 ]]; then
  echo "Dry run. Re-run with --apply to delete these selected local artifacts:"
  printf '%s\n' "${TARGETS[@]}"
  exit 0
fi

printf '%s\0' "${TARGETS[@]}" | xargs -0 rm -rf
echo "Deleted ${#TARGETS[@]} selected local artifact(s)."

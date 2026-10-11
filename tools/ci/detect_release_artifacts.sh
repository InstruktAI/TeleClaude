#!/usr/bin/env bash
# Detect release evidence in runner-owned temporary directories.
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  printf 'Usage: %s <file|glob> <path-or-pattern>\n' "$0" >&2
  exit 2
fi
: "${GITHUB_OUTPUT:?GitHub step output file is required}"

present=false
case "$1" in
  file)
    if [[ -f "$2" ]]; then
      present=true
    fi
    ;;
  glob)
    if compgen -G "$2" >/dev/null; then
      present=true
    fi
    ;;
  *)
    printf 'Unknown artifact detection mode: %s\n' "$1" >&2
    exit 2
    ;;
esac

if [[ "$present" == true ]]; then
  printf 'present=true\n' >> "$GITHUB_OUTPUT"
fi

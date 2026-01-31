#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/Workspace"
APPLY=false
RENAME=false
IMPACT=false
HOME_DOTDIRS=false
HOME_DOTALL=false

usage() {
  cat <<'USAGE'
Usage: relocate-workspace-paths.sh [--root <dir>] [--apply] [--rename] [--impact] [--home-dotdirs] [--home-dotall]

Default is dry-run (no changes). Use --apply to edit files.
Use --rename to rename files/folders containing "Workspace-".
Use --impact to show a concise match preview per file.
Use --home-dotdirs to scan only dotfolders under your home directory.
Use --home-dotall to scan dotfiles and all files under dotfolders in your home directory.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="$2"; shift 2 ;;
    --apply)
      APPLY=true; shift ;;
    --rename)
      RENAME=true; shift ;;
    --impact)
      IMPACT=true; shift ;;
    --home-dotdirs)
      HOME_DOTDIRS=true; shift ;;
    --home-dotall)
      HOME_DOTALL=true; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown arg: $1"; usage; exit 1 ;;
  esac
done

if [[ ! -d "$ROOT" ]]; then
  echo "Root not found: $ROOT" >&2
  exit 1
fi

# Exclusions: generated/disposable artifacts and metadata only.
# This preserves behavior while avoiding needless churn and huge scans.
RG_EXCLUDES=(
  -g '!**/node_modules/**'
  -g '!**/.venv/**'
  -g '!**/venv/**'
  -g '!**/.virtualenvs/**'
  -g '!**/.git/**'
  -g '!**/.cache/**'
  -g '!**/dist/**'
  -g '!**/build/**'
  -g '!**/out/**'
  -g '!**/target/**'
  -g '!**/.next/**'
  -g '!**/.turbo/**'
  -g '!**/.pnpm-store/**'
  -g '!**/.npm/**'
  -g '!**/.yarn/cache/**'
)

PATTERN='(/Workspace|~/Workspace|Workspace-)'

SCAN_LABEL="$ROOT"
SCAN_PATHS=("$ROOT")
SCAN_EXCLUDES=("${RG_EXCLUDES[@]}")
RG_FOLLOW=()

if $HOME_DOTALL; then
  mapfile -t DOTDIRS < <(find "$HOME" -maxdepth 1 -mindepth 1 -name '.*' -type d -perm -u+rx -not -name '.Trash' -print)
  mapfile -t DOTFILES < <(find "$HOME" -maxdepth 1 -mindepth 1 -name '.*' -type f -perm -u+r -print)
  SCAN_PATHS=("${DOTFILES[@]}" "${DOTDIRS[@]}")
  SCAN_EXCLUDES=()
  SCAN_LABEL="$HOME (dotfiles + dotfolders recursive)"
  RG_FOLLOW=(--follow)
elif $HOME_DOTDIRS; then
  mapfile -t DOTDIRS < <(find "$HOME" -maxdepth 1 -mindepth 1 -name '.*' -type d -perm -u+rx -not -name '.Trash' -print)
  SCAN_PATHS=("${DOTDIRS[@]}")
  SCAN_EXCLUDES=()
  SCAN_LABEL="$HOME (dotfolders only)"
  RG_FOLLOW=(--follow)
fi

if $APPLY; then
  echo "[apply] Replacing in text files under: $SCAN_LABEL"
else
  echo "[dry-run] Scanning text files under: $SCAN_LABEL"
fi

# Find matching text files, including dotfiles/hidden paths.
mapfile -t FILES < <(rg -l --hidden --no-ignore "${RG_FOLLOW[@]}" "${PATTERN}" "${SCAN_EXCLUDES[@]}" "${SCAN_PATHS[@]}" || true)

if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No matching text files found."
else
  echo "Matched files: ${#FILES[@]}"
  if $APPLY; then
    perl -0pi -e 's#~/Workspace#~/Workspace#g; s#/Workspace#/Workspace#g; s#Workspace-#Workspace-#g' "${FILES[@]}"
    echo "Edits applied."
  else
    echo "Dry-run file list:"
    printf '%s\n' "${FILES[@]}"
    if $IMPACT; then
      echo ""
      echo "Impact preview (first 200 matches total):"
      rg -n --max-count 200 "${RG_FOLLOW[@]}" "${PATTERN}" "${SCAN_EXCLUDES[@]}" "${SCAN_PATHS[@]}" || true
    fi
  fi
fi

if $RENAME; then
  echo ""
  echo "Rename pass for names containing: Workspace-"
  # Find files/dirs whose names include the token; use -depth to avoid path issues.
  mapfile -t RENAMES < <(find "$ROOT" -depth -name '*Workspace-*')

  if [[ ${#RENAMES[@]} -eq 0 ]]; then
    echo "No names to rename."
  else
    if $APPLY; then
      for p in "${RENAMES[@]}"; do
        new="${p//Workspace-/Workspace-}"
        if [[ "$p" != "$new" ]]; then
          mv -n "$p" "$new"
          echo "renamed: $p -> $new"
        fi
      done
    else
      for p in "${RENAMES[@]}"; do
        new="${p//Workspace-/Workspace-}"
        if [[ "$p" != "$new" ]]; then
          echo "would rename: $p -> $new"
        fi
      done
    fi
  fi
fi

#!/usr/bin/env bash
# Bash completion for telec (uses telec's built-in completer).
#
# The Python CLI outputs completions in "value<TAB>description" format.
# This script extracts the value column, strips the "short, " prefix from
# flag pairs so only the long form is inserted, drops positional hints
# (<arg>) from the insertable list, and lets compgen filter by prefix.

_telec_complete() {
  local cur words
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  words=$(
    TELEC_COMPLETE=1 COMP_LINE="${COMP_LINE}" COMP_POINT="${COMP_POINT}" telec 2>/dev/null \
      | awk -F'\t' '
          { v = $1 }
          v ~ /^-[a-zA-Z], / { sub(/^-[a-zA-Z], /, "", v) }
          v ~ /^<.*>$/ { next }
          v != "" { print v }
        '
  )
  mapfile -t COMPREPLY < <(compgen -W "${words}" -- "${cur}")
  return 0
}

complete -F _telec_complete telec

#!/usr/bin/env zsh
# Zsh completion for telec (uses telec's built-in completer).
#
# The Python CLI outputs completions in "value<TAB>description" format.
# This script parses that and presents it to zsh's completion system.

_telec_complete() {
  local -a values descriptions
  local line value desc

  # Get completions from Python (format: value<TAB>description)
  while IFS=$'\t' read -r value desc; do
    [[ -n "$value" ]] || continue
    values+=("$value")
    descriptions+=("$value -- $desc")
  done < <(TELEC_COMPLETE=1 COMP_LINE="${BUFFER}" COMP_POINT="${#BUFFER}" telec 2>/dev/null)

  if (( ${#values[@]} )); then
    compadd -l -d descriptions -a values
  fi
}

compdef _telec_complete telec

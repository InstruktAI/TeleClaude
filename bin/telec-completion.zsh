#!/usr/bin/env zsh
# Zsh completion for telec (uses telec's built-in completer).
#
# The Python CLI outputs completions in "value<TAB>description" format.
# This script parses that and presents it to zsh's completion system.

_telec_complete() {
  local -a values descs descriptions
  local value desc max_len=0 padded

  # Get completions from Python (format: value<TAB>description)
  while IFS=$'\t' read -r value desc; do
    [[ -n "$value" ]] || continue
    values+=("$value")
    descs+=("$desc")
    (( ${#value} > max_len )) && max_len=${#value}
  done < <(TELEC_COMPLETE=1 COMP_LINE="${BUFFER}" COMP_POINT="${#BUFFER}" telec 2>/dev/null)

  # Build aligned descriptions
  for ((i=1; i<=${#values[@]}; i++)); do
    padded=$(printf "%-${max_len}s" "${values[$i]}")
    descriptions+=("$padded  ${descs[$i]}")
  done

  if (( ${#values[@]} )); then
    compadd -l -d descriptions -a values
  fi
}

compdef _telec_complete telec

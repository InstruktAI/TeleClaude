#!/usr/bin/env zsh
# Zsh completion for telec (uses telec's built-in completer).
#
# The Python CLI outputs completions in "value<TAB>description" format.
# This script parses that and presents it to zsh's completion system.
# Entries wrapped in <angle_brackets> are positional hints — shown but not inserted.

_telec_complete() {
  local -a values descs descriptions hint_descs
  local value desc max_len=0 padded has_hints=0

  # Get completions from Python (format: value<TAB>description)
  while IFS=$'\t' read -r value desc; do
    [[ -n "$value" ]] || continue
    values+=("$value")
    descs+=("$desc")
    (( ${#value} > max_len )) && max_len=${#value}
  done < <(TELEC_COMPLETE=1 COMP_LINE="${BUFFER}" COMP_POINT="${#BUFFER}" telec 2>/dev/null)

  # Separate insertable completions from positional hints (<arg>)
  local -a insert_values insert_descs
  for ((i=1; i<=${#values[@]}; i++)); do
    if [[ "${values[$i]}" == \<*\> ]]; then
      has_hints=1
      hint_descs+=("${values[$i]}  ${descs[$i]}")
    else
      insert_values+=("${values[$i]}")
      insert_descs+=("${descs[$i]}")
    fi
  done

  # Show positional hints as non-insertable header
  if (( has_hints )); then
    compadd -x "${(j:, :)hint_descs}"
  fi

  # Build aligned descriptions for insertable completions
  if (( ${#insert_values[@]} )); then
    local -a aligned_descs
    max_len=0
    for ((i=1; i<=${#insert_values[@]}; i++)); do
      (( ${#insert_values[$i]} > max_len )) && max_len=${#insert_values[$i]}
    done
    for ((i=1; i<=${#insert_values[@]}; i++)); do
      padded=$(printf "%-${max_len}s" "${insert_values[$i]}")
      aligned_descs+=("$padded  ${insert_descs[$i]}")
    done
    compadd -l -d aligned_descs -a insert_values
  fi
}

compdef _telec_complete telec

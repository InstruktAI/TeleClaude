#!/usr/bin/env zsh
# Zsh completion for telec (uses telec's built-in completer).
#
# The Python CLI outputs completions in "value<TAB>description" format.
# This script parses that and presents it to zsh's completion system.
# Entries wrapped in <angle_brackets> are positional hints — shown but not inserted.

_telec_complete() {
  local -a descriptions hint_descs
  local value desc escaped_value

  # Get completions from Python (format: value<TAB>description)
  while IFS=$'\t' read -r value desc; do
    [[ -n "$value" ]] || continue
    if [[ "$value" == \<*\> ]]; then
      hint_descs+=("$value  $desc")
    else
      escaped_value="${value//\\/\\\\}"
      escaped_value="${escaped_value//:/\\:}"
      descriptions+=("$escaped_value:$desc")
    fi
  done < <(TELEC_COMPLETE=1 COMP_LINE="${BUFFER}" COMP_POINT="${#BUFFER}" telec 2>/dev/null)

  # Show positional hints as non-insertable header
  if (( ${#hint_descs[@]} )); then
    compadd -x "${(j:, :)hint_descs}"
  fi

  if (( ${#descriptions[@]} )); then
    _describe 'telec command' descriptions
  fi
}

compdef _telec_complete telec

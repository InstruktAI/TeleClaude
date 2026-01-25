#!/usr/bin/env zsh
# Zsh completion for telec (uses telec's built-in completer).

_telec_complete() {
  local -a completions
  completions=("${(@f)$(TELEC_COMPLETE=1 COMP_LINE="${BUFFER}" COMP_POINT="${#BUFFER}" telec)}")
  if (( ${#completions[@]} )); then
    local -a displays
    local item desc
    for item in "${completions[@]}"; do
      if [[ "$item" == tc_* ]]; then
        desc="tmux"
      elif [[ "$item" == <-> ]]; then
        desc="index"
      elif [[ "$item" == /* ]]; then
        desc="command"
      else
        desc="session"
      fi
      displays+=("${item}  (${desc})")
    done
    compadd -l -d displays -- "${completions[@]}"
  else
    compadd -a completions
  fi
}

compdef _telec_complete telec

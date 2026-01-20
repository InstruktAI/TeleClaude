#!/usr/bin/env bash
# Bash completion for telec (uses telec's built-in completer).

_telec_complete() {
  local cur
  COMPREPLY=()
  cur="${COMP_WORDS[COMP_CWORD]}"
  COMPREPLY=( $(TELEC_COMPLETE=1 COMP_LINE="${COMP_LINE}" COMP_POINT="${COMP_POINT}" telec) )
  return 0
}

complete -F _telec_complete telec

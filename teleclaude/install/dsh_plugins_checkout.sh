#!/bin/sh
# Ensure the local checkout of the TeleClaude dsh plugins repository exists.
# Which plugins a profile holds, and at which version, is decided only by the
# DeepSeek stack convergence (python -m teleclaude.install.deepseek_stack).
set -e
# A blank or whitespace-only DSH_HOME counts as unset, as the runtime resolves it.
dsh_home="${DSH_HOME:-}"
case "$dsh_home" in
  *[![:space:]]*) ;;
  *) dsh_home="$HOME/.dsh" ;;
esac
plugins_home="$dsh_home/plugins"

if [ -L "$plugins_home" ] || [ -d "$plugins_home" ]; then
  exit 0
fi
git clone https://github.com/InstruktAI/dsh-plugins.git "$plugins_home"

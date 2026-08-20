#!/bin/sh
set -e
dsh_home="${DSH_HOME:-$HOME/.dsh}"
plugins_home="$dsh_home/plugins"
extra_plugins="dsh-checkpoint-rewind"
install_cmd="$plugins_home/dsh_install_plugins_all_profiles.sh $extra_plugins"

if [ -L "$plugins_home" ] || [ -d "$plugins_home" ]; then
  echo "found existing plugins folder" >&2
  if [ -f "$plugins_home/install.sh" ]; then
    echo "frunning its dsh_install_plugins_all_profiles.sh" >&2
    $install_cmd
  else
    echo "no install script found in existing plugins folder, skipping install" >&2
  fi
else
  git clone https://github.com/InstruktAI/dsh-plugins.git "$plugins_home"
  $install_cmd
fi

#!/bin/sh
# Install the TeleClaude global DSH plugins (dsh-qa and
# dsh-checkpoint-rewind) into every EXISTING DSH profile. dsh-hooks is
# installed separately from the machine authoring source so its package-owned
# bundle patch remains authoritative.
#
# Invoked by bin/install.sh (setup_dsh_integration) after dsh is installed;
# may also be run manually. The loop only visits directories already present
# under $DSH_HOME/profiles — this script NEVER creates a profile (dsh plugin
# --profile X add auto-initializes missing profiles, which is why every target
# must exist first).
set -e
dsh_home="${DSH_HOME:-$HOME/.dsh}"
plugins="github:InstruktAI/dsh-plugins#main&path:/dsh-qa dsh-checkpoint-rewind"
for profile_dir in "$dsh_home"/profiles/*/; do
    [ -d "$profile_dir" ] || continue
    profile=${profile_dir%/}
    profile=${profile##*/}
    echo "Installing node modules for profile: $profile"
    dsh plugin --profile "$profile" install
    for plugin in $plugins; do
        echo "Adding plugin $plugin to profile: $profile"
        dsh plugin --profile "$profile" add "$plugin"
    done
done

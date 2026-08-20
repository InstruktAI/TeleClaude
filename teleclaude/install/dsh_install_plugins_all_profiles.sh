#!/bin/sh
# Install the DSH plugins into every EXISTING DSH profile.
#
# Invoked by bin/install.sh (setup_dsh_integration) after dsh is installed, and
# symlinked to $DSH_HOME/install-plugins.sh so it can also be run by hand.
#
# The plugin set is:
#   every package under $DSH_HOME/plugins/    installed as a file: ref, so the
#                                             local checkout stays authoritative
#   dsh-checkpoint-rewind                     third-party, from the registry
#   extras                                    comma-separated, from
#                                             $DSH_HOME/extra-plugins and the
#                                             arguments
#
# Profiles are the directories under $DSH_HOME/profiles that carry a
# package.json: this script NEVER creates a profile (dsh plugin --profile X add
# auto-initializes missing profiles, which is why every target must exist
# first), and the package.json guard keeps profiles/node_modules out.
#
# Example:
#   ~/.dsh/install-plugins.sh github:me/my-plugins#main&path:/one,other-plugin
set -e
dsh_home="${DSH_HOME:-$HOME/.dsh}"

plugins=""
for plugin_dir in "$dsh_home"/plugins/*/; do
    [ -f "$plugin_dir/package.json" ] || continue
    plugins="$plugins
file:${plugin_dir%/}"
done

plugins="$plugins
dsh-checkpoint-rewind"

extras=""
extra_file="$dsh_home/extra-plugins"
[ -f "$extra_file" ] && extras=$(cat "$extra_file")
old_ifs=$IFS
IFS=','
extras="$extras,$*"
IFS=$old_ifs
extras=$(printf '%s' "$extras" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; /^#/d' | grep -v '^$' || true)
[ -n "$extras" ] && plugins="$plugins
$extras"

for profile_dir in "$dsh_home"/profiles/*/; do
    [ -f "$profile_dir/package.json" ] || continue
    profile=${profile_dir%/}
    profile=${profile##*/}
    echo "Installing node modules for profile: $profile"
    dsh plugin --profile "$profile" install
    while IFS= read -r plugin; do
        [ -n "$plugin" ] || continue
        echo "Adding plugin $plugin to profile: $profile"
        dsh plugin --profile "$profile" add "$plugin"
    done <<INNER
$plugins
INNER
done

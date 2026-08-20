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

# A profile that cannot be installed into (a stale pnpm store, a broken
# package.json) is reported and skipped: one unusable profile never withholds
# the plugins from the others. Failures are counted and surface in the exit
# status, so the installer still reports the pass as failed.
failures=0
for profile_dir in "$dsh_home"/profiles/*/; do
    [ -f "$profile_dir/package.json" ] || continue
    profile=${profile_dir%/}
    profile=${profile##*/}
    echo "Installing node modules for profile: $profile"
    if ! dsh plugin --profile "$profile" install; then
        echo "WARNING: node modules failed for profile $profile; skipping it" >&2
        failures=$((failures + 1))
        continue
    fi
    while IFS= read -r plugin; do
        [ -n "$plugin" ] || continue
        echo "Adding plugin $plugin to profile: $profile"
        if ! dsh plugin --profile "$profile" add "$plugin"; then
            echo "WARNING: failed to add $plugin to profile $profile" >&2
            failures=$((failures + 1))
        fi
    done <<INNER
$plugins
INNER
done

if [ "$failures" -ne 0 ]; then
    echo "$failures plugin operation(s) failed" >&2
    exit 1
fi

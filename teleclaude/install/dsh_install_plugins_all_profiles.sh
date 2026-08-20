#!/bin/sh
# Install the TeleClaude global DSH plugins into every EXISTING DSH profile.
#
# Invoked by bin/install.sh (setup_dsh_integration) after dsh is installed, and
# symlinked to $DSH_HOME/install-plugins.sh so it can also be run by hand from
# the DSH home. The loop visits only directories already present under
# $DSH_HOME/profiles that carry a package.json: this script NEVER creates a
# profile (dsh plugin --profile X add auto-initializes missing profiles, which
# is why every target must exist first), and the package.json guard keeps
# $DSH_HOME/profiles/node_modules from being treated as one.
#
# dsh-hooks is installed from the machine authoring location
# ($DSH_HOME/plugins/dsh-hooks) so its package-owned bundle patch stays
# authoritative; it is skipped when that package is absent.
#
# Plugin set, in order of application:
#   built-in defaults        the TeleClaude global plugins below
#   DSH_PLUGINS=...          replaces the defaults entirely (empty = none)
#   $DSH_HOME/extra-plugins  extra plugins, one per line ('#' starts a comment)
#   arguments                extra plugins for this run
#
# Example:
#   ~/.dsh/install-plugins.sh github:me/my-dsh-plugins#main&path:/my-plugin
set -e
dsh_home="${DSH_HOME:-$HOME/.dsh}"
default_plugins="github:InstruktAI/dsh-plugins#main&path:/dsh-qa dsh-checkpoint-rewind"
hooks_src="$dsh_home/plugins/dsh-hooks"
if [ -f "$hooks_src/package.json" ]; then
    default_plugins="file:$hooks_src $default_plugins"
fi
plugins="${DSH_PLUGINS-$default_plugins}"
extra_file="$dsh_home/extra-plugins"
if [ -f "$extra_file" ]; then
    plugins="$plugins $(sed 's/#.*//' "$extra_file")"
fi
plugins="$plugins $*"
# Split the whitespace-delimited plugin list into arguments with pathname
# expansion off, so a '*' in an operator-supplied plugin ref stays literal.
set -f
# shellcheck disable=SC2086
set -- $plugins
set +f
for profile_dir in "$dsh_home"/profiles/*/; do
    [ -f "$profile_dir/package.json" ] || continue
    profile=${profile_dir%/}
    profile=${profile##*/}
    echo "Installing node modules for profile: $profile"
    dsh plugin --profile "$profile" install
    for plugin in "$@"; do
        echo "Adding plugin $plugin to profile: $profile"
        dsh plugin --profile "$profile" add "$plugin"
    done
done

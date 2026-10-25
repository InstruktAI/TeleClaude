#!/usr/bin/env bash
# Where the platform's live surfaces address the code.
#
# A release of the installation is addressed through the installation's `current` pointer, never through
# its own folder, so switching `current` rewrites no service definition, hook command or link and a pruned
# release breaks nothing that runs. Any other checkout names itself. Mirrors
# teleclaude/core/reconciliation/installation.py and live_surfaces.py. Sets no shell options: this file is
# sourced by callers that own theirs.

# The XDG data directory: $XDG_DATA_HOME when it is an absolute path, else ~/.local/share. Service
# definitions carry this value to the processes the service managers start, which do not inherit it.
installation_data_home() {
    local data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
    case "$data_home" in
        /*) ;;
        *) data_home="$HOME/.local/share" ;;
    esac
    printf '%s\n' "$data_home"
}

# The installation root under the XDG data directory.
installation_root_path() {
    printf '%s\n' "$(installation_data_home)/instrukt-ai/teleclaude"
}

# is_installation_release_dir <dir>: whether <dir> is a folder of the installation's releases.
is_installation_release_dir() {
    local dir="$1" releases physical_parent
    releases="$(cd "$(installation_root_path)/releases" 2>/dev/null && pwd -P)" || return 1
    physical_parent="$(cd "$(dirname "$(cd "$dir" && pwd -P)")" && pwd -P)" || return 1
    [ "$physical_parent" = "$releases" ]
}

# live_root_of <dir>: the path live surfaces name for <dir>.
live_root_of() {
    local dir="$1"
    if is_installation_release_dir "$dir"; then
        printf '%s\n' "$(installation_root_path)/current"
    else
        printf '%s\n' "$dir"
    fi
}

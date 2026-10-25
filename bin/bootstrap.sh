#!/usr/bin/env bash
#
# TeleClaude bootstrap.
#
# Takes a machine with no TeleClaude — or one that runs it from a project checkout — to a platform that
# runs from an installed release. It needs no clone: every release tag carries this file, so the machine
# fetches it by itself:
#
#   curl -fsSL https://raw.githubusercontent.com/InstruktAI/TeleClaude/<tag>/bin/bootstrap.sh | bash
#
# It checks the machine's prerequisites, then drives the install act of the source's latest release
# (initial provisioning on a machine with no platform, a controlled restart on one that runs from a
# checkout) and publishes `telec` from it. The machine convergence that needs no valid configuration
# then runs from the installed release. Configuration is completed in the terminal interface (`telec`)
# or with `telec config`; `telec app start` installs the services and starts the daemon once it is valid.
#
# TELECLAUDE_SOURCE names the repository to follow (default: the upstream repository, so a fork's
# installation follows its fork); TELECLAUDE_BOOTSTRAP_REF pins the release or branch the driver runs from.
# Nothing here waits on a prompt: a missing prerequisite fails at once and says how to provide it.

set -euo pipefail

SOURCE="${TELECLAUDE_SOURCE:-https://github.com/InstruktAI/TeleClaude.git}"
DRIVER_REF="${TELECLAUDE_BOOTSTRAP_REF:-}"
NODE_MIN_MAJOR=22

fail() {
    printf 'bootstrap: %s\n' "$1" >&2
    exit 1
}

require_tool() {
    local tool="$1" hint="$2"
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is missing. $hint"
}

installation_root() {
    local data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
    case "$data_home" in
        /*) ;;
        *) data_home="$HOME/.local/share" ;;
    esac
    printf '%s\n' "$data_home/instrukt-ai/teleclaude"
}

check_prerequisites() {
    require_tool git "Install git (macOS: xcode-select --install; Debian/Ubuntu: sudo apt install git)."
    require_tool uv "Install uv: https://docs.astral.sh/uv/getting-started/installation/"
    require_tool node "Install Node.js ${NODE_MIN_MAJOR} or newer: https://nodejs.org/"
    require_tool corepack "Install a Node.js distribution that includes corepack (Node.js ${NODE_MIN_MAJOR} or newer)."
    require_tool tmux "Install tmux (macOS: brew install tmux; Debian/Ubuntu: sudo apt install tmux)."
    local node_major
    node_major="$(node -p 'process.versions.node.split(".")[0]')"
    [ "$node_major" -ge "$NODE_MIN_MAJOR" ] || fail "Node.js $node_major is too old. Install Node.js ${NODE_MIN_MAJOR} or newer."
    if [ "$(uname -s)" = "Darwin" ]; then
        /usr/bin/xcrun --find swiftc >/dev/null 2>&1 \
            || fail "The Xcode Command Line Tools are missing. Run: xcode-select --install, then run the bootstrap again."
    fi
}

# The project checkout the platform currently runs from: the checkout the published telec belongs to,
# when that is not already a release of the installation. Empty when there is none.
running_checkout() {
    local published="$HOME/.local/bin/telec" target physical root
    [ -L "$published" ] || return 0
    target="$(readlink "$published")"
    case "$target" in
        /*) ;;
        *) target="$(dirname "$published")/$target" ;;
    esac
    [ -e "$target" ] || return 0
    physical="$(cd "$(dirname "$target")/.." && pwd -P)" || return 0
    [ -e "$physical/.git" ] || return 0
    root="$(cd "$physical" && pwd -P)"
    case "$root" in
        "$(installation_root)"/*) return 0 ;;
    esac
    printf '%s\n' "$root"
}

# The release the driver runs from: the source's latest release tag. A source that tags none has no
# release to install, and the bootstrap says so rather than running from another kind of source.
driver_ref() {
    local latest
    if [ -n "$DRIVER_REF" ]; then
        printf '%s\n' "$DRIVER_REF"
        return 0
    fi
    latest="$(git ls-remote --tags --refs --sort=-version:refname "$SOURCE" 'v[0-9]*.[0-9]*.[0-9]*' 2>/dev/null | head -n 1 | sed 's#.*refs/tags/##')"
    [ -n "$latest" ] || fail "$SOURCE has tagged no release, so there is no latest release to install."
    printf '%s\n' "$latest"
}

main() {
    check_prerequisites

    local checkout driver scratch ref root
    checkout="$(running_checkout)"
    root="$(installation_root)"
    scratch="$(mktemp -d)"
    # shellcheck disable=SC2064
    trap "rm -rf '$scratch'" EXIT
    driver="$scratch/driver"

    ref="$(driver_ref)" || exit 1
    printf 'Fetching the driver (%s) from %s\n' "$ref" "$SOURCE"
    git clone --quiet --depth 1 --branch "$ref" "$SOURCE" "$driver" || fail "Could not fetch $ref from $SOURCE."
    (cd "$driver" && uv sync --frozen --quiet) || fail "Could not build the driver's environment."

    if [ -n "$checkout" ]; then
        printf 'The platform runs from %s; moving it onto an installation at %s\n' "$checkout" "$root"
        (cd "$driver" && .venv/bin/python -m teleclaude.core.reconciliation.installation_move move --checkout "$checkout") \
            || fail "The move did not complete; the platform is as it was left (see the report above)."
    else
        printf 'Installing the latest release into %s\n' "$root"
        (cd "$driver" && .venv/bin/python -m teleclaude.core.reconciliation.installation_move bootstrap --source "$SOURCE") \
            || fail "The install did not complete (see the report above)."
    fi

    printf 'Converging the machine from the installed release\n'
    "$root/current/bin/install.sh" || fail "The machine convergence did not complete (see its report above)."

    printf '\nTeleClaude is installed at %s.\n' "$root"
    printf 'Complete the configuration with `telec` (the terminal interface) or `telec config`;\n'
    printf 'then `telec app start` installs the services and starts the daemon.\n'
}

main "$@"

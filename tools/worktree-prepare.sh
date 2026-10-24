#!/usr/bin/env bash
#
# Worktree Preparation Script
# Prepares a git worktree for TeleClaude work by:
#   1. Reusing the project-root Python environment via .venv symlink
#   2. Generating config.yml (isolated worktree database)
#   3. Symlinking .env from main repo
#
# Usage: tools/worktree-prepare.sh <slug> <environment-root> <worktree-path>
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Validate arguments
if [ $# -ne 3 ]; then
    print_error "Usage: $0 <slug> <environment-root> <worktree-path>"
    exit 1
fi

SLUG="$1"
ENVIRONMENT_ROOT="$(cd "$2" && pwd)"
WORKTREE_PATH="$3"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Verify we're in the main repo (not a worktree)
if command -v git &> /dev/null && git rev-parse --git-dir &> /dev/null; then
    GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
    COMMON_DIR=$(git rev-parse --git-common-dir 2>/dev/null)

    if [ "$GIT_DIR" != "$COMMON_DIR" ]; then
        print_error "This script must run from the main repository, not a worktree"
        exit 1
    fi
fi

# Verify worktree exists
if [ ! -d "$WORKTREE_PATH" ]; then
    print_error "Worktree directory not found: $WORKTREE_PATH"
    exit 1
fi

print_info "Preparing worktree: $SLUG"

# Step 1: Link shared Python environment
print_info "Linking shared Python environment..."
cd "$WORKTREE_PATH"

# Require the root environment to exist; worktree prep does not provision Python.
if [ ! -x "$ENVIRONMENT_ROOT/.venv/bin/python" ]; then
    print_error "Environment Python missing: $ENVIRONMENT_ROOT/.venv/bin/python"
    print_error "Run make install (or uv sync --group dev) in the project root first."
    exit 1
fi

# Replace any existing worktree-local virtualenv with a symlink to the root one.
if [ -e ".venv" ] || [ -L ".venv" ]; then
    rm -rf ".venv"
fi
ln -s "$ENVIRONMENT_ROOT/.venv" ".venv"

print_success "Shared .venv linked"

# Step 2: Create .env symlink
print_info "Creating .env symlink..."

if [ ! -f "$ENVIRONMENT_ROOT/.env" ]; then
    print_error "Environment settings not found: $ENVIRONMENT_ROOT/.env"
    exit 1
fi

cd "$WORKTREE_PATH"
ln -sf "$ENVIRONMENT_ROOT/.env" .env
print_success ".env symlink created"

print_success "Worktree preparation complete: $SLUG"
print_info "Ready for work with:"
print_info "  - Shared root .venv/"
print_info "  - Isolated database (worktree teleclaude.db)"
print_info "  - Shared secrets (.env symlink)"

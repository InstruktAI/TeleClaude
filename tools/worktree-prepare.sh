#!/usr/bin/env bash
#
# Worktree Preparation Script
# Prepares a git worktree for TeleClaude work by:
#   1. Installing Python dependencies (isolated .venv)
#   2. Generating config.yml (isolated worktree database)
#   3. Symlinking .env from main repo
#
# Usage: tools/worktree-prepare.sh <slug>
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
if [ $# -ne 1 ]; then
    print_error "Usage: $0 <slug>"
    exit 1
fi

SLUG="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_ROOT="$(pwd)"
WORKTREE_DIR="$TARGET_ROOT/trees/$SLUG"

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
if [ ! -d "$WORKTREE_DIR" ]; then
    print_error "Worktree directory not found: $WORKTREE_DIR"
    exit 1
fi

print_info "Preparing worktree: $SLUG"

# Step 1: Install Python dependencies
print_info "Installing Python dependencies..."
cd "$WORKTREE_DIR"

# Check if uv is available
if command -v uv &> /dev/null; then
    uv sync --extra test
else
    print_warning "uv not found, falling back to pip"
    # Create venv if it doesn't exist
    if [ ! -d ".venv" ]; then
        python3 -m venv .venv
    fi
    # Install with pip
    .venv/bin/python -m pip install --quiet --upgrade pip
    .venv/bin/python -m pip install --quiet -e ".[test]"
fi

print_success "Dependencies installed"

# Step 2: Generate config.yml
print_info "Generating config.yml..."

if [ ! -f "$TARGET_ROOT/config.yml" ]; then
    print_error "Main config.yml not found: $TARGET_ROOT/config.yml"
    exit 1
fi

# Copy main config with worktree-local database path
# Use worktree venv to ensure PyYAML is available
"$WORKTREE_DIR/.venv/bin/python" << PYTHON_SCRIPT
import sys
import yaml
from pathlib import Path

repo_root = Path("$TARGET_ROOT")
worktree_dir = Path("$WORKTREE_DIR")
main_config_path = repo_root / "config.yml"
worktree_config_path = worktree_dir / "config.yml"

# Read main config
with open(main_config_path, 'r') as f:
    config = yaml.safe_load(f)

# Set database path to worktree-local database
# Worktrees need their own SQLite database for test isolation and development
# This is NOT a violation of the "single database" rule - that rule applies to
# the running daemon, not isolated development/test environments
if 'database' in config:
    config['database']['path'] = str(worktree_dir / "teleclaude.db")

# Write worktree config
with open(worktree_config_path, 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)

print(f"Generated config at: {worktree_config_path}")
print(f"Database: {worktree_dir / 'teleclaude.db'}")
PYTHON_SCRIPT

print_success "config.yml generated"

# Step 3: Create .env symlink
print_info "Creating .env symlink..."

if [ ! -f "$TARGET_ROOT/.env" ]; then
    print_error "Main .env not found: $TARGET_ROOT/.env"
    exit 1
fi

cd "$WORKTREE_DIR"
ln -sf "../../.env" .env
print_success ".env symlink created"

print_success "Worktree preparation complete: $SLUG"
print_info "Ready for work with:"
print_info "  - Isolated .venv/"
print_info "  - Isolated database (worktree teleclaude.db)"
print_info "  - Shared secrets (.env symlink)"

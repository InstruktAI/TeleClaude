#!/usr/bin/env bash
set -euo pipefail

setup_agent_hooks() {
    print_header "Configuring Agent Hooks"
    print_info "Running scripts/install_hooks.py..."

    if "$INSTALL_DIR/.venv/bin/python" "$INSTALL_DIR/scripts/install_hooks.py"; then
        print_success "Agent hooks configured"
    else
        print_error "Failed to configure agent hooks"
    fi
}

#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Verify deployment prerequisites and configuration state (Read-Only).

Checks:
1. Required binaries (node, python, pip, etc.)
2. Agent runtimes (claude, gemini, codex)
3. Config files existence and validity
4. MCP injection status (teleclaude, context7)
5. Environment variables
"""

import json
import shutil
from pathlib import Path
from typing import List

# Colors
GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def log_info(msg: str):
    print(f"{BLUE}ℹ{NC} {msg}")


def log_success(msg: str):
    print(f"{GREEN}✓{NC} {msg}")


def log_warn(msg: str):
    print(f"{YELLOW}⚠{NC} {msg}")


def log_error(msg: str):
    print(f"{RED}✗{NC} {msg}")


def check_binary(name: str, required: bool = True) -> bool:
    path = shutil.which(name)
    if path:
        log_success(f"Found {name} at {path}")
        return True
    if required:
        log_error(f"Missing required binary: {name}")
    else:
        log_warn(f"Missing optional binary: {name}")
    return False


def check_file(path: Path, description: str) -> bool:
    if path.exists():
        log_success(f"Found {description}: {path}")
        return True
    log_error(f"Missing {description}: {path}")
    return False


def check_json_config(path: Path, check_keys: List[str] = []) -> bool:
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        log_success(f"Valid JSON in {path}")

        missing = []
        for key in check_keys:
            # Simple top-level check or dot-notation support could be added
            # For now, checking if key exists in string representation for simplicity/speed
            if key not in str(data):
                missing.append(key)

        if missing:
            log_warn(f"Config {path} missing keys/values: {', '.join(missing)}")
            return False
        return True
    except json.JSONDecodeError:
        log_error(f"Invalid JSON in {path}")
        return False


def main():
    print(f"{BLUE}=== TeleClaude Deployment Verification (Dry Run) ==={NC}\n")

    home = Path.home()
    install_dir = Path(__file__).resolve().parent.parent

    # 1. System Dependencies
    print(f"{BLUE}--- System Dependencies ---{NC}")
    check_binary("node")
    check_binary("npm")
    check_binary("python3")
    check_binary("uv")
    check_binary("tmux")
    check_binary("ffmpeg", required=False)
    print("")

    # 2. Agent Runtimes
    print(f"{BLUE}--- Agent Runtimes ---{NC}")
    check_binary("claude")
    check_binary("gemini", required=False)
    check_binary("codex", required=False)  # Likely a wrapper or alias
    print("")

    # 3. Configuration Files
    print(f"{BLUE}--- Configuration ---{NC}")
    check_file(install_dir / ".env", "Environment file")
    check_file(install_dir / "config.yml", "Daemon config")
    check_file(install_dir / "teleclaude.yml", "Global config")
    print("")

    # 4. MCP Integration Status
    print(f"{BLUE}--- MCP Integration ---{NC}")

    # Claude
    claude_config = home / ".claude.json"
    if check_file(claude_config, "Claude Config"):
        check_json_config(claude_config, ["teleclaude", "mcp-wrapper.py"])
        # Check Context7
        check_json_config(claude_config, ["context7"])

    # Gemini
    gemini_config = home / ".gemini/settings.json"
    if check_file(gemini_config, "Gemini Config"):
        check_json_config(gemini_config, ["teleclaude"])
    else:
        log_warn("Gemini config not found (is Gemini installed?)")

    # Codex
    codex_config = home / ".codex/config.toml"
    if check_file(codex_config, "Codex Config"):
        content = codex_config.read_text()
        if "teleclaude" in content:
            log_success("TeleClaude MCP present in Codex config")
        else:
            log_warn("TeleClaude MCP MISSING in Codex config")
    else:
        log_warn("Codex config not found")

    print(f"\n{BLUE}=== Verification Complete ==={NC}")


if __name__ == "__main__":
    main()

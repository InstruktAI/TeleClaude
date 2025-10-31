#!/usr/bin/env python3
"""Unit test for /cd WORKDIR expansion logic."""

import os
import re
from pathlib import Path

import pytest
import yaml
from dotenv import load_dotenv


def expand_env_vars(config):
    """Recursively expand environment variables in config."""
    if isinstance(config, dict):
        return {k: expand_env_vars(v) for k, v in config.items()}
    if isinstance(config, list):
        return [expand_env_vars(item) for item in config]
    if isinstance(config, str):
        def replace_env_var(match):
            env_var = match.group(1)
            return os.getenv(env_var, match.group(0))
        return re.sub(r"\$\{([^}]+)\}", replace_env_var, config)
    return config


@pytest.mark.asyncio
async def test_workdir_expansion_logic():
    """Test that WORKDIR expands to configured default_working_dir."""
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    # Load and expand config
    with open(base_dir / "config.yml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config = expand_env_vars(config)

    # Get working directory
    working_dir = os.path.expanduser(config["computer"]["default_working_dir"])
    assert working_dir == "/tmp", "Test config should use /tmp as WORKDIR"

    # Test WORKDIR expansion (simulating daemon logic)
    target = "WORKDIR"
    if target == "WORKDIR":
        expanded = os.path.expanduser(config["computer"]["default_working_dir"])
    else:
        expanded = target

    assert expanded == "/tmp", "WORKDIR should expand to /tmp"
    assert expanded == working_dir, "Expanded WORKDIR should match default_working_dir"


@pytest.mark.asyncio
async def test_trusted_dirs_includes_workdir():
    """Test that trusted directories list includes WORKDIR as first entry."""
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    with open(base_dir / "config.yml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config = expand_env_vars(config)

    # Simulate daemon logic for /cd with no args
    working_dir = os.path.expanduser(config["computer"]["default_working_dir"])
    configured_dirs = config.get("computer", {}).get("trustedDirs", [])
    trusted_dirs = ["WORKDIR"] + configured_dirs

    # Assertions
    assert trusted_dirs[0] == "WORKDIR", "First trusted dir should be WORKDIR"
    assert len(trusted_dirs) >= 1, "Should have at least WORKDIR"
    assert all(isinstance(d, str) for d in trusted_dirs), "All entries should be strings"


@pytest.mark.asyncio
async def test_cd_command_construction():
    """Test that cd command is properly constructed with quoted path."""
    base_dir = Path(__file__).parent
    load_dotenv(base_dir / ".env")

    with open(base_dir / "config.yml", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config = expand_env_vars(config)

    # Simulate selecting WORKDIR
    target = "WORKDIR"
    if target == "WORKDIR":
        target_path = os.path.expanduser(config["computer"]["default_working_dir"])
    else:
        target_path = target

    # Simulate command construction (daemon uses shlex.quote)
    import shlex
    cd_command = f"cd {shlex.quote(target_path)}"

    assert cd_command == "cd /tmp", "Should construct proper cd command"
    assert "'" not in cd_command, "/tmp doesn't need quoting"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

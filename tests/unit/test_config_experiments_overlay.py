import os
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch, mock_open
import importlib
import teleclaude.config

def test_experiments_yml_overlay_loading(tmp_path, monkeypatch):
    """Verify that experiments.yml is correctly merged into the global config."""
    
    # Setup temporary directory for config files
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    config_file = config_dir / "config.yml"
    experiments_file = config_dir / "experiments.yml"
    
    # Base config content
    base_config = {
        "computer": {"name": "test-host", "user": "test-user"},
        "database": {"path": "/tmp/test.db"},
        "redis": {"enabled": False},
        "telegram": {"trusted_bots": []},
        "agents": {"claude": {"command": "claude"}},
        "ui": {"animations_enabled": True, "animations_periodic_interval": 60, "animations_subset": []}
    }
    
    # Experiments overlay content
    experiments_config = {
        "experiments": [
            {"name": "test_experiment", "agents": ["gemini"]}
        ]
    }
    
    config_file.write_text(yaml.dump(base_config))
    experiments_file.write_text(yaml.dump(experiments_config))
    
    # Monkeypatch the environment variable to point to our temp config
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    
    # Force reload of the config module to trigger the loading logic
    importlib.reload(teleclaude.config)
    
    # Verify the experiment was loaded
    assert teleclaude.config.config.is_experiment_enabled("test_experiment", "gemini") is True
    assert teleclaude.config.config.is_experiment_enabled("test_experiment", "claude") is False
    
    # Cleanup: restore original config state for other tests
    monkeypatch.delenv("TELECLAUDE_CONFIG_PATH", raising=False)
    importlib.reload(teleclaude.config)

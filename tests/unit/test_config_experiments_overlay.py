import importlib

import yaml


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
        "ui": {"animations_enabled": True, "animations_periodic_interval": 60, "animations_subset": []},
    }

    # Experiments overlay content — test both agent and adapter dimensions
    experiments_config = {
        "experiments": [
            {"name": "test_experiment", "agents": ["gemini"]},
            {"name": "test_experiment", "adapters": ["discord"]},
        ]
    }

    config_file.write_text(yaml.dump(base_config))
    experiments_file.write_text(yaml.dump(experiments_config))

    # Monkeypatch the environment variable to point to our temp config
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))

    import teleclaude.config

    # Force reload of the config module to trigger the loading logic
    importlib.reload(teleclaude.config)

    cfg = teleclaude.config.config

    # Agent-only entry matches gemini on any adapter
    assert cfg.is_experiment_enabled("test_experiment", "gemini") is True
    assert cfg.is_experiment_enabled("test_experiment", "gemini", adapter="telegram") is True
    assert cfg.is_experiment_enabled("test_experiment", "gemini", adapter="discord") is True

    # Adapter-only entry matches any agent on discord
    assert cfg.is_experiment_enabled("test_experiment", "claude", adapter="discord") is True

    # Claude + telegram → no matching entry
    assert cfg.is_experiment_enabled("test_experiment", "claude", adapter="telegram") is False

    # Optimistic match: no adapter provided → adapter-only entry matches
    assert cfg.is_experiment_enabled("test_experiment", "claude") is True

    # No matching agent, no matching adapter
    assert cfg.is_experiment_enabled("nonexistent_experiment", "claude") is False

    # Cleanup: restore original config state for other tests
    monkeypatch.delenv("TELECLAUDE_CONFIG_PATH", raising=False)
    importlib.reload(teleclaude.config)

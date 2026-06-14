from __future__ import annotations

import pytest
from pydantic import ValidationError
from ruamel.yaml import YAML

from teleclaude.config import _parse_process_janitor_config
from teleclaude.config.loader import load_project_config

DEFAULT_SCAN_INTERVAL_SECONDS = 300
DEFAULT_SIGNATURE_TTL_SECONDS = 3600
DEFAULT_LEASE_TTL_SECONDS = 1800
CUSTOM_SCAN_INTERVAL_SECONDS = 600
CUSTOM_SIGNATURE_TTL_SECONDS = 7200
CUSTOM_LEASE_TTL_SECONDS = 2400
MINIMUM_REJECTED_INTERVAL_SECONDS = 59


def test_project_config_loads_process_janitor_defaults(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    YAML().dump({"project_slug": "process-janitor"}, config_path)

    config = load_project_config(config_path)

    assert config.process_janitor.scan_interval_seconds == DEFAULT_SCAN_INTERVAL_SECONDS
    assert config.process_janitor.default_signature_ttl_seconds == DEFAULT_SIGNATURE_TTL_SECONDS
    assert config.process_janitor.lease_ttl_seconds == DEFAULT_LEASE_TTL_SECONDS
    assert config.process_janitor.dry_run_default is True


def test_project_config_loads_process_janitor_overrides(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    YAML().dump(
        {
            "project_slug": "process-janitor",
            "process_janitor": {
                "scan_interval_seconds": CUSTOM_SCAN_INTERVAL_SECONDS,
                "default_signature_ttl_seconds": CUSTOM_SIGNATURE_TTL_SECONDS,
                "lease_ttl_seconds": CUSTOM_LEASE_TTL_SECONDS,
                "dry_run_default": False,
            },
        },
        config_path,
    )

    config = load_project_config(config_path)

    assert config.process_janitor.scan_interval_seconds == CUSTOM_SCAN_INTERVAL_SECONDS
    assert config.process_janitor.default_signature_ttl_seconds == CUSTOM_SIGNATURE_TTL_SECONDS
    assert config.process_janitor.lease_ttl_seconds == CUSTOM_LEASE_TTL_SECONDS
    assert config.process_janitor.dry_run_default is False


def test_project_config_rejects_too_short_process_janitor_scan_interval(tmp_path):
    config_path = tmp_path / "teleclaude.yml"
    YAML().dump(
        {
            "project_slug": "process-janitor",
            "process_janitor": {"scan_interval_seconds": MINIMUM_REJECTED_INTERVAL_SECONDS},
        },
        config_path,
    )

    with pytest.raises(ValidationError):
        load_project_config(config_path)


def test_runtime_config_parser_rejects_too_short_process_janitor_scan_interval():
    with pytest.raises(ValueError, match=r"process_janitor\.scan_interval_seconds"):
        _parse_process_janitor_config({"scan_interval_seconds": MINIMUM_REJECTED_INTERVAL_SECONDS})

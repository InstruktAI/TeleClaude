"""Antigravity (agy) settings and Policy Engine deployment tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.install.configure_agent_cli import configure_agy
from teleclaude.install.gemini_policy_migration import (
    GEMINI_LEGACY_ALLOWED_KEY,
    GEMINI_POLICY_TARGET_FILENAME,
    GEMINI_TOOLS_KEY,
    JsonObject,
    JsonValue,
)

pytestmark = pytest.mark.unit

OPERATOR_POLICY_FILENAME = "operator.toml"
OPERATOR_POLICY_BYTES = b'[[rule]]\ntoolName = "WriteFile"\ndecision = "deny"\npriority = 900\n'
USER_MARKER_KEY = "operatorPreference"


def _agy_dir(home: Path) -> Path:
    return home / ".gemini" / "antigravity-cli"


def _repo_root(tmp_path: Path) -> Path:
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True, exist_ok=True)
    receiver.touch()
    return tmp_path


def _read_settings(home: Path) -> JsonObject:
    settings = json.loads((_agy_dir(home) / "settings.json").read_text(encoding="utf-8"))
    assert isinstance(settings, dict)
    return cast(JsonObject, settings)


def _normalize_paths(value: JsonValue, tmp_path: Path) -> JsonValue:
    if isinstance(value, str):
        return value.replace(str(tmp_path), "TMP")
    if isinstance(value, list):
        return [_normalize_paths(item, tmp_path) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_paths(item, tmp_path) for key, item in value.items()}
    return value


def test_configure_agy_deploys_settings_without_legacy_tools_allowed(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_agy(_repo_root(tmp_path))

    settings = _read_settings(tmp_path)
    tools = settings[GEMINI_TOOLS_KEY]
    assert isinstance(tools, dict)
    assert GEMINI_LEGACY_ALLOWED_KEY not in tools
    assert _normalize_paths(settings, tmp_path) == snapshot


def test_configure_agy_deletes_legacy_tools_allowed_without_contaminating_user_settings(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    agy_dir = _agy_dir(tmp_path)
    agy_dir.mkdir(parents=True)
    (agy_dir / "settings.json").write_text(
        json.dumps(
            {
                GEMINI_TOOLS_KEY: {
                    GEMINI_LEGACY_ALLOWED_KEY: ["*"],
                    "enableHooks": False,
                },
                USER_MARKER_KEY: True,
            }
        ),
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_agy(_repo_root(tmp_path))

    settings = _read_settings(tmp_path)
    tools = settings[GEMINI_TOOLS_KEY]
    assert isinstance(tools, dict)
    assert GEMINI_LEGACY_ALLOWED_KEY not in tools
    assert settings[USER_MARKER_KEY] is True
    assert _normalize_paths(settings, tmp_path) == snapshot


def test_configure_agy_deploys_policy_file_non_destructively(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    policies_dir = _agy_dir(tmp_path) / "policies"
    policies_dir.mkdir(parents=True)
    operator_policy = policies_dir / OPERATOR_POLICY_FILENAME
    operator_policy.write_bytes(OPERATOR_POLICY_BYTES)

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_agy(_repo_root(tmp_path))

    teleclaude_policy = policies_dir / GEMINI_POLICY_TARGET_FILENAME
    assert operator_policy.read_bytes() == OPERATOR_POLICY_BYTES
    assert teleclaude_policy.read_text(encoding="utf-8") == snapshot


def test_configure_agy_rewrites_only_teleclaude_policy_file(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    policies_dir = _agy_dir(tmp_path) / "policies"
    policies_dir.mkdir(parents=True)
    operator_policy = policies_dir / OPERATOR_POLICY_FILENAME
    operator_policy.write_bytes(OPERATOR_POLICY_BYTES)
    teleclaude_policy = policies_dir / GEMINI_POLICY_TARGET_FILENAME
    teleclaude_policy.write_text("stale", encoding="utf-8")

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_agy(_repo_root(tmp_path))
        first_policy = teleclaude_policy.read_text(encoding="utf-8")
        configure_agy(_repo_root(tmp_path))

    assert operator_policy.read_bytes() == OPERATOR_POLICY_BYTES
    assert {
        "first_policy": first_policy,
        "second_policy": teleclaude_policy.read_text(encoding="utf-8"),
    } == snapshot

"""Characterization tests for teleclaude/cli/config_cmd.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from teleclaude.cli.config_cmd import (
    _deep_merge,
    _extract_subtree,
    _load_raw_config,
    _resolve_config_path,
    handle_get,
    handle_patch,
    handle_validate,
)

# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


def test_deep_merge_adds_new_keys() -> None:
    base = {"a": 1}
    override = {"b": 2}
    result = _deep_merge(base, override)
    assert result == {"a": 1, "b": 2}


def test_deep_merge_overrides_scalar_values() -> None:
    base = {"a": 1}
    override = {"a": 99}
    result = _deep_merge(base, override)
    assert result["a"] == 99


def test_deep_merge_recursively_merges_nested_dicts() -> None:
    base = {"nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 99, "z": 3}}
    result = _deep_merge(base, override)
    assert result["nested"] == {"x": 1, "y": 99, "z": 3}


def test_deep_merge_does_not_mutate_base() -> None:
    base = {"a": {"x": 1}}
    override = {"a": {"x": 2}}
    _deep_merge(base, override)
    assert base["a"]["x"] == 1


def test_deep_merge_empty_override_returns_base_copy() -> None:
    base = {"a": 1}
    result = _deep_merge(base, {})
    assert result == {"a": 1}


# ---------------------------------------------------------------------------
# _resolve_config_path
# ---------------------------------------------------------------------------


def test_resolve_config_path_uses_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", "/custom/config.yml")
    result = _resolve_config_path(None)
    assert result == Path("/custom/config.yml")


def test_resolve_config_path_falls_back_to_cwd_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELECLAUDE_CONFIG_PATH", raising=False)
    result = _resolve_config_path(None)
    assert result == Path.cwd() / "config.yml"


def test_resolve_config_path_uses_project_root_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELECLAUDE_CONFIG_PATH", raising=False)
    result = _resolve_config_path(Path("/my/project"))
    assert result == Path("/my/project/config.yml")


# ---------------------------------------------------------------------------
# _load_raw_config
# ---------------------------------------------------------------------------


def test_load_raw_config_returns_empty_dict_when_file_absent(tmp_path: Path) -> None:
    result = _load_raw_config(tmp_path / "missing.yml")
    assert result == {}


def test_load_raw_config_parses_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("key: value\nnested:\n  x: 1\n")
    result = _load_raw_config(config_file)
    assert result.get("key") == "value"
    nested = result.get("nested")
    assert isinstance(nested, dict)
    assert nested.get("x") == 1


def test_load_raw_config_returns_empty_dict_for_empty_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("")
    result = _load_raw_config(config_file)
    assert result == {}


# ---------------------------------------------------------------------------
# _extract_subtree
# ---------------------------------------------------------------------------


def test_extract_subtree_returns_wrapped_leaf_value() -> None:
    data = {"a": {"b": {"c": 42}}}
    result = _extract_subtree(data, "a.b.c")
    assert result == {"a": {"b": {"c": 42}}}


def test_extract_subtree_raises_key_error_for_missing_path() -> None:
    data = {"a": {"b": 1}}
    with pytest.raises(KeyError):
        _extract_subtree(data, "a.missing")


def test_extract_subtree_returns_top_level_key() -> None:
    data = {"key": "value"}
    result = _extract_subtree(data, "key")
    assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# handle_get
# ---------------------------------------------------------------------------


def test_handle_get_prints_full_config_when_no_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("key: value\n")
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    handle_get([])
    captured = capsys.readouterr()
    assert "key" in captured.out


def test_handle_get_json_format_outputs_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    config_file = tmp_path / "config.yml"
    config_file.write_text("key: value\n")
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    handle_get(["--format", "json"])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["key"] == "value"


def test_handle_get_exits_when_config_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(tmp_path / "missing.yml"))
    with pytest.raises(SystemExit):
        handle_get([])


def test_handle_get_exits_on_invalid_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("key: value\n")
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    with pytest.raises(SystemExit):
        handle_get(["--format", "toml"])


# ---------------------------------------------------------------------------
# handle_patch
# ---------------------------------------------------------------------------


def test_handle_patch_merges_yaml_into_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("existing: keep\n")
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    handle_patch(["--yaml", "new_key: added"])
    updated = yaml.safe_load(config_file.read_text())
    assert updated["existing"] == "keep"
    assert updated["new_key"] == "added"


def test_handle_patch_exits_when_config_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(tmp_path / "missing.yml"))
    with pytest.raises(SystemExit):
        handle_patch(["--yaml", "key: val"])


def test_handle_patch_exits_when_patch_is_not_a_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("key: value\n")
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    with pytest.raises(SystemExit):
        handle_patch(["--yaml", "- list item"])


# ---------------------------------------------------------------------------
# handle_validate
# ---------------------------------------------------------------------------


def test_handle_validate_exits_when_config_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(tmp_path / "missing.yml"))
    with pytest.raises(SystemExit):
        handle_validate([])


def test_handle_validate_succeeds_with_valid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("key: value\n")
    monkeypatch.setenv("TELECLAUDE_CONFIG_PATH", str(config_file))
    handle_validate([])  # should not raise SystemExit

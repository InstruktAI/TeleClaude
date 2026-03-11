"""Unit tests for sandbox-scope cartridge CLI functions in cartridge_cli.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _mock_loader(config_obj):
    """Return a mock teleclaude.config.loader module with load_global_config returning config_obj."""
    mock = MagicMock()
    mock.load_global_config.return_value = config_obj
    return mock


def _mock_loader_raising(exc):
    mock = MagicMock()
    mock.load_global_config.side_effect = exc
    return mock


def _sys_modules_for_loader(loader_mock):
    return {
        "teleclaude": MagicMock(),
        "teleclaude.config": MagicMock(),
        "teleclaude.config.loader": loader_mock,
    }


# ---------------------------------------------------------------------------
# _get_sandbox_dir
# ---------------------------------------------------------------------------


def test_get_sandbox_dir_falls_back_to_default_on_load_error():
    from teleclaude.cli.cartridge_cli import _get_sandbox_dir

    loader = _mock_loader_raising(RuntimeError("config unavailable"))
    with patch.dict(__import__("sys").modules, _sys_modules_for_loader(loader)):
        result = _get_sandbox_dir()

    assert result == Path("~/.teleclaude/sandbox-cartridges").expanduser()


def test_get_sandbox_dir_uses_config_value():
    from teleclaude.cli.cartridge_cli import _get_sandbox_dir

    mock_config = MagicMock()
    mock_config.sandbox_cartridges_dir = "~/custom/sandbox"
    loader = _mock_loader(mock_config)
    with patch.dict(__import__("sys").modules, _sys_modules_for_loader(loader)):
        result = _get_sandbox_dir()

    assert result == Path("~/custom/sandbox").expanduser()


def test_get_sandbox_dir_falls_back_when_attr_none():
    from teleclaude.cli.cartridge_cli import _get_sandbox_dir

    mock_config = MagicMock(spec=[])  # no sandbox_cartridges_dir attr → getattr returns None
    loader = _mock_loader(mock_config)
    with patch.dict(__import__("sys").modules, _sys_modules_for_loader(loader)):
        result = _get_sandbox_dir()

    assert result == Path("~/.teleclaude/sandbox-cartridges").expanduser()


# ---------------------------------------------------------------------------
# _list_sandbox_cartridges
# ---------------------------------------------------------------------------


def test_list_sandbox_cartridges_absent_dir_text(capsys):
    from teleclaude.cli.cartridge_cli import _list_sandbox_cartridges

    with patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=Path("/nonexistent/path/xyz")):
        _list_sandbox_cartridges(use_json=False)

    captured = capsys.readouterr()
    assert "No sandbox cartridges" in captured.out


def test_list_sandbox_cartridges_absent_dir_json(capsys):
    from teleclaude.cli.cartridge_cli import _list_sandbox_cartridges

    with patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=Path("/nonexistent/path/xyz")):
        _list_sandbox_cartridges(use_json=True)

    captured = capsys.readouterr()
    assert json.loads(captured.out) == []


def test_list_sandbox_cartridges_lists_py_files_json(capsys):
    from teleclaude.cli.cartridge_cli import _list_sandbox_cartridges

    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox_dir = Path(tmpdir)
        (sandbox_dir / "cart_a.py").write_text("# a")
        (sandbox_dir / "cart_b.py").write_text("# b")
        (sandbox_dir / "readme.txt").write_text("ignore")

        with patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=sandbox_dir):
            _list_sandbox_cartridges(use_json=True)

    captured = capsys.readouterr()
    rows = json.loads(captured.out)
    ids = [r["id"] for r in rows]
    assert ids == ["cart_a", "cart_b"]
    assert all("size_bytes" in r and "modified" in r for r in rows)


def test_list_sandbox_cartridges_empty_dir_text(capsys):
    from teleclaude.cli.cartridge_cli import _list_sandbox_cartridges

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=Path(tmpdir)):
            _list_sandbox_cartridges(use_json=False)

    captured = capsys.readouterr()
    assert "No sandbox cartridges" in captured.out


# ---------------------------------------------------------------------------
# _promote_from_sandbox
# ---------------------------------------------------------------------------


def _make_parsed(cartridge_id, to_scope, target_domain=None):
    import argparse

    ns = argparse.Namespace()
    ns.cartridge_id = cartridge_id
    ns.to_scope = to_scope
    ns.target_domain = target_domain
    return ns


def test_promote_from_sandbox_wrong_to_scope_exits(capsys):
    from teleclaude.cli.cartridge_cli import _promote_from_sandbox

    parsed = _make_parsed("my_cart", to_scope="personal")
    with pytest.raises(SystemExit):
        _promote_from_sandbox(parsed, use_json=False)


def test_promote_from_sandbox_missing_cartridge_exits(capsys):
    from teleclaude.cli.cartridge_cli import _promote_from_sandbox

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=Path(tmpdir)):
            parsed = _make_parsed("ghost_cart", to_scope="domain", target_domain="myteam")
            with pytest.raises(SystemExit):
                _promote_from_sandbox(parsed, use_json=False)


def test_promote_from_sandbox_syntax_error_exits(capsys):
    from teleclaude.cli.cartridge_cli import _promote_from_sandbox

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "bad.py").write_text("def broken(\n")
        with patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=Path(tmpdir)):
            parsed = _make_parsed("bad", to_scope="domain", target_domain="myteam")
            with pytest.raises(SystemExit):
                _promote_from_sandbox(parsed, use_json=False)


def test_promote_from_sandbox_copies_and_deletes(capsys):
    from teleclaude.cli.cartridge_cli import _promote_from_sandbox

    with (
        tempfile.TemporaryDirectory() as sandbox_tmpdir,
        tempfile.TemporaryDirectory() as domain_base_tmpdir,
    ):
        sandbox_dir = Path(sandbox_tmpdir)
        domain_base = Path(domain_base_tmpdir)
        src = sandbox_dir / "my_cart.py"
        src.write_text("async def process(e, c): return e\n")

        mock_config = MagicMock()
        mock_config.event_domains.base_path = str(domain_base)
        loader = _mock_loader(mock_config)

        with (
            patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=sandbox_dir),
            patch.dict(__import__("sys").modules, _sys_modules_for_loader(loader)),
        ):
            parsed = _make_parsed("my_cart", to_scope="domain", target_domain="myteam")
            _promote_from_sandbox(parsed, use_json=False)

        dest = domain_base / "domains" / "myteam" / "cartridges" / "my_cart.py"
        assert dest.exists()
        assert not src.exists()


def test_promote_from_sandbox_json_output(capsys):
    from teleclaude.cli.cartridge_cli import _promote_from_sandbox

    with (
        tempfile.TemporaryDirectory() as sandbox_tmpdir,
        tempfile.TemporaryDirectory() as domain_base_tmpdir,
    ):
        sandbox_dir = Path(sandbox_tmpdir)
        domain_base = Path(domain_base_tmpdir)
        (sandbox_dir / "j_cart.py").write_text("async def process(e, c): return e\n")

        mock_config = MagicMock()
        mock_config.event_domains.base_path = str(domain_base)
        loader = _mock_loader(mock_config)

        with (
            patch("teleclaude.cli.cartridge_cli._get_sandbox_dir", return_value=sandbox_dir),
            patch.dict(__import__("sys").modules, _sys_modules_for_loader(loader)),
        ):
            parsed = _make_parsed("j_cart", to_scope="domain", target_domain="myteam")
            _promote_from_sandbox(parsed, use_json=True)

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["ok"] is True
        assert result["id"] == "j_cart"
        assert result["from"] == "sandbox"
        assert result["to"] == "domain"

"""Test specifications for teleclaude.install.configure_agent_cli.

Covers:
  R1 — Module rename: configure_agent_cli is importable at the new path, and all
       internal references (guardrails.py, init_flow.py) are updated.
  R2 — Shell wrapper inlining: setup_agent_hooks.sh removed; install.sh owns setup.
  R3 — Repo-owned compaction prompt source file exists with correct content.
  R4 — Compaction prompt deployment: file written, TOML key set, idempotent,
       and delivered via the settings/codex.toml override mechanism.
  R6 — Prototype .codex/ files absent from the repository (regression guards).
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.install import configure_agent_cli
from teleclaude.install.codex_hook_trust import build_codex_managed_hook_state
from teleclaude.install.configure_agent_cli import configure_agy, configure_claude, configure_codex
from teleclaude.project_setup import init_flow

pytestmark = pytest.mark.unit

COMPACTION_PROMPT_FILENAME = "CODEX.compaction.md"
COMPACT_PROMPT_TOML_KEY = "experimental_compact_prompt_file"
CODEX_HOOKS_FILENAME = "hooks.json"

# Repo root: tests/unit/install/ → tests/unit/ → tests/ → repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# R1 — Module rename
# ---------------------------------------------------------------------------


def test_configure_agent_cli_module_is_importable() -> None:
    """The renamed module must be importable from teleclaude.install.configure_agent_cli."""
    assert configure_agent_cli.__file__


def test_configure_codex_callable_from_renamed_module() -> None:
    """configure_codex must be accessible from the renamed module."""
    assert callable(configure_codex)


def test_configure_claude_and_agy_callable_from_renamed_module() -> None:
    """configure_claude and configure_agy must be accessible from the renamed module."""
    assert callable(configure_claude)
    assert callable(configure_agy)


# ---------------------------------------------------------------------------
# R4 — Compaction prompt deployment
# ---------------------------------------------------------------------------


def test_install_shell_environment_creates_symlinks(tmp_path: Path) -> None:
    """install_shell_environment symlinks every rc file into SHELL_DIR pointing at the repo source."""
    shell_dir = tmp_path / "shell"
    with patch.object(configure_agent_cli, "SHELL_DIR", shell_dir):
        configure_agent_cli.install_shell_environment()

    expected_links = {
        ".zshenv": "zshenv",
        ".zshrc": "zshrc",
        ".bashenv": "bashenv",
        ".bashrc": "bashrc",
        ".profile": "profile",
    }
    for installed_name, source_name in expected_links.items():
        link = shell_dir / installed_name
        source = configure_agent_cli.SHELL_TEMPLATE_DIR / source_name
        assert link.is_symlink(), f"{link} must be a symlink"
        assert link.resolve() == source.resolve(), f"{link} must point at {source}"


def test_install_shell_environment_is_idempotent(tmp_path: Path) -> None:
    """Running install_shell_environment twice leaves the symlinks intact and correct."""
    shell_dir = tmp_path / "shell"
    with patch.object(configure_agent_cli, "SHELL_DIR", shell_dir):
        configure_agent_cli.install_shell_environment()
        configure_agent_cli.install_shell_environment()

    for installed_name in (".zshenv", ".zshrc", ".bashenv", ".bashrc", ".profile"):
        link = shell_dir / installed_name
        assert link.is_symlink(), f"{link} must remain a symlink after a second run"


def test_shell_rc_resolves_path_to_override_root_when_telceclaude_home_set(tmp_path: Path) -> None:
    """Functional check: when an override TELECLAUDE_HOME is in env, every
    shell rc file resolves its PATH prepend to that root, not the
    $HOME/.teleclaude fallback. Sourcing each rc with a clean PATH and a
    distinct override root must end up with the override's bin first.
    Pins the contract end-to-end (rc text → executed shell semantics).
    """
    custom_root = tmp_path / "custom-tc"
    custom_bin = custom_root / "bin"
    custom_bin.mkdir(parents=True)
    template_dir = configure_agent_cli.SHELL_TEMPLATE_DIR

    # Each rc must be a self-contained PATH-pin source: sourcing it under a
    # POSIX sh with no PATH must leave PATH starting at the override's bin.
    # Compare the first PATH entry as a Path object so we assert on a
    # structural type rather than on string content.
    for source_name in ("zshenv", "bashenv", "profile"):
        rc = template_dir / source_name
        result = subprocess.run(
            ["/bin/sh", "-c", f'. {rc}; printf %s "$PATH"'],
            env={
                "TELECLAUDE_HOME": str(custom_root),
                "HOME": str(tmp_path / "stub-home"),  # must not be used
                "PATH": "",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{rc} sourcing failed: stderr={result.stderr}"
        first_entry = Path(result.stdout.split(":", 1)[0])
        assert first_entry == custom_bin, (
            f"{rc} must prepend $TELECLAUDE_HOME/bin (got {first_entry}, expected {custom_bin})"
        )


def test_teleclaude_shell_wrapper_resolves_env_to_override_root(tmp_path: Path) -> None:
    """The wrapper exports TeleClaude env pins before execing the resolved host shell."""
    custom_root = tmp_path / "custom-tc"
    (custom_root / "bin").mkdir(parents=True)
    (custom_root / "shell").mkdir(parents=True)
    probe_bin = tmp_path / "probe-bin"
    probe_bin.mkdir()
    probe_shell = probe_bin / "env-probe-shell"
    probe_shell.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'printf "PATH=%s\\n" "$PATH"',
                'printf "ZDOTDIR=%s\\n" "$ZDOTDIR"',
                'printf "BASH_ENV=%s\\n" "$BASH_ENV"',
                'printf "ENV=%s\\n" "$ENV"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    probe_shell.chmod(0o755)
    wrapper = configure_agent_cli.WRAPPER_TEMPLATE_DIR / "teleclaude-shell"

    # Use a non-empty inherited PATH so the contract is exercised under
    # realistic conditions (no edge-case trailing colon from empty PATH).
    inherited_path = str(tmp_path / "inherited-bin")
    input_path = f"{probe_bin}{os.pathsep}{inherited_path}"
    sourced = subprocess.run(
        [str(wrapper)],
        env={
            "TELECLAUDE_HOME": str(custom_root),
            "HOME": str(tmp_path / "stub-home"),
            "PATH": input_path,
            "TELECLAUDE_HOST_SHELL": "env-probe-shell",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert sourced.returncode == 0, f"wrapper sourcing failed: stderr={sourced.stderr}"
    # Parse the probe output into key=value pairs, then convert each
    # exported value into a structural Path domain so the assertion lives
    # in Path-equality space, not string-content space. PATH is split into
    # an ordered list of Path entries; the rest are single Paths.
    env_out: dict[str, str] = {}
    for line in sourced.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        env_out[key] = value

    path_entries = [Path(p) for p in env_out["PATH"].split(":")]
    actual = {
        "PATH_ENTRIES": path_entries,
        "ZDOTDIR": Path(env_out["ZDOTDIR"]),
        "BASH_ENV": Path(env_out["BASH_ENV"]),
        "ENV": Path(env_out["ENV"]),
    }
    expected = {
        "PATH_ENTRIES": [custom_root / "bin", probe_bin, Path(inherited_path)],
        "ZDOTDIR": custom_root / "shell",
        "BASH_ENV": custom_root / "shell" / ".bashenv",
        "ENV": custom_root / "shell" / ".profile",
    }
    assert actual == expected, f"wrapper exported env must match override-rooted contract: {actual!r}"


def test_configure_codex_writes_compaction_prompt_to_codex_dir(tmp_path: Path) -> None:
    """configure_codex copies the repo-owned compaction prompt to ~/.codex/CODEX.compaction.md."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    prompt_file = codex_dir / COMPACTION_PROMPT_FILENAME
    assert prompt_file.exists(), f"Compaction prompt must be written to {prompt_file}"
    source = (_REPO_ROOT / "teleclaude" / "install" / "settings" / COMPACTION_PROMPT_FILENAME).read_text(
        encoding="utf-8"
    )
    assert prompt_file.read_text(encoding="utf-8") == source, (
        "Deployed compaction prompt content must exactly match the repo-owned source file"
    )


def test_configure_codex_sets_compact_prompt_toml_key(tmp_path: Path) -> None:
    """configure_codex writes experimental_compact_prompt_file as an absolute path in config.toml."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config_path = codex_dir / "config.toml"
    assert config_path.exists(), "config.toml must be created by configure_codex"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert COMPACT_PROMPT_TOML_KEY in config, f"config.toml must contain '{COMPACT_PROMPT_TOML_KEY}'"
    value = config[COMPACT_PROMPT_TOML_KEY]
    assert isinstance(value, str) and value.strip(), f"'{COMPACT_PROMPT_TOML_KEY}' must be a non-empty file path string"
    # The value must be the absolute path to the deployed prompt — a relative path would silently break Codex
    expected_absolute_path = str(codex_dir / COMPACTION_PROMPT_FILENAME)
    assert value == expected_absolute_path, (
        f"'{COMPACT_PROMPT_TOML_KEY}' must be the absolute deployed path, not a relative placeholder. "
        f"Expected: {expected_absolute_path!r}. Got: {value!r}"
    )


def test_configure_codex_enables_native_hooks_feature_flag(tmp_path: Path) -> None:
    """configure_codex must enable the native Codex hooks runtime feature."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert config["features"]["hooks"] is True
    assert "codex_hooks" not in config["features"], (
        "codex_hooks is a legacy alias in codex 0.129+; the canonical key is 'hooks'"
    )
    assert "notify" not in config


def test_configure_codex_writes_feature_flag_inside_features_table(tmp_path: Path) -> None:
    """configure_codex must place the hooks feature flag under [features], not under a project block."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()
    (codex_dir / "config.toml").write_text(
        """
[features]
multi_agent = true

[projects."/repo-a"]
trust_level = "trusted"

[projects."/repo-b"]
trust_level = "trusted"
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert config["features"]["hooks"] is True
    assert "hooks" not in config["projects"]["/repo-a"]
    assert "hooks" not in config["projects"]["/repo-b"]


def test_configure_codex_writes_hooks_json_with_managed_events(tmp_path: Path) -> None:
    """configure_codex must install managed SessionStart/UserPromptSubmit/PreToolUse/Stop hooks."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert set(hooks["hooks"]) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"}

    start_command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    submit_command = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    pre_tool_command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    stop_command = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert "--agent codex" in start_command
    assert "--agent codex" in submit_command
    assert "--agent codex" in pre_tool_command
    assert "--agent codex" in stop_command
    assert "SessionStart" not in start_command
    assert "UserPromptSubmit" not in submit_command
    assert "PreToolUse" not in pre_tool_command
    assert " Stop" not in stop_command
    # PreToolUse matcher must be present so all tools fire the hook
    assert hooks["hooks"]["PreToolUse"][0].get("matcher") == ".*"


def test_configure_agy_refuses_to_overwrite_invalid_settings(tmp_path: Path) -> None:
    """An existing but malformed Antigravity settings file must stop the run, not be clobbered."""
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    settings_path = tmp_path / ".gemini" / "antigravity-cli" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    malformed = '{"colorScheme": "dark"'  # truncated JSON
    settings_path.write_text(malformed, encoding="utf-8")

    with patch("pathlib.Path.home", return_value=tmp_path):
        with pytest.raises(RuntimeError):
            configure_agy(tmp_path)

    assert settings_path.read_text(encoding="utf-8") == malformed


def test_configure_codex_persists_managed_hook_trust_state(tmp_path: Path) -> None:
    """configure_codex must pre-trust the three TeleClaude codex hooks in config.toml.

    Codex 0.129+ silently drops execution of any hook whose ``trusted_hash`` in
    ``[hooks.state."<key>"]`` does not match its computed ``currentHash``.
    Without this entry, every fresh codex session ignores SessionStart, Stop,
    and UserPromptSubmit until the user runs ``/hooks`` and trusts each one.
    """
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    state = config.get("hooks", {}).get("state", {})
    assert state, "config.toml must persist hooks.state for managed codex hooks"

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    hooks_json = json.loads(hooks_path.read_text(encoding="utf-8"))
    receiver_command = hooks_json["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    expected = build_codex_managed_hook_state(
        hooks_path=hooks_path,
        receiver_command=receiver_command,
        positions={
            "session_start": (0, 0),
            "user_prompt_submit": (0, 0),
            "pre_tool_use": (0, 0),
            "stop": (0, 0),
        },
    )

    for key, entry in expected.items():
        assert key in state, f"missing trust entry for {key}"
        assert state[key].get("trusted_hash") == entry["trusted_hash"], (
            f"trusted_hash for {key} must match codex's computed currentHash"
        )


def test_configure_codex_trust_keys_track_foreign_block_offsets(tmp_path: Path) -> None:
    """Foreign blocks already in hooks.json shift TeleClaude managed handlers to
    higher (group_index, handler_index) positions; the trusted_hash key must
    follow or codex will silently drop the managed hook for failing the trust
    check."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [{"type": "command", "command": "/usr/local/bin/foreign-tool"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    state = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))["hooks"]["state"]
    expected_key = f"{hooks_path}:session_start:1:0"
    assert expected_key in state, (
        f"foreign hook at group_index 0 must shift the TeleClaude managed key to {expected_key}"
    )
    assert f"{hooks_path}:session_start:0:0" not in state


def test_configure_codex_preserves_foreign_state_in_same_hooks_json(tmp_path: Path) -> None:
    """A foreign hook entry under the same hooks.json path must survive telec init.

    Earlier the merge stripped any state key whose prefix matched ``{hooks_path}:``,
    deleting unrelated entries. The contract is to replace only the exact keys
    we own.
    """
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    # post_tool_use is cataloged in HOOK_EVENT_MAP but not a managed trust label;
    # entries under labels we do not manage must survive intact.
    foreign_key = f"{hooks_path}:post_tool_use:0:0"
    foreign_hash = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        f'[hooks.state."{foreign_key}"]\n  trusted_hash = "{foreign_hash}"\n',
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    state = tomllib.loads(config_path.read_text(encoding="utf-8"))["hooks"]["state"]
    assert state.get(foreign_key, {}).get("trusted_hash") == foreign_hash, (
        "foreign entry under the same hooks.json path must be preserved"
    )


def test_configure_codex_strips_every_duplicate_managed_position(tmp_path: Path) -> None:
    """Multiple old TeleClaude handlers for the same event must all be stripped.

    A user (or a previous installer) could end up with several TeleClaude
    handlers at distinct positions inside hooks.json. Every persisted
    ``hooks.state`` key for those old positions has to be removed; otherwise
    a non-current one survives and a foreign handler that later moves into
    that index inherits the stale TeleClaude trust.
    """
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    receiver_command = f'{receiver} --agent codex --cwd "$PWD"'
    tc_block = {
        "matcher": "startup|resume",
        "hooks": [
            {
                "type": "command",
                "command": receiver_command,
                "statusMessage": "Loading session notes",
            }
        ],
    }
    foreign_block = {
        "matcher": "resume",
        "hooks": [{"type": "command", "command": "/usr/local/bin/foreign-tool"}],
    }
    # Three TeleClaude blocks followed by a foreign block. After the merge
    # every TC is stripped (each block becomes empty and is dropped), the
    # foreign block stays, and TC is re-appended at the tail. The merge
    # leaves new TC at (1, 0) and old TC at [(0, 0), (1, 0), (2, 0)] — the
    # earliest position is the bug-revealing one.
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        deepcopy(tc_block),
                        deepcopy(tc_block),
                        deepcopy(tc_block),
                        deepcopy(foreign_block),
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    stale_keys = [
        f"{hooks_path}:session_start:0:0",
        f"{hooks_path}:session_start:1:0",
        f"{hooks_path}:session_start:2:0",
    ]
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        "\n".join(
            f'[hooks.state."{key}"]\n  trusted_hash = "sha256:stale-{idx}"\n' for idx, key in enumerate(stale_keys)
        ),
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    state = tomllib.loads(config_path.read_text(encoding="utf-8"))["hooks"]["state"]
    new_managed_key = f"{hooks_path}:session_start:1:0"

    for idx, stale_key in enumerate(stale_keys):
        if stale_key == new_managed_key:
            assert state[stale_key]["trusted_hash"] != f"sha256:stale-{idx}", (
                "new managed key must carry the freshly computed trusted_hash"
            )
            continue
        assert stale_key not in state, (
            f"every old TeleClaude position must be stripped; {stale_key} leaked through "
            "(stale TeleClaude trust would attach to whatever handler now sits there)"
        )


def test_configure_codex_remaps_foreign_trust_when_compaction_shifts_indices(tmp_path: Path) -> None:
    """If TeleClaude shares a hook block with a foreign handler, removing TC from
    that block compacts the remaining handlers and shifts their indices. Any
    user-trusted foreign handler must keep working: its ``trusted_hash`` entry
    has to migrate to the new ``(group, handler)`` key, otherwise codex looks
    up the old key, finds nothing matching the foreign hook's currentHash, and
    silently disables it.
    """
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    receiver_command = f'{receiver} --agent codex --cwd "$PWD"'
    # Single block with TWO handlers: TeleClaude at (0, 0), foreign at (0, 1).
    # The merge strips TC and compacts foreign down to (0, 0), then re-appends TC at (1, 0).
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|resume",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": receiver_command,
                                    "statusMessage": "Loading session notes",
                                },
                                {"type": "command", "command": "/usr/local/bin/foreign-tool"},
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    foreign_old_key = f"{hooks_path}:session_start:0:1"
    foreign_hash = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        f'[hooks.state."{foreign_old_key}"]\n  trusted_hash = "{foreign_hash}"\n',
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    state = tomllib.loads(config_path.read_text(encoding="utf-8"))["hooks"]["state"]
    foreign_new_key = f"{hooks_path}:session_start:0:0"

    assert state.get(foreign_new_key, {}).get("trusted_hash") == foreign_hash, (
        "foreign trust must migrate from old position (0,1) to compacted position (0,0)"
    )
    assert foreign_old_key not in state, (
        "stale foreign trust entry at the original position must not linger after compaction"
    )


def test_configure_codex_preserves_user_trusted_foreign_managed_event(tmp_path: Path) -> None:
    """A user-trusted foreign hook for one of our managed event labels must keep its trust.

    If hooks.json holds both a foreign SessionStart and a TeleClaude SessionStart, both
    can carry their own trusted_hash entries. Stripping every key under the managed
    event-label prefix would silently disable the foreign hook on the next telec init.
    Trust deletion must be position-targeted: only the keys at the actual TeleClaude
    handler positions are stripped.
    """
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [{"type": "command", "command": "/usr/local/bin/foreign-tool"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    foreign_key = f"{hooks_path}:session_start:0:0"
    foreign_hash = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        f'[hooks.state."{foreign_key}"]\n  trusted_hash = "{foreign_hash}"\n',
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    state = tomllib.loads(config_path.read_text(encoding="utf-8"))["hooks"]["state"]

    assert state.get(foreign_key, {}).get("trusted_hash") == foreign_hash, (
        "user-trusted foreign hook at a managed event label must keep its trusted_hash; "
        "telec init only owns the TeleClaude handler position"
    )

    new_managed_key = f"{hooks_path}:session_start:1:0"
    assert new_managed_key in state, "TeleClaude managed key at the shifted position must be written"
    assert state[new_managed_key]["trusted_hash"].startswith("sha256:")
    assert state[new_managed_key]["trusted_hash"] != foreign_hash


def test_configure_codex_migrates_user_disable_when_managed_hook_shifts(tmp_path: Path) -> None:
    """When a foreign block shifts a TeleClaude hook to a new (group, handler) index,
    a previously persisted ``enabled = false`` must migrate to the new key. Otherwise
    the foreign hook now occupying the old index would inherit the disable, and the
    real TeleClaude hook would silently re-enable.
    """
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    receiver_command = f'{receiver} --agent codex --cwd "$PWD"'
    # Existing hooks.json: TeleClaude at (0, 0), foreign appended at (1, 0).
    # The merge strips TC from its block and re-appends at the tail, shifting TC to (1, 0).
    hooks_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|resume",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": receiver_command,
                                    "statusMessage": "Loading session notes",
                                }
                            ],
                        },
                        {
                            "matcher": "resume",
                            "hooks": [{"type": "command", "command": "/usr/local/bin/foreign-tool"}],
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    old_managed_key = f"{hooks_path}:session_start:0:0"
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        f'[hooks.state."{old_managed_key}"]\n  enabled = false\n  trusted_hash = "sha256:stale"\n',
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    state = tomllib.loads(config_path.read_text(encoding="utf-8"))["hooks"]["state"]
    new_managed_key = f"{hooks_path}:session_start:1:0"

    assert old_managed_key not in state, (
        "stale TeleClaude key at the old position must be dropped after the merge shifts TC; "
        "otherwise the foreign hook now at (0,0) would inherit our user's enabled=false"
    )
    assert state[new_managed_key]["enabled"] is False, (
        "user-set enabled=false must migrate forward when the managed hook shifts position"
    )
    assert state[new_managed_key]["trusted_hash"].startswith("sha256:")


def test_configure_codex_preserves_user_disable_on_managed_hook(tmp_path: Path) -> None:
    """A user's explicit ``enabled = false`` via /hooks must survive ``telec init``.

    The installer always rewrites ``trusted_hash`` (it must match the current
    command), but the ``enabled`` flag is the user's deliberate override and
    must not be silently flipped back on by re-running the installer.
    """
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    hooks_path = codex_dir / CODEX_HOOKS_FILENAME
    stop_key = f"{hooks_path}:stop:0:0"
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        f'[hooks.state."{stop_key}"]\n  enabled = false\n  trusted_hash = "sha256:stale"\n',
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    stop_entry = config["hooks"]["state"][stop_key]
    assert stop_entry["enabled"] is False, "user's explicit enabled=false must be preserved"
    assert stop_entry["trusted_hash"] != "sha256:stale", "trusted_hash must be rewritten to match the current command"
    assert stop_entry["trusted_hash"].startswith("sha256:")


def test_configure_codex_preserves_foreign_hook_trust_entries(tmp_path: Path) -> None:
    """Re-running configure_codex must not delete unrelated [hooks.state] entries."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    foreign_key = "/some/foreign/hooks.json:session_start:0:0"
    foreign_hash = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        f'[hooks.state."{foreign_key}"]\n  trusted_hash = "{foreign_hash}"\n',
        encoding="utf-8",
    )

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    state = config["hooks"]["state"]
    assert foreign_key in state, "foreign hook trust entry must be preserved"
    assert state[foreign_key]["trusted_hash"] == foreign_hash


def test_configure_codex_compaction_prompt_deployment_is_idempotent(tmp_path: Path) -> None:
    """Running configure_codex twice produces identical config.toml output."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with patch("pathlib.Path.home", return_value=tmp_path):
        configure_codex(tmp_path)
        config_after_first = (codex_dir / "config.toml").read_text(encoding="utf-8")

        configure_codex(tmp_path)
        config_after_second = (codex_dir / "config.toml").read_text(encoding="utf-8")

    assert config_after_first == config_after_second, (
        "configure_codex must be idempotent: config.toml must not change on re-run"
    )


def test_compact_prompt_key_set_when_source_exists_even_if_overrides_omit_it(tmp_path: Path) -> None:
    """The experimental_compact_prompt_file key must be present in config.toml when
    the compaction prompt source file exists, regardless of whether codex.toml
    declares the key. The runtime deploys the prompt and resolves its path."""
    custom_settings_dir = tmp_path / "custom-settings"
    custom_settings_dir.mkdir()
    (custom_settings_dir / COMPACTION_PROMPT_FILENAME).write_text("# compaction prompt\n", encoding="utf-8")
    (custom_settings_dir / "codex.toml").write_text('sandbox_mode = "danger-full-access"\n', encoding="utf-8")

    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(configure_agent_cli, "SETTINGS_DIR", custom_settings_dir),
    ):
        configure_codex(tmp_path)

    config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert COMPACT_PROMPT_TOML_KEY in config, (
        f"config.toml must contain '{COMPACT_PROMPT_TOML_KEY}' when the prompt source "
        "file exists — the runtime deploys the prompt independently of the overrides file"
    )
    expected = str(codex_dir / COMPACTION_PROMPT_FILENAME)
    assert config[COMPACT_PROMPT_TOML_KEY] == expected


def test_configure_codex_omits_compact_prompt_key_when_prompt_source_missing(tmp_path: Path) -> None:
    """configure_codex skips experimental_compact_prompt_file when the source prompt file is missing."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    receiver.parent.mkdir(parents=True)
    receiver.touch()

    broken_settings_dir = tmp_path / "broken-settings"
    broken_settings_dir.mkdir()
    (broken_settings_dir / "codex.toml").write_text(
        f'{COMPACT_PROMPT_TOML_KEY} = "{COMPACTION_PROMPT_FILENAME}"\n',
        encoding="utf-8",
    )

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(configure_agent_cli, "SETTINGS_DIR", broken_settings_dir),
    ):
        configure_codex(tmp_path)

    config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
    assert COMPACT_PROMPT_TOML_KEY not in config, (
        "configure_codex must not point config.toml at a compaction prompt file "
        "when the source prompt asset is unavailable"
    )


def test_install_hooks_module_no_longer_exists_on_disk() -> None:
    """The old module path must be absent after the rename — no silent co-existence."""
    assert not (_REPO_ROOT / "teleclaude" / "install" / "install_hooks.py").exists()


def test_bin_init_entry_point_no_longer_exists_at_old_path() -> None:
    """The old CLI entry point stub must be absent after the rename."""
    assert not (_REPO_ROOT / "bin" / "init" / "install_hooks.py").exists()


# ---------------------------------------------------------------------------
# R1 — Internal reference updates
# ---------------------------------------------------------------------------


def test_guardrails_exclusion_list_references_renamed_module() -> None:
    """guardrails.py loose-dict exclusion list must reference configure_agent_cli.py after the rename."""
    content = (_REPO_ROOT / "tools" / "lint" / "guardrails.py").read_text(encoding="utf-8")
    assert "configure_agent_cli.py" in content, (
        "tools/lint/guardrails.py must list configure_agent_cli.py in its exclusion list"
    )


def test_init_flow_does_not_configure_agent_cli() -> None:
    """init_flow.py must no longer own machine-global agent CLI configuration."""
    assert not hasattr(init_flow, "configure_agent_cli")


# ---------------------------------------------------------------------------
# R2 — Shell wrapper inlining
# ---------------------------------------------------------------------------


def test_setup_agent_hooks_shell_script_removed() -> None:
    """bin/init/setup_agent_hooks.sh must no longer exist after install.sh owns setup."""
    assert not (_REPO_ROOT / "bin" / "init" / "setup_agent_hooks.sh").exists(), (
        "bin/init/setup_agent_hooks.sh must be removed — its invocation is inlined into bin/install.sh"
    )


def test_bin_init_does_not_source_removed_script() -> None:
    """bin/init.sh must be removed after setup ownership moves to install/start."""
    assert not (_REPO_ROOT / "bin" / "init.sh").exists()


def test_agent_cli_configurator_entry_point_is_callable() -> None:
    """The agent CLI configurator remains importable from its module home."""
    assert callable(configure_agent_cli.main)


# ---------------------------------------------------------------------------
# R3 — Repo-owned compaction prompt source
# ---------------------------------------------------------------------------

_SETTINGS_COMPACTION_PROMPT = _REPO_ROOT / "teleclaude" / "install" / "settings" / COMPACTION_PROMPT_FILENAME


def test_compaction_prompt_source_file_exists_in_settings() -> None:
    """A compaction prompt file must be stored in teleclaude/install/settings/ for version-controlled distribution."""
    assert _SETTINGS_COMPACTION_PROMPT.exists(), (
        f"Compaction prompt must exist at {_SETTINGS_COMPACTION_PROMPT} alongside other install-time settings"
    )


def test_compaction_prompt_instructs_preservation_of_marked_content() -> None:
    """The compaction prompt must instruct Codex to preserve content between the context-preservation markers."""
    content = _SETTINGS_COMPACTION_PROMPT.read_text(encoding="utf-8")
    assert "TELECLAUDE_CONTEXT_PRESERVATION_START" in content, (
        "Compaction prompt must reference TELECLAUDE_CONTEXT_PRESERVATION_START"
    )
    assert "TELECLAUDE_CONTEXT_PRESERVATION_END" in content, (
        "Compaction prompt must reference TELECLAUDE_CONTEXT_PRESERVATION_END"
    )


# ---------------------------------------------------------------------------
# R6 — Prototype files absent (regression guards)
# ---------------------------------------------------------------------------


def test_prototype_codex_config_toml_not_in_repository() -> None:
    """.codex/config.toml must not be committed — superseded by the repo-managed install settings path."""
    assert not (_REPO_ROOT / ".codex" / "config.toml").exists(), (
        ".codex/config.toml must not exist in the repository — "
        "use teleclaude/install/settings/codex.toml for Codex settings"
    )


def test_prototype_codex_compaction_md_not_in_repository() -> None:
    """.codex/CODEX.compaction.md must not be committed — superseded by teleclaude/install/settings/."""
    assert not (_REPO_ROOT / ".codex" / COMPACTION_PROMPT_FILENAME).exists(), (
        ".codex/CODEX.compaction.md must not exist in the repository — "
        f"the canonical source is teleclaude/install/settings/{COMPACTION_PROMPT_FILENAME}"
    )


# ---------------------------------------------------------------------------
# Characterization coverage carried forward from test_install_hooks.py
# ---------------------------------------------------------------------------


class TestExtractReceiverScript:
    """Tests for _extract_receiver_script."""

    def test_managed_receiver_path_normalizes_to_token(self) -> None:
        """Any TeleClaude-managed receiver script collapses to RECEIVER_TOKEN regardless of filename variant."""
        assert (
            configure_agent_cli._extract_receiver_script("python /tmp/receiver/__main__.py --agent codex") == "receiver"
        )


class TestMergeHooks:
    """Tests for merge_hooks."""

    def test_replaces_existing_receiver_hook_but_keeps_foreign_hooks(self) -> None:
        """merge_hooks replaces an existing receiver hook but preserves non-receiver hooks."""
        existing = {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"command": "/old/receiver.py --agent claude"},
                        {"command": "/usr/bin/custom-hook"},
                    ],
                }
            ]
        }
        new = {"Stop": {"command": "/new/receiver.py --agent claude"}}

        merged = configure_agent_cli.merge_hooks(existing, new)

        hooks = merged["Stop"][0]["hooks"]
        assert hooks == [{"command": "/usr/bin/custom-hook"}, {"command": "/new/receiver.py --agent claude"}]


class TestPruneAgentHooks:
    """Tests for _prune_agent_hooks."""

    def test_removes_teleclaude_hooks_from_disallowed_events(self) -> None:
        """_prune_agent_hooks removes receiver hooks for events not in allowed_events."""
        existing = {
            "Stop": [{"matcher": "*", "hooks": [{"command": "/tmp/receiver.py --agent claude"}]}],
            "SessionStart": [{"matcher": "*", "hooks": [{"command": "/tmp/receiver.py --agent claude"}]}],
            "custom": {"preserve": True},
        }

        pruned = configure_agent_cli._prune_agent_hooks(existing, {"SessionStart"})

        assert "Stop" not in pruned
        assert pruned["SessionStart"][0]["hooks"] == [{"command": "/tmp/receiver.py --agent claude"}]
        assert pruned["custom"] == {"preserve": True}


class TestCodexMcpConfig:
    """Tests for MCP server merge in configure_codex."""

    def test_configure_codex_merges_managed_mcp_servers(self, tmp_path: Path) -> None:
        """configure_codex merges managed MCP servers with type=stdio into config.toml."""
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        receiver = tmp_path / "teleclaude" / "hooks" / "receiver" / "__main__.py"
        receiver.parent.mkdir(parents=True)
        receiver.touch()
        mcp_json = tmp_path / "mcp.json"
        mcp_json.write_text(
            json.dumps({"mcpServers": {"test-server": {"command": "uvx", "args": ["a"]}}}),
            encoding="utf-8",
        )

        with patch("pathlib.Path.home", return_value=tmp_path):
            configure_codex(tmp_path)

        config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
        assert "test-server" in config.get("mcp_servers", {})
        server = config["mcp_servers"]["test-server"]
        assert server["type"] == "stdio"
        assert server["command"] == "uvx"


class TestResolveStateRoot:
    """Tests for resolve_state_root."""

    def test_follows_worktree_gitdir_to_main_repository(self, tmp_path: Path) -> None:
        """resolve_state_root follows gitdir pointer in worktrees to find the main repo."""
        main_repo = tmp_path / "main"
        worktree = tmp_path / "worktree"
        gitdir = main_repo / ".git" / "worktrees" / "demo"
        gitdir.mkdir(parents=True)
        worktree.mkdir()
        (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

        resolved = configure_agent_cli.resolve_state_root(worktree)

        assert resolved == main_repo

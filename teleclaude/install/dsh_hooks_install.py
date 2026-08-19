"""DeepSeek Harness installer wiring: receiver hooks config, machine-local
cordis patch row, and the restricted launch overlay.

Mirrors the codex_hooks_install module split: per-agent installer logic lives
outside configure_agent_cli.py, importing that module's shared hook helpers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from teleclaude.core.events import AgentHookEvents
from teleclaude.install.configure_agent_cli import (
    HOOKS_KEY,
    _build_hook_invocation,
    _build_hook_map,
    _filter_receiver_handled_events,
    _load_json_settings,
    merge_hooks,
)
from teleclaude.paths import TELECLAUDE_HOME
from teleclaude.project_root import resolve_project_root


def configure_dsh(repo_root: Path) -> None:
    """Configure DeepSeek Harness hooks (dsh-hooks plugin fork).

    Writes the global ~/.dsh/hooks.json (respecting $DSH_HOME) in the nested
    Claude Code settings shape, merging idempotently with any existing user
    hooks (dedup by receiver script path, matching merge_hooks semantics).
    """
    repo_root = resolve_project_root(repo_root)
    receiver_script = repo_root / "teleclaude" / "hooks" / "receiver" / "__main__.py"
    if not receiver_script.exists():
        print(f"Warning: DeepSeek receiver not found at {receiver_script}")
        return

    os.chmod(receiver_script, 0o755)
    dsh_home = Path(os.environ.get("DSH_HOME", Path.home() / ".dsh"))
    hooks_path = dsh_home / "hooks.json"
    hooks_path.parent.mkdir(parents=True, exist_ok=True)

    settings = _load_json_settings(hooks_path, label="DeepSeek Harness")
    if settings is None:
        return

    receiver_invocation = _build_hook_invocation(receiver_script)
    hooks_map = _build_hook_map(
        receiver_invocation,
        "deepseek",
        _filter_receiver_handled_events(AgentHookEvents.HOOK_EVENT_MAP["deepseek"]),
    )
    # The receiver legitimately writes outside the agent workspace (state dir,
    # outbox DB), so its hooks declare the explicit unsandboxed opt-in the
    # dsh-hooks plugin requires for full-access hook execution.
    for hook_def in hooks_map.values():
        hook_def["unsandboxed"] = True

    # Accept both the nested CC shape ({"hooks": {...}}) and a flat event map.
    existing_hooks = settings.get(HOOKS_KEY, settings)
    if not isinstance(existing_hooks, dict):
        existing_hooks = {}
    merged_hooks = merge_hooks(existing_hooks, hooks_map)

    out_settings = dict(settings)
    out_settings[HOOKS_KEY] = merged_hooks
    out_settings.setdefault("$schema", "https://json.schemastore.org/claude-code-settings.json")

    hooks_path.write_text(json.dumps(out_settings, indent=2) + "\n")
    print(f"DeepSeek Harness hooks configured in {hooks_path}")

    _deploy_dsh_restricted_patch(repo_root)
    _merge_dsh_cordis_patch(repo_root, dsh_home)


def _deploy_dsh_restricted_patch(repo_root: Path) -> None:
    """Deploy the restricted launch overlay to $TELECLAUDE_HOME.

    templates/dsh-restricted.patch.yml is copied to
    $TELECLAUDE_HOME/dsh-restricted.patch.yml (idempotent: rewritten only when
    the content differs). The restricted profile flags in AGENT_PROTOCOL
    reference it via $TELECLAUDE_HOME, which the pane shell expands.
    """
    src = repo_root / "templates" / "dsh-restricted.patch.yml"
    if not src.exists():
        print(f"Warning: dsh restricted patch template not found at {src}")
        return
    dst = TELECLAUDE_HOME / "dsh-restricted.patch.yml"
    content = src.read_text()
    if dst.exists() and dst.read_text() == content:
        print(f"DeepSeek restricted patch already installed at {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content)
    print(f"DeepSeek restricted patch installed at {dst}")


def _merge_dsh_cordis_patch(repo_root: Path, dsh_home: Path) -> None:
    """Merge the dsh-hooks plugin row into the machine-local cordis patch layer.

    ~/.dsh/cordis.patch.yml is applied to EVERY profile after that profile's
    own cordis.patch.yml, so the row there activates the hooks plugin in every
    profile (existing and future). The package itself is installed per profile
    by bin/install.sh's setup_dsh_integration. The merge is a TEXT append — the
    file legitimately contains !!js expressions that a YAML round-trip would
    destroy — and is idempotent (skips when the row is already present).
    """
    patch_path = dsh_home / "cordis.patch.yml"
    template_path = repo_root / "templates" / "dsh-cordis.patch.yml"
    if not template_path.exists():
        print(f"Warning: dsh cordis patch template not found at {template_path}")
        return
    patch_text = template_path.read_text()

    if patch_path.exists():
        existing = patch_path.read_text()
        if "id: dsh-hooks" in existing:
            print(f"dsh-hooks row already present in {patch_path}")
            return
        if not existing.endswith("\n"):
            existing += "\n"
        if not existing.endswith("\n\n"):
            existing += "\n"
        patch_path.write_text(existing + patch_text)
    else:
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(patch_text)
    print(f"dsh-hooks row merged into {patch_path}")

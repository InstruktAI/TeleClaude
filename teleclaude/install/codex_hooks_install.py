"""Plumbing for writing Codex ``hooks.json`` and the matching ``hooks.state`` trust entries.

Codex 0.129+ requires every User-layer hook to carry a matching ``trusted_hash``
in ``~/.codex/config.toml`` before it will be invoked. The functions here own
the hooks.json merge, the (group_index, handler_index) bookkeeping that codex's
trust keys depend on, and the ``hooks.state`` rewrite — extracted from
``configure_agent_cli`` so each module stays under the size limit.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from teleclaude.install.codex_hook_trust import build_codex_managed_hook_state, codex_hook_state_key

# Codex hook events expose two parallel naming systems: the camelCase event
# names that appear inside ``hooks.json`` (e.g. ``SessionStart``) and the
# snake_case labels that codex uses for ``hooks.state.<key>``. The trust hash
# tracks the snake_case label, so installer plumbing translates between the two.
CODEX_TRUST_LABEL_BY_HOOK_NAME: dict[str, str] = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "user_prompt_submit",
    "Stop": "stop",
}

# guard: loose-dict-func - hooks.json wire shape is dynamic JSON; merge return must mirror it
_HookBlock = dict[str, Any]
_PositionPair = tuple[int, int]
_MergeBlocksResult = tuple[list[_HookBlock], list[_PositionPair], dict[_PositionPair, _PositionPair]]


@dataclass(frozen=True)
class CodexHookWriteResult:
    """Outcome of rewriting ``hooks.json`` and the position bookkeeping the trust merge needs.

    ``new_positions`` reflects the freshly-written file. ``old_positions`` is
    captured from the file *before* mutation so the trust merge can drop stale
    keys and migrate any user-set ``enabled`` override forward. ``foreign_remap``
    maps each preserved foreign handler's old ``(group, handler)`` to its new
    position so foreign trust entries stay attached when TC removal compacts a
    mixed block.
    """

    new_positions: dict[str, list[tuple[int, int]]]
    old_positions: dict[str, list[tuple[int, int]]]
    foreign_remap: dict[str, dict[tuple[int, int], tuple[int, int]]]


def write_codex_hooks_json(
    hooks_path: Path,
    managed_hooks: dict[str, list[_HookBlock]],
    *,
    load_settings: Any,
    prune: Any,
    extract_receiver_script: Any,
) -> CodexHookWriteResult:
    """Write Codex native hooks while preserving foreign non-TeleClaude hooks.

    The three callable arguments wire this module to the rest of the installer
    without pulling in a circular dependency on ``configure_agent_cli``.
    """
    existing = load_settings(hooks_path, label="Codex hooks")
    if existing is None:
        return CodexHookWriteResult(new_positions={}, old_positions={}, foreign_remap={})

    existing_hooks = existing.get("hooks", {})
    if not isinstance(existing_hooks, dict):
        existing_hooks = {}

    old_positions: dict[str, list[tuple[int, int]]] = {
        event_name: _find_managed_positions_in_blocks(existing_hooks.get(event_name), extract_receiver_script)
        for event_name in managed_hooks
    }

    updated_hooks = prune(existing_hooks, set(managed_hooks.keys()))
    new_positions: dict[str, list[tuple[int, int]]] = {}
    foreign_remap: dict[str, dict[tuple[int, int], tuple[int, int]]] = {}
    for event_name, managed_blocks in managed_hooks.items():
        merged, positions, remap = _merge_codex_hook_blocks(
            existing_hooks.get(event_name),
            managed_blocks,
            extract_receiver_script,
        )
        updated_hooks[event_name] = merged
        new_positions[event_name] = positions
        foreign_remap[event_name] = remap

    with open(hooks_path, "w") as handle:
        json.dump({"hooks": updated_hooks}, handle, indent=2)
    return CodexHookWriteResult(
        new_positions=new_positions,
        old_positions=old_positions,
        foreign_remap=foreign_remap,
    )


def merge_codex_hook_trust_state(
    config: dict[str, object],  # guard: loose-dict - codex config.toml is dynamic TOML
    *,
    hooks_path: Path,
    receiver_command: str,
    new_positions: Mapping[str, tuple[int, int]],
    old_positions_by_label: Mapping[str, list[tuple[int, int]]],
    foreign_remap_by_label: Mapping[str, dict[tuple[int, int], tuple[int, int]]],
) -> None:
    """Pre-trust the TeleClaude-managed Codex hooks under ``[hooks.state]``.

    Strip only the exact ``hooks.state`` keys whose ``(group_index,
    handler_index)`` came from a TeleClaude-recognized handler — both the new
    positions written in this run and the positions where TeleClaude lived
    before mutation. Foreign trust entries survive verbatim, including
    user-trusted foreign hooks at our managed event labels.

    Removing TC from a mixed block compacts the remaining foreign handlers, so
    apply ``foreign_remap_by_label`` to move every preserved foreign trust
    entry from its old position key to its new one. Any user-set ``enabled``
    flag from a stripped TeleClaude key migrates to the new managed key for
    the same label.
    """
    managed = build_codex_managed_hook_state(
        hooks_path=hooks_path,
        receiver_command=receiver_command,
        positions=new_positions,
    )

    hooks_section = config.get("hooks")
    if not isinstance(hooks_section, dict):
        hooks_section = {}
    existing_state = hooks_section.get("state") if isinstance(hooks_section.get("state"), dict) else None

    new_keys_by_label = _build_keys(hooks_path, new_positions.items())
    old_keys_by_label = {
        label: list(_build_keys(hooks_path, ((label, pos) for pos in occurrences)).values())
        for label, occurrences in old_positions_by_label.items()
    }
    stale_keys: set[str] = set(new_keys_by_label.values())
    for keys in old_keys_by_label.values():
        stale_keys.update(keys)

    enabled_at_new_key, enabled_at_old_managed_key = _capture_enabled_overrides(
        existing_state=existing_state,
        new_keys_by_label=new_keys_by_label,
        old_keys_by_label=old_keys_by_label,
    )
    foreign_remap_keys = _build_foreign_remap_keys(hooks_path, foreign_remap_by_label)
    merged = _carry_over_existing_state(
        existing_state=existing_state,
        stale_keys=stale_keys,
        foreign_remap_keys=foreign_remap_keys,
    )

    for label, new_key in new_keys_by_label.items():
        managed_entry = managed.get(new_key)
        if managed_entry is None:
            continue
        entry: dict[str, object] = dict(managed_entry)  # guard: loose-dict - codex hooks.state entry shape
        if label in enabled_at_new_key:
            entry["enabled"] = enabled_at_new_key[label]
        elif label in enabled_at_old_managed_key:
            entry["enabled"] = enabled_at_old_managed_key[label]
        merged[new_key] = entry

    hooks_section["state"] = dict(sorted(merged.items()))
    config["hooks"] = hooks_section


def first_positions_per_label(
    positions_by_event: Mapping[str, list[tuple[int, int]]],
) -> dict[str, tuple[int, int]]:
    """Take the first managed handler per event and key it by snake_case trust label."""
    positions: dict[str, tuple[int, int]] = {}
    for hook_name, occurrences in positions_by_event.items():
        label = CODEX_TRUST_LABEL_BY_HOOK_NAME.get(hook_name)
        if label is None or not occurrences:
            continue
        positions[label] = occurrences[0]
    return positions


def all_positions_per_label(
    positions_by_event: Mapping[str, list[tuple[int, int]]],
) -> dict[str, list[tuple[int, int]]]:
    """Collect every managed handler position per event, keyed by snake_case trust label."""
    positions: dict[str, list[tuple[int, int]]] = {}
    for hook_name, occurrences in positions_by_event.items():
        label = CODEX_TRUST_LABEL_BY_HOOK_NAME.get(hook_name)
        if label is None or not occurrences:
            continue
        positions[label] = list(occurrences)
    return positions


def foreign_remap_per_label(
    remap_by_event: Mapping[str, dict[tuple[int, int], tuple[int, int]]],
) -> dict[str, dict[tuple[int, int], tuple[int, int]]]:
    """Translate foreign-handler position remaps to snake_case trust labels."""
    remap: dict[str, dict[tuple[int, int], tuple[int, int]]] = {}
    for hook_name, mapping in remap_by_event.items():
        label = CODEX_TRUST_LABEL_BY_HOOK_NAME.get(hook_name)
        if label is None or not mapping:
            continue
        remap[label] = dict(mapping)
    return remap


def _merge_codex_hook_blocks(
    existing_blocks: object,
    managed_blocks: list[_HookBlock],
    extract_receiver_script: Any,
) -> _MergeBlocksResult:
    """Replace TeleClaude receiver hooks while preserving foreign Codex hook blocks.

    Returns ``(merged_blocks, managed_positions, foreign_remap)``. ``foreign_remap``
    captures every preserved foreign handler's ``(group, handler)`` shift caused
    by TC removal, so trust state can follow the handler to its new position.
    """
    merged_blocks: list[_HookBlock] = []
    foreign_remap: dict[tuple[int, int], tuple[int, int]] = {}

    if isinstance(existing_blocks, list):
        for old_group_index, block in enumerate(existing_blocks):
            if not isinstance(block, dict):
                continue
            hooks_list = block.get("hooks", [])
            if not isinstance(hooks_list, list):
                merged_blocks.append(block)
                continue
            filtered_hooks: list[Any] = []
            preserved_old_handler_indices: list[int] = []
            for old_handler_index, hook in enumerate(hooks_list):
                if not isinstance(hook, dict):
                    filtered_hooks.append(hook)
                    preserved_old_handler_indices.append(old_handler_index)
                    continue
                if extract_receiver_script(hook.get("command", "")) is not None and _is_managed_receiver_command(
                    hook.get("command", ""), extract_receiver_script
                ):
                    continue
                filtered_hooks.append(hook)
                preserved_old_handler_indices.append(old_handler_index)
            if filtered_hooks:
                new_group_index = len(merged_blocks)
                updated_block = block.copy()
                updated_block["hooks"] = filtered_hooks
                merged_blocks.append(updated_block)
                for new_handler_index, old_handler_index in enumerate(preserved_old_handler_indices):
                    foreign_remap[(old_group_index, old_handler_index)] = (new_group_index, new_handler_index)

    managed_positions: list[tuple[int, int]] = []
    base_group_index = len(merged_blocks)
    for offset, block in enumerate(deepcopy(managed_blocks)):
        merged_blocks.append(block)
        for handler_index in range(len(block.get("hooks", []))):
            managed_positions.append((base_group_index + offset, handler_index))
    return merged_blocks, managed_positions, foreign_remap


def _is_managed_receiver_command(command: object, extract_receiver_script: Any) -> bool:
    """Return ``True`` when the command resolves to a TeleClaude-managed receiver script."""
    return bool(extract_receiver_script(command) == "receiver")


def _find_managed_positions_in_blocks(
    blocks: object,
    extract_receiver_script: Any,
) -> list[tuple[int, int]]:
    """Locate ``(group_index, handler_index)`` for TeleClaude handlers inside hooks.json blocks."""
    if not isinstance(blocks, list):
        return []
    positions: list[tuple[int, int]] = []
    for group_index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        hooks_list = block.get("hooks", [])
        if not isinstance(hooks_list, list):
            continue
        for handler_index, hook in enumerate(hooks_list):
            if not isinstance(hook, dict):
                continue
            if _is_managed_receiver_command(hook.get("command", ""), extract_receiver_script):
                positions.append((group_index, handler_index))
    return positions


def _build_keys(
    hooks_path: Path,
    items: Iterable[tuple[str, tuple[int, int]]],
) -> dict[str, str]:
    """Build ``{label: hooks.state-key}`` for an iterable of ``(label, (group, handler))`` pairs."""
    keys: dict[str, str] = {}
    for label, position in items:
        keys[label] = codex_hook_state_key(
            source_path=hooks_path,
            event_label=label,
            group_index=position[0],
            handler_index=position[1],
        )
    return keys


def _capture_enabled_overrides(
    *,
    existing_state: dict[str, object] | None,  # guard: loose-dict - codex hooks.state TOML
    new_keys_by_label: Mapping[str, str],
    old_keys_by_label: Mapping[str, list[str]],
) -> tuple[dict[str, bool], dict[str, bool]]:
    """Pick up ``enabled`` flags persisted at the current new key and at any prior TC key for migration."""
    at_new: dict[str, bool] = {}
    at_old: dict[str, bool] = {}
    if not isinstance(existing_state, dict):
        return at_new, at_old
    for label, new_key in new_keys_by_label.items():
        prior = existing_state.get(new_key)
        if isinstance(prior, dict) and "enabled" in prior:
            at_new[label] = bool(prior["enabled"])
    for label, old_keys in old_keys_by_label.items():
        for old_key in old_keys:
            prior = existing_state.get(old_key)
            if isinstance(prior, dict) and "enabled" in prior and label not in at_old:
                at_old[label] = bool(prior["enabled"])
    return at_new, at_old


def _build_foreign_remap_keys(
    hooks_path: Path,
    foreign_remap_by_label: Mapping[str, dict[tuple[int, int], tuple[int, int]]],
) -> dict[str, str]:
    """Translate per-label ``(old_pos -> new_pos)`` foreign remaps into ``hooks.state``-key remaps."""
    remap_keys: dict[str, str] = {}
    for label, mapping in foreign_remap_by_label.items():
        for old_pos, new_pos in mapping.items():
            if old_pos == new_pos:
                continue
            old_key = codex_hook_state_key(
                source_path=hooks_path,
                event_label=label,
                group_index=old_pos[0],
                handler_index=old_pos[1],
            )
            new_key = codex_hook_state_key(
                source_path=hooks_path,
                event_label=label,
                group_index=new_pos[0],
                handler_index=new_pos[1],
            )
            remap_keys[old_key] = new_key
    return remap_keys


def _carry_over_existing_state(
    *,
    existing_state: dict[str, object] | None,  # guard: loose-dict - codex hooks.state TOML
    stale_keys: set[str],
    foreign_remap_keys: Mapping[str, str],
) -> dict[str, dict[str, object]]:  # guard: loose-dict - codex hooks.state TOML
    """Copy non-stale entries forward, applying foreign-handler key remaps where applicable."""
    merged: dict[str, dict[str, object]] = {}  # guard: loose-dict - codex hooks.state TOML
    if not isinstance(existing_state, dict):
        return merged
    for key, value in existing_state.items():
        if not isinstance(value, dict):
            continue
        if key in stale_keys:
            continue
        target_key = foreign_remap_keys.get(key, key)
        merged[target_key] = dict(value)
    return merged

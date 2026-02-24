"""Regression tests for diagram extractors under scripts/diagrams."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "diagrams"


def _load_script_module(name: str) -> ModuleType:
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"scripts.diagrams.{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_runtime_matrix_regression() -> None:
    module = _load_script_module("extract_runtime_matrix")

    events_tree = ast.parse(module.EVENTS_PATH.read_text(encoding="utf-8"), filename=str(module.EVENTS_PATH))
    agent_tree = ast.parse(module.AGENT_TYPES_PATH.read_text(encoding="utf-8"), filename=str(module.AGENT_TYPES_PATH))
    constants_tree = ast.parse(module.CONSTANTS_PATH.read_text(encoding="utf-8"), filename=str(module.CONSTANTS_PATH))

    event_counts = module.parse_hook_event_counts(events_tree)
    agent_names = module.parse_agent_names(agent_tree)
    adapter_features = module.detect_adapter_features(agent_names)
    protocol_features = module.parse_agent_protocol_features(constants_tree)
    checkpoint_blocking = module.detect_checkpoint_blocking_features(agent_names)

    mermaid = module.generate_mermaid(
        event_counts=event_counts,
        agent_names=agent_names,
        adapter_features=adapter_features,
        protocol_features=protocol_features,
        checkpoint_blocking=checkpoint_blocking,
    )

    assert "claude --> feat_hook_normalization" in mermaid
    assert "codex --> feat_hook_normalization" in mermaid
    assert "codex --> feat_session_tracking" in mermaid
    assert "codex --> feat_prompt_capture" in mermaid
    assert "codex --> feat_notification_capture" in mermaid
    assert "codex --> feat_transcript_discovery" not in mermaid
    assert "claude --> feat_hook_stop_blocking" in mermaid
    assert "codex --> feat_hook_stop_blocking" not in mermaid


def test_extract_events_regression() -> None:
    module = _load_script_module("extract_events")

    events_tree = ast.parse(module.EVENTS_PATH.read_text(encoding="utf-8"), filename=str(module.EVENTS_PATH))
    coordinator_tree = ast.parse(
        module.COORDINATOR_PATH.read_text(encoding="utf-8"), filename=str(module.COORDINATOR_PATH)
    )

    hook_map = module.parse_hook_event_map(events_tree)
    constants = module.parse_agent_hook_constants(events_tree)
    dispatch = module.parse_handler_dispatch(coordinator_tree)

    mermaid = module.generate_mermaid(hook_map, dispatch, constants)

    assert "claude -->|SessionStart| session_start" in mermaid
    assert "session_start --> h_handle_session_start" in mermaid
    assert "agent_stop --> h_handle_agent_stop" in mermaid


def test_extract_state_machines_regression() -> None:
    module = _load_script_module("extract_state_machines")

    source = module.CORE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module.CORE_PATH))

    phase_statuses = module.parse_enum_members(tree, "PhaseStatus")
    defaults = module.parse_default_phase_state(tree)
    post_completion = module.parse_post_completion_text(tree)

    phase_transitions = module.parse_phase_transitions(defaults, post_completion)

    mermaid = module.generate_mermaid(phase_statuses, phase_transitions)

    assert "p_PENDING --> p_COMPLETE: next-build" in mermaid
    assert "p_PENDING --> p_APPROVED: next-review" in mermaid
    assert "p_APPROVED --> p_PENDING: next-fix-review" in mermaid


def test_extract_commands_regression() -> None:
    module = _load_script_module("extract_commands")

    commands = module.parse_all_commands()
    tree = ast.parse(
        module.NEXT_MACHINE_CORE_PATH.read_text(encoding="utf-8"), filename=str(module.NEXT_MACHINE_CORE_PATH)
    )

    dispatch_edges = module.parse_dispatch_edges(tree)
    completion_edges = module.parse_post_completion_next_calls(tree)

    mermaid = module.generate_mermaid(commands, dispatch_edges, completion_edges)

    assert "next_work -->|dispatch| next_build" in mermaid
    assert "next_work -->|dispatch| next_review" in mermaid
    assert "next_fix_review -->|post-completion| next_work" in mermaid


def test_extract_data_model_regression() -> None:
    module = _load_script_module("extract_data_model")
    tree = ast.parse(module.DB_MODELS_PATH.read_text(encoding="utf-8"), filename=str(module.DB_MODELS_PATH))

    models = module.parse_sqlmodel_classes(tree)
    mermaid = module.generate_mermaid(models)

    assert models
    assert "erDiagram" in mermaid
    assert "session" in mermaid


@pytest.mark.timeout(5)
def test_extract_modules_regression() -> None:
    module = _load_script_module("extract_modules")

    deps = module.extract_package_deps()
    mermaid = module.generate_mermaid(deps)

    assert deps
    assert "flowchart TD" in mermaid
    assert "core -->" in mermaid or "--> core" in mermaid

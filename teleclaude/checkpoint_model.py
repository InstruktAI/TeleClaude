"""Effective checkpoint model: base ⊕ overlay merge, the scope matcher, and resolution.

One matcher and one resolution source serve all three checkpoint consumers — the
`agent_stop` hook engine, the commit-obligation ledger, and the integrator
post-merge maintenance path — so a path that owes an action in one owes the
equivalent in the others. Action selection is structured glob + evidence matching
over the merged declaration only; no runtime language or content detection.
"""

from __future__ import annotations

from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_project_config
from teleclaude.constants import (
    CHECKPOINT_BASE_ACTIONS,
    CHECKPOINT_BASE_AGENTS_BINDING_INDEX,
    CHECKPOINT_BASE_BINDINGS,
    CHECKPOINT_BASE_DOCS_BINDING_INDEX,
    CheckpointAction,
    CheckpointBinding,
    CheckpointModel,
    CheckpointScope,
    _compile_glob,
)

logger = get_logger(__name__)

__all__ = [
    "base_checkpoint_model",
    "load_checkpoint_model",
    "merge_overlay",
    "scope_matches",
    "scopes_for_action",
    "triggered_action_ids",
]


def _glob_matches(path: str, pattern: str) -> bool:
    """Return True if path matches the glob pattern (** support, * within segment)."""
    return bool(_compile_glob(pattern).match(path))


def scope_matches(path: str, scope: CheckpointScope) -> bool:
    """Apply the single scope rule: include → override → exclude."""
    if not any(_glob_matches(path, pattern) for pattern in scope.include):
        return False
    if scope.override and any(_glob_matches(path, pattern) for pattern in scope.override):
        return True
    if scope.exclude and any(_glob_matches(path, pattern) for pattern in scope.exclude):
        return False
    return True


def triggered_action_ids(files: list[str], model: CheckpointModel) -> set[str]:
    """Return the set of action ids any changed file owes under the merged model."""
    owed: set[str] = set()
    for binding in model.bindings:
        if any(scope_matches(path, binding.scope) for path in files):
            owed.update(binding.actions)
    return owed


def scopes_for_action(model: CheckpointModel, action_id: str) -> list[CheckpointScope]:
    """Return the scopes of every binding that references the given action id."""
    return [binding.scope for binding in model.bindings if action_id in binding.actions]


def _fill_slug(action: CheckpointAction, project_slug: str) -> CheckpointAction:
    """Substitute the ``{slug}`` placeholder in an action's run/evidence strings."""
    if "{slug}" not in action.run and not any("{slug}" in marker for marker in action.evidence):
        return action
    return CheckpointAction(
        id=action.id,
        run=action.run.replace("{slug}", project_slug),
        evidence=tuple(marker.replace("{slug}", project_slug) for marker in action.evidence),
        main_only=action.main_only,
        precedence=action.precedence,
        evidence_must_follow_last_mutation=action.evidence_must_follow_last_mutation,
    )


def base_checkpoint_model(project_slug: str) -> CheckpointModel:
    """The platform-universal base with ``{slug}`` filled, no overlay merged."""
    actions = {action_id: _fill_slug(action, project_slug) for action_id, action in CHECKPOINT_BASE_ACTIONS.items()}
    return CheckpointModel(actions=actions, bindings=CHECKPOINT_BASE_BINDINGS)


def _scope_from_cfg(scope_cfg: object) -> CheckpointScope:
    """Build a frozen scope from a Pydantic ``CheckpointScopeConfig``."""
    return CheckpointScope(
        include=tuple(getattr(scope_cfg, "include", []) or []),
        exclude=tuple(getattr(scope_cfg, "exclude", []) or []),
        override=tuple(getattr(scope_cfg, "override", []) or []),
    )


def merge_overlay(base: CheckpointModel, overlay: object | None, project_slug: str) -> CheckpointModel:
    """Merge a project-declared overlay (``CheckpointConfig``) atop the base model.

    Registry: overlay actions extend or override base actions by id. Bindings: the
    conventional ``docs`` / ``agents`` extras append to the matching base binding;
    the ``code`` kind adds a binding onto which ``test`` / ``log-check`` attach;
    generic bindings append their declared scope → action-id lists. ``{slug}`` is
    filled across every action.
    """
    actions = {action_id: _fill_slug(action, project_slug) for action_id, action in base.actions.items()}
    bindings: list[CheckpointBinding] = list(base.bindings)

    if overlay is not None:
        for action_id, action_cfg in (getattr(overlay, "actions", None) or {}).items():
            evidence = tuple(action_cfg.evidence) if action_cfg.evidence else (action_cfg.run,)
            actions[action_id] = _fill_slug(
                CheckpointAction(
                    id=action_id,
                    run=action_cfg.run,
                    evidence=evidence,
                    main_only=action_cfg.main_only,
                    precedence=action_cfg.precedence,
                    evidence_must_follow_last_mutation=action_cfg.evidence_must_follow_last_mutation,
                ),
                project_slug,
            )

        bindings = _append_conventional_extras(bindings, overlay)

        code_cfg = getattr(overlay, "code", None)
        if code_cfg is not None:
            code_scope = _scope_from_cfg(code_cfg.scope)
            if code_scope.include:
                bindings.append(CheckpointBinding(scope=code_scope, actions=("test", "log-check")))

        for binding_cfg in getattr(overlay, "bindings", None) or []:
            bindings.append(
                CheckpointBinding(scope=_scope_from_cfg(binding_cfg.scope), actions=tuple(binding_cfg.actions))
            )

    return CheckpointModel(actions=actions, bindings=tuple(bindings))


def _append_conventional_extras(bindings: list[CheckpointBinding], overlay: object) -> list[CheckpointBinding]:
    """Append optional ``docs`` / ``agents`` overlay extras onto their base bindings."""
    extras: dict[int, tuple[str, ...]] = {}
    docs_cfg = getattr(overlay, "docs", None)
    if docs_cfg is not None and docs_cfg.actions:
        extras[CHECKPOINT_BASE_DOCS_BINDING_INDEX] = tuple(docs_cfg.actions)
    agents_cfg = getattr(overlay, "agents", None)
    if agents_cfg is not None and agents_cfg.actions:
        extras[CHECKPOINT_BASE_AGENTS_BINDING_INDEX] = tuple(agents_cfg.actions)
    if not extras:
        return bindings
    return [
        CheckpointBinding(scope=binding.scope, actions=binding.actions + extras.get(index, ()))
        if index in extras
        else binding
        for index, binding in enumerate(bindings)
    ]


def load_checkpoint_model(project_path: str) -> CheckpointModel:
    """Load the effective checkpoint model for a project (base ⊕ overlay).

    Fail-open: an unreadable project config degrades to base-only with the slug
    derived from the directory name, never raising.
    """
    root = Path(project_path) if project_path else Path(".")
    fallback_slug = root.name or "project"
    try:
        config = load_project_config(root / "teleclaude.yml")
        project_slug = config.project_slug or fallback_slug
        return merge_overlay(base_checkpoint_model(project_slug), config.checkpoint, project_slug)
    except Exception:
        logger.warning(
            "Checkpoint overlay unreadable; falling back to base-only model",
            extra={"project_path": project_path or ""},
            exc_info=True,
        )
        return base_checkpoint_model(fallback_slug)

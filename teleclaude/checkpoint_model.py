"""Effective checkpoint model: base ⊕ overlay merge, the scope matcher, and resolution.

One matcher and one binding table serve every checkpoint and maintenance consumer:
the agent-stop engine surfaces judgment actions, while canonical-root maintenance
executes declared commands. Action selection is structured glob matching over the
merged declaration only; no consumer recreates path or capability policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import ALL_CAPABILITIES, Capabilities, capabilities_from_project_config
from teleclaude.config.loader import load_declared_project_config
from teleclaude.config.schema import ProjectConfig
from teleclaude.constants import (
    CHECKPOINT_BASE_ACTIONS,
    CHECKPOINT_BASE_AGENTS_BINDING,
    CHECKPOINT_BASE_CODE_BINDING,
    CHECKPOINT_BASE_DOCS_BINDING,
    CHECKPOINT_BASE_MAINTENANCE,
    CheckpointAction,
    CheckpointBinding,
    CheckpointModel,
    CheckpointScope,
    MaintenanceAction,
    _compile_glob,
)

logger = get_logger(__name__)

_DEFAULT_PROJECT_PATH = "."
_DEFAULT_PROJECT_SLUG = "project"
_PROJECT_SLUG_PLACEHOLDER = "{slug}"
_ACTIVATION_BEFORE_PLACEHOLDER = "{before_sha}"
_ACTIVATION_AFTER_PLACEHOLDER = "{after_sha}"
_ACTIVATION_BEFORE_FLAG = "--before-sha"
_EMPTY_COMMAND_ARGUMENT = ""
_MAINTENANCE_ACTIONS_RESOLVED_EVENT = "checkpoint_maintenance_actions_resolved"

__all__ = [
    "ActivationRange",
    "base_checkpoint_model",
    "checkpoint_model_from_project_config",
    "fill_activation_range",
    "load_checkpoint_model",
    "main_only_judgment_action_ids_for_files",
    "main_only_maintenance_action_ids_for_files",
    "merge_overlay",
    "scope_matches",
    "scopes_for_action",
    "triggered_action_ids",
]


@dataclass(frozen=True)
class ActivationRange:
    """Immutable Git object ids selected at a commit or merge ingress."""

    before_sha: str | None
    after_sha: str


def fill_activation_range(command: tuple[str, ...], activation_range: ActivationRange) -> tuple[str, ...]:
    """Substitute recorded ids, omitting the before flag for a root commit."""
    resolved: list[str] = []
    index = 0
    while index < len(command):
        argument = command[index]
        next_argument = command[index + 1] if index + 1 < len(command) else _EMPTY_COMMAND_ARGUMENT
        if argument == _ACTIVATION_BEFORE_FLAG and next_argument == _ACTIVATION_BEFORE_PLACEHOLDER:
            if activation_range.before_sha is not None:
                resolved.extend((_ACTIVATION_BEFORE_FLAG, activation_range.before_sha))
            index += 2
            continue
        if argument == _ACTIVATION_AFTER_PLACEHOLDER:
            resolved.append(activation_range.after_sha)
        else:
            resolved.append(argument)
        index += 1
    return tuple(resolved)


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


def main_only_maintenance_action_ids_for_files(files: list[str], project_root: Path) -> list[str]:
    """Return ordered main-only maintenance action ids owed by project files."""
    model = load_checkpoint_model(str(project_root))
    owed = triggered_action_ids(files, model)
    main_only = [
        action_id for action_id in owed if action_id in model.maintenance and model.maintenance[action_id].main_only
    ]
    ordered_main_only = sorted(main_only, key=lambda action_id: (model.maintenance[action_id].precedence, action_id))
    logger.info(
        _MAINTENANCE_ACTIONS_RESOLVED_EVENT,
        project_path=str(project_root),
        changed_file_set=sorted(files),
        triggered_action_ids=sorted(owed),
        main_only_action_ids=ordered_main_only,
    )
    return ordered_main_only


def main_only_judgment_action_ids_for_files(files: list[str], project_root: Path) -> list[str]:
    """Return ordered main-only judgment action ids owed by project files."""
    model = load_checkpoint_model(str(project_root))
    owed = triggered_action_ids(files, model)
    return sorted(
        (action_id for action_id in owed if action_id in model.actions and model.actions[action_id].main_only),
        key=lambda action_id: (model.actions[action_id].precedence, action_id),
    )


def scopes_for_action(model: CheckpointModel, action_id: str) -> list[CheckpointScope]:
    """Return the scopes of every binding that references the given action id."""
    return [binding.scope for binding in model.bindings if action_id in binding.actions]


def _fill_slug(action: CheckpointAction, project_slug: str) -> CheckpointAction:
    """Substitute the ``{slug}`` placeholder in the action's dynamic fields."""
    if _PROJECT_SLUG_PLACEHOLDER not in action.run and not any(
        _PROJECT_SLUG_PLACEHOLDER in marker for marker in action.evidence
    ):
        return action
    return CheckpointAction(
        id=action.id,
        run=action.run.replace(_PROJECT_SLUG_PLACEHOLDER, project_slug),
        evidence=tuple(marker.replace(_PROJECT_SLUG_PLACEHOLDER, project_slug) for marker in action.evidence),
        main_only=action.main_only,
        off_main_eligible=action.off_main_eligible,
        precedence=action.precedence,
        evidence_must_follow_last_mutation=action.evidence_must_follow_last_mutation,
    )


def _fill_maintenance_slug(action: MaintenanceAction, project_slug: str) -> MaintenanceAction:
    """Substitute the ``{slug}`` placeholder in maintenance command arguments."""
    if not any(_PROJECT_SLUG_PLACEHOLDER in argument for argument in action.command):
        return action
    return MaintenanceAction(
        id=action.id,
        command=tuple(argument.replace(_PROJECT_SLUG_PLACEHOLDER, project_slug) for argument in action.command),
        main_only=action.main_only,
        precedence=action.precedence,
    )


def base_checkpoint_model(project_slug: str, capabilities: Capabilities = ALL_CAPABILITIES) -> CheckpointModel:
    """The platform-universal base with ``{slug}`` filled, no overlay merged."""
    actions = {action_id: _fill_slug(action, project_slug) for action_id, action in CHECKPOINT_BASE_ACTIONS.items()}
    maintenance = {
        action_id: _fill_maintenance_slug(action, project_slug)
        for action_id, action in CHECKPOINT_BASE_MAINTENANCE.items()
    }
    enabled_bindings = (
        binding
        for binding, enabled in (
            (CHECKPOINT_BASE_DOCS_BINDING, capabilities.docs),
            (CHECKPOINT_BASE_AGENTS_BINDING, capabilities.agents),
            (CHECKPOINT_BASE_CODE_BINDING, capabilities.code),
        )
        if enabled
    )
    return CheckpointModel(actions=actions, maintenance=maintenance, bindings=tuple(enabled_bindings))


def _scope_from_cfg(scope_cfg: object) -> CheckpointScope:
    """Build a frozen scope from a Pydantic ``CheckpointScopeConfig``."""
    return CheckpointScope(
        include=tuple(getattr(scope_cfg, "include", []) or []),
        exclude=tuple(getattr(scope_cfg, "exclude", []) or []),
        override=tuple(getattr(scope_cfg, "override", []) or []),
    )


def merge_overlay(
    base: CheckpointModel,
    overlay: object | None,
    project_slug: str,
    capabilities: Capabilities = ALL_CAPABILITIES,
) -> CheckpointModel:
    """Merge a project-declared overlay (``CheckpointConfig``) atop the base model.

    Registries: overlay actions extend or override their matching base registry by
    id. Bindings: the
    conventional ``docs`` / ``agents`` extras append to the matching base binding;
    the ``code`` kind adds a binding onto which ``test`` / ``log-check`` attach;
    generic bindings append their declared scope → action-id lists. ``{slug}`` is
    filled across every action.
    """
    actions = {action_id: _fill_slug(action, project_slug) for action_id, action in base.actions.items()}
    maintenance = {
        action_id: _fill_maintenance_slug(action, project_slug) for action_id, action in base.maintenance.items()
    }
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

        for action_id, action_cfg in (getattr(overlay, "maintenance", None) or {}).items():
            maintenance[action_id] = _fill_maintenance_slug(
                MaintenanceAction(
                    id=action_id,
                    command=tuple(action_cfg.command),
                    main_only=action_cfg.main_only,
                    precedence=action_cfg.precedence,
                ),
                project_slug,
            )

        bindings = _append_conventional_extras(bindings, overlay)

        code_cfg = getattr(overlay, "code", None)
        if capabilities.code and code_cfg is not None:
            code_scope = _scope_from_cfg(code_cfg.scope)
            if code_scope.include:
                bindings.append(CheckpointBinding(scope=code_scope, actions=("test", "log-check")))

        for binding_cfg in getattr(overlay, "bindings", None) or []:
            bindings.append(
                CheckpointBinding(scope=_scope_from_cfg(binding_cfg.scope), actions=tuple(binding_cfg.actions))
            )

    return CheckpointModel(actions=actions, maintenance=maintenance, bindings=tuple(bindings))


def _append_conventional_extras(bindings: list[CheckpointBinding], overlay: object) -> list[CheckpointBinding]:
    """Append optional ``docs`` / ``agents`` overlay extras onto their base bindings."""
    extras: dict[CheckpointBinding, tuple[str, ...]] = {}
    docs_cfg = getattr(overlay, "docs", None)
    if docs_cfg is not None and docs_cfg.actions:
        extras[CHECKPOINT_BASE_DOCS_BINDING] = tuple(docs_cfg.actions)
    agents_cfg = getattr(overlay, "agents", None)
    if agents_cfg is not None and agents_cfg.actions:
        extras[CHECKPOINT_BASE_AGENTS_BINDING] = tuple(agents_cfg.actions)
    if not extras:
        return bindings
    return [
        CheckpointBinding(scope=binding.scope, actions=binding.actions + extras.get(binding, ()))
        if binding in extras
        else binding
        for binding in bindings
    ]


def load_checkpoint_model(project_path: str) -> CheckpointModel:
    """Load the effective checkpoint model for a project (base ⊕ overlay).

    A root that declares no project (person, company, global home, or no
    declaration at all) has no project overlay to merge and returns the base
    model directly. Fail-open applies only to a genuinely unreadable or
    malformed declaration, which degrades to base-only with the slug derived
    from the directory name, never raising.
    """
    root = Path(project_path) if project_path else Path(_DEFAULT_PROJECT_PATH)
    fallback_slug = root.name or _DEFAULT_PROJECT_SLUG
    try:
        config = load_declared_project_config(root)
    except Exception:
        logger.warning(
            "Checkpoint overlay unreadable; falling back to base-only model",
            extra={"project_path": project_path or ""},
            exc_info=True,
        )
        return base_checkpoint_model(fallback_slug)
    if config is None:
        return base_checkpoint_model(fallback_slug)
    return checkpoint_model_from_project_config(project_path, config, capabilities_from_project_config(config))


def checkpoint_model_from_project_config(
    project_path: str,
    config: ProjectConfig | None,
    capabilities: Capabilities,
) -> CheckpointModel:
    """Build the effective model from an overlay already resolved by the caller."""
    root = Path(project_path) if project_path else Path(_DEFAULT_PROJECT_PATH)
    fallback_slug = root.name or _DEFAULT_PROJECT_SLUG
    if config is None:
        return base_checkpoint_model(fallback_slug, capabilities)
    project_slug = config.project_slug or fallback_slug
    return merge_overlay(
        base_checkpoint_model(project_slug, capabilities),
        config.checkpoint,
        project_slug,
        capabilities,
    )

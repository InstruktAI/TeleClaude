"""Effective checkpoint model: base ⊕ overlay merge, the scope matcher, and resolution.

One matcher and one binding table serve every checkpoint and maintenance consumer:
the agent-stop engine surfaces judgment actions, while canonical-root maintenance
executes declared commands. Action selection is structured glob matching over the
merged declaration only; no consumer recreates path or capability policy.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.capabilities import (
    ALL_CAPABILITIES,
    NOT_A_TARGET,
    Capabilities,
    capabilities_from_project_config,
    resolve_capabilities,
)
from teleclaude.config.loader import load_declared_project_config, load_declared_project_config_from_content
from teleclaude.config.schema import ProjectConfig
from teleclaude.constants import (
    BLUEPRINT_MAINTENANCE_ACTION_ID,
    CHECKPOINT_BASE_ACTIONS,
    CHECKPOINT_BASE_AGENTS_BINDING,
    CHECKPOINT_BASE_BLUEPRINT_ACTIVATION_BINDING,
    CHECKPOINT_BASE_CODE_BINDING,
    CHECKPOINT_BASE_DOCS_BINDING,
    CHECKPOINT_BASE_MAINTENANCE,
    CHECKPOINT_HOME_DECLARATION_BINDING,
    CHECKPOINT_HOME_PUBLICATION_BINDING,
    CHECKPOINT_PROJECT_DESK_BINDING,
    LOG_CHECK_ACTION_ID,
    CheckpointAction,
    CheckpointActivation,
    CheckpointActivationBinding,
    CheckpointBinding,
    CheckpointEventBinding,
    CheckpointModel,
    CheckpointScope,
    JudgmentOwner,
    MaintenanceAction,
    _compile_glob,
)
from teleclaude.events.type_pattern import TypePattern
from teleclaude.git import GitCommandError
from teleclaude.git_tree import TreeSource, read_tree_path
from teleclaude.paths import ConfigFileName, is_platform_home

logger = get_logger(__name__)

_DEFAULT_PROJECT_PATH = "."
_DEFAULT_PROJECT_SLUG = "project"
_PROJECT_SLUG_PLACEHOLDER = "{slug}"
_ACTIVATION_BEFORE_PLACEHOLDER = "{before_sha}"
_ACTIVATION_AFTER_PLACEHOLDER = "{after_sha}"
_HOME_PLACEHOLDER = "{home}"
_INTERPRETER_PLACEHOLDER = "{interpreter}"
_EVENT_FILE_PLACEHOLDER = "{event_file}"
_EVENT_TYPE_PLACEHOLDER = "{event_type}"
_EVENT_ID_PLACEHOLDER = "{event_id}"
_FLAG_PREFIX = "--"
_MAINTENANCE_ACTIONS_RESOLVED_EVENT = "checkpoint_maintenance_actions_resolved"
_COMMITTED_DECLARATION_UNREADABLE_EVENT = "checkpoint_committed_declaration_unreadable"

__all__ = [
    "ActivationRange",
    "activation_action_ids",
    "base_checkpoint_model",
    "checkpoint_model_from_project_config",
    "event_only_action_ids",
    "fill_activation_range",
    "fill_event_activation",
    "fill_on_demand",
    "load_checkpoint_model",
    "load_committed_checkpoint_model",
    "main_only_judgment_action_ids_for_files",
    "main_only_maintenance_action_ids_for_files",
    "main_only_maintenance_action_ids_for_files_and_activation",
    "main_only_maintenance_action_ids_for_model",
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


def _fill_placeholders(command: tuple[str, ...], values: Mapping[str, str | None]) -> tuple[str, ...]:
    """Substitute each placeholder the command names from ``values``.

    A placeholder whose value is ``None`` is omitted together with the flag directly before
    it, so a command declares ``--before-sha {before_sha}`` once and a run that has no such
    value passes neither. A placeholder not in ``values`` is left as written.
    """
    resolved: list[str] = []
    for argument in command:
        if argument not in values:
            resolved.append(argument)
            continue
        value = values[argument]
        if value is not None:
            resolved.append(value)
        elif resolved and resolved[-1].startswith(_FLAG_PREFIX):
            resolved.pop()
    return tuple(resolved)


def fill_activation_range(
    command: tuple[str, ...],
    activation_range: ActivationRange,
    *,
    interpreter: str | None = None,
    home: str | None = None,
) -> tuple[str, ...]:
    """Substitute the interpreter and recorded ids.

    A root commit omits the ``--before-sha`` pair. The ``--home`` pair appears only
    when a ``home`` is given, so a commit-boundary activation, which has none, omits it.
    """
    return _fill_placeholders(
        command,
        {
            _INTERPRETER_PLACEHOLDER: interpreter or sys.executable,
            _ACTIVATION_BEFORE_PLACEHOLDER: activation_range.before_sha,
            _ACTIVATION_AFTER_PLACEHOLDER: activation_range.after_sha,
            _HOME_PLACEHOLDER: home,
        },
    )


def fill_event_activation(
    command: tuple[str, ...],
    *,
    event_file: str,
    event_type: str,
    event_id: str,
    interpreter: str | None = None,
) -> tuple[str, ...]:
    """Substitute the interpreter and the event an activation answers.

    The event itself reaches a command only as the path of the file that holds it. An event
    activation has no commit range and no home, so each range placeholder is omitted
    together with the flag before it.
    """
    return _fill_placeholders(
        command,
        {
            _INTERPRETER_PLACEHOLDER: interpreter or sys.executable,
            _EVENT_FILE_PLACEHOLDER: event_file,
            _EVENT_TYPE_PLACEHOLDER: event_type,
            _EVENT_ID_PLACEHOLDER: event_id,
            _ACTIVATION_BEFORE_PLACEHOLDER: None,
            _ACTIVATION_AFTER_PLACEHOLDER: None,
            _HOME_PLACEHOLDER: None,
        },
    )


def fill_on_demand(command: tuple[str, ...], tip: str, home: str, *, interpreter: str | None = None) -> tuple[str, ...]:
    """Fill a command for an on-demand run, which has a tip and an invocation home but no range."""
    return fill_activation_range(
        command, ActivationRange(before_sha=None, after_sha=tip), interpreter=interpreter, home=home
    )


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


def event_only_action_ids(model: CheckpointModel) -> frozenset[str]:
    """Return the action ids that an event binding names and no path binding names.

    Such an action reacts to an event, so a run with no event has nothing for it to act on.
    """
    path_bound = {action_id for binding in model.bindings for action_id in binding.actions}
    activation_bound = {action_id for binding in model.activation_bindings for action_id in binding.actions}
    event_bound = {action_id for binding in model.event_bindings for action_id in binding.actions}
    return frozenset(event_bound - path_bound - activation_bound)


def activation_action_ids(model: CheckpointModel, activation: CheckpointActivation) -> frozenset[str]:
    """Return the action ids selected by one activation binding."""
    return frozenset(
        action_id
        for binding in model.activation_bindings
        if binding.activation is activation
        for action_id in binding.actions
    )


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


def main_only_maintenance_action_ids_for_files_and_activation(
    files: list[str], activation: CheckpointActivation, project_root: Path
) -> list[str]:
    """Return ordered main-only maintenance ids selected by paths or activation."""
    return main_only_maintenance_action_ids_for_model(files, activation, load_checkpoint_model(str(project_root)))


def main_only_maintenance_action_ids_for_model(
    files: list[str], activation: CheckpointActivation, model: CheckpointModel
) -> list[str]:
    """Return ordered main-only maintenance ids one already-resolved declaration selects by paths or activation."""
    selected = triggered_action_ids(files, model) | activation_action_ids(model, activation)
    return sorted(
        (
            action_id
            for action_id in selected
            if action_id in model.maintenance and model.maintenance[action_id].main_only
        ),
        key=lambda action_id: (model.maintenance[action_id].precedence, action_id),
    )


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
        judged_by=action.judged_by,
    )


def _fill_maintenance_slug(action: MaintenanceAction, project_slug: str) -> MaintenanceAction:
    """Substitute the ``{slug}`` placeholder in maintenance command and probe arguments."""
    probe = action.owed_probe or ()
    if not any(_PROJECT_SLUG_PLACEHOLDER in argument for argument in (*action.command, *probe)):
        return action
    return replace(
        action,
        command=tuple(argument.replace(_PROJECT_SLUG_PLACEHOLDER, project_slug) for argument in action.command),
        owed_probe=(
            tuple(argument.replace(_PROJECT_SLUG_PLACEHOLDER, project_slug) for argument in probe)
            if action.owed_probe is not None
            else None
        ),
    )


def base_checkpoint_model(
    project_slug: str,
    capabilities: Capabilities = ALL_CAPABILITIES,
    *,
    help_desk: bool = False,
) -> CheckpointModel:
    """The platform-universal base with ``{slug}`` filled, no overlay merged.

    A project whose declaration enables a help desk also binds its declaration to
    convergence and the publication that follows it.
    """
    actions = {action_id: _fill_slug(action, project_slug) for action_id, action in CHECKPOINT_BASE_ACTIONS.items()}
    maintenance = {
        action_id: _fill_maintenance_slug(action, project_slug)
        for action_id, action in CHECKPOINT_BASE_MAINTENANCE.items()
        if action_id != BLUEPRINT_MAINTENANCE_ACTION_ID or capabilities.code
    }
    enabled_bindings = (
        binding
        for binding, enabled in (
            (CHECKPOINT_BASE_DOCS_BINDING, capabilities.docs),
            (CHECKPOINT_BASE_AGENTS_BINDING, capabilities.agents),
            (CHECKPOINT_BASE_CODE_BINDING, capabilities.code),
            (CHECKPOINT_PROJECT_DESK_BINDING, help_desk),
        )
        if enabled
    )
    activation_bindings = (CHECKPOINT_BASE_BLUEPRINT_ACTIVATION_BINDING,) if capabilities.code else ()
    return CheckpointModel(
        actions=actions,
        maintenance=maintenance,
        bindings=tuple(enabled_bindings),
        activation_bindings=activation_bindings,
    )


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
    generic bindings append their declared scope → action-id lists, and a binding
    that names ``events`` joins the event bindings instead, so every reader of
    ``bindings`` sees path bindings only. ``{slug}`` is filled across every action.
    """
    actions = {action_id: _fill_slug(action, project_slug) for action_id, action in base.actions.items()}
    maintenance = {
        action_id: _fill_maintenance_slug(action, project_slug) for action_id, action in base.maintenance.items()
    }
    bindings: list[CheckpointBinding] = list(base.bindings)
    event_bindings: list[CheckpointEventBinding] = list(base.event_bindings)
    activation_bindings: list[CheckpointActivationBinding] = list(base.activation_bindings)

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
                    on_demand=action_cfg.on_demand,
                    owed_probe=tuple(action_cfg.owed_probe) if action_cfg.owed_probe is not None else None,
                ),
                project_slug,
            )

        bindings = _append_conventional_extras(bindings, overlay)

        for action_id in getattr(overlay, "integrator_judgment", None) or []:
            actions[action_id] = replace(actions[action_id], judged_by=JudgmentOwner.INTEGRATOR)

        code_cfg = getattr(overlay, "code", None)
        if capabilities.code and code_cfg is not None:
            code_scope = _scope_from_cfg(code_cfg.scope)
            if code_scope.include:
                bindings.append(CheckpointBinding(scope=code_scope, actions=("test", LOG_CHECK_ACTION_ID)))

        for binding_cfg in getattr(overlay, "bindings", None) or []:
            if binding_cfg.activation is not None:
                activation_bindings.append(
                    CheckpointActivationBinding(
                        activation=binding_cfg.activation,
                        actions=tuple(binding_cfg.actions),
                    )
                )
            elif binding_cfg.events is not None:
                event_bindings.append(
                    CheckpointEventBinding(
                        patterns=tuple(TypePattern(text) for text in binding_cfg.events),
                        actions=tuple(binding_cfg.actions),
                    )
                )
            else:
                bindings.append(
                    CheckpointBinding(scope=_scope_from_cfg(binding_cfg.scope), actions=tuple(binding_cfg.actions))
                )

    if not capabilities.code:
        maintenance.pop(BLUEPRINT_MAINTENANCE_ACTION_ID, None)
        bindings = [
            CheckpointBinding(binding.scope, retained_actions)
            for binding in bindings
            if (
                retained_actions := tuple(
                    action for action in binding.actions if action != BLUEPRINT_MAINTENANCE_ACTION_ID
                )
            )
        ]
        event_bindings = [
            CheckpointEventBinding(binding.patterns, retained_actions)
            for binding in event_bindings
            if (
                retained_actions := tuple(
                    action for action in binding.actions if action != BLUEPRINT_MAINTENANCE_ACTION_ID
                )
            )
        ]
        activation_bindings = [
            CheckpointActivationBinding(binding.activation, retained_actions)
            for binding in activation_bindings
            if (
                retained_actions := tuple(
                    action for action in binding.actions if action != BLUEPRINT_MAINTENANCE_ACTION_ID
                )
            )
        ]

    return CheckpointModel(
        actions=actions,
        maintenance=maintenance,
        bindings=tuple(bindings),
        event_bindings=tuple(event_bindings),
        activation_bindings=tuple(activation_bindings),
    )


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
    from the directory name. Filesystem errors while resolving the root remain
    visible because the home-specific maintenance binding depends on that result.
    """
    root = Path(project_path) if project_path else Path(_DEFAULT_PROJECT_PATH)
    try:
        config = load_declared_project_config(root)
    except Exception:
        logger.warning(
            "Checkpoint overlay unreadable; falling back to base-only model",
            extra={"project_path": project_path or ""},
            exc_info=True,
        )
        config = None
    capabilities_if_missing = resolve_capabilities(root) if config is None else NOT_A_TARGET
    return _model_for_declaration(root, project_path, config, capabilities_if_missing)


def load_committed_checkpoint_model(repository_root: Path, tip: str) -> CheckpointModel:
    """Load the effective model from the root's declaration as committed at ``tip``.

    The step set an on-demand run performs comes from what is committed, so an
    uncommitted edit to the overlay cannot add or reorder steps. A root whose
    declaration is absent from the tip, or unreadable there, degrades to the
    base-only model, the same posture ``load_checkpoint_model`` takes.
    """
    root = repository_root.resolve()
    marker = root / ConfigFileName.OVERLAY
    try:
        content = read_tree_path(TreeSource.recorded_commit(root, tip), ConfigFileName.OVERLAY.value)
        config = load_declared_project_config_from_content(marker, content)
    except (GitCommandError, ValueError):
        logger.warning(
            _COMMITTED_DECLARATION_UNREADABLE_EVENT,
            project_path=str(root),
            tip=tip,
            exc_info=True,
        )
        config = None
    return _model_for_declaration(root, str(root), config, NOT_A_TARGET)


def _model_for_declaration(
    root: Path,
    project_path: str,
    config: ProjectConfig | None,
    capabilities_if_missing: Capabilities,
) -> CheckpointModel:
    """Build the effective model for a root from its resolved declaration, if any."""
    if config is None:
        model = base_checkpoint_model(root.name or _DEFAULT_PROJECT_SLUG, capabilities_if_missing)
    else:
        model = checkpoint_model_from_project_config(project_path, config, capabilities_from_project_config(config))
    if is_platform_home(root):
        model = _append_home_publication_binding(model)
    return model


def _append_home_publication_binding(model: CheckpointModel) -> CheckpointModel:
    """Attach the platform-home triggers (tier docs publication, declaration convergence) once each."""
    attached = tuple(
        binding
        for binding in (CHECKPOINT_HOME_PUBLICATION_BINDING, CHECKPOINT_HOME_DECLARATION_BINDING)
        if binding not in model.bindings
    )
    if not attached:
        return model
    return CheckpointModel(
        actions=model.actions,
        maintenance=model.maintenance,
        bindings=(*model.bindings, *attached),
        event_bindings=model.event_bindings,
        activation_bindings=model.activation_bindings,
    )


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
        base_checkpoint_model(project_slug, capabilities, help_desk=config.help_desk.enabled),
        config.checkpoint,
        project_slug,
        capabilities,
    )

"""Project checkpoint overlay models: declared actions, maintenance, bindings and their cross-references."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from teleclaude.closed_model import ClosedModel
from teleclaude.constants import (
    CHECKPOINT_BASE_ACTIONS,
    CHECKPOINT_BASE_MAINTENANCE,
    CheckpointActivation,
    OnDemandDisposition,
)
from teleclaude.events.type_pattern import TypePattern

_PROBE_REQUIRES_DEFER_ERROR = "owed_probe belongs only to an action whose on_demand is defer"
_EVENT_BINDING_SCOPE_ERROR = "a binding names one trigger kind: events or scope, never both"
_EVENT_BINDING_EMPTY_ERROR = "a binding that names events must name at least one event type pattern"
_EVENT_BINDING_JUDGMENT_ACTION_ERROR = (
    "checkpoint.bindings[{index}] binds events to {actions}; only maintenance actions may be bound to events, "
    "because an event has no agent to surface a judgment action to"
)
_EVENT_BINDING_SCOPE_FIELD = "scope"
_ACTION_LIST_SEPARATOR = ", "
_ACTIVATION_TRIGGER_KIND_ERROR = "a binding names one trigger kind: activation, events, or scope"
_ACTIVATION_MAIN_ONLY_ACTION_ERROR_TEMPLATE = "activation binding {index} requires main-only maintenance: {actions}"


class CheckpointActionConfig(ClosedModel):
    """A project-declared checkpoint action (verb) overlaid on the base registry."""

    run: str = Field(min_length=1)
    evidence: list[str] = []
    main_only: bool = False
    precedence: int = 0
    evidence_must_follow_last_mutation: bool = False


class CheckpointMaintenanceConfig(ClosedModel):
    """A project-declared deterministic action overlaid on the maintenance registry."""

    command: list[str] = Field(min_length=1)
    main_only: bool = False
    precedence: int = 0
    on_demand: OnDemandDisposition = OnDemandDisposition.RUN
    owed_probe: list[str] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_probe_belongs_to_deferred_action(self) -> CheckpointMaintenanceConfig:
        """An owed probe answers whether a deferred action is owed; a performed action has none."""
        if self.owed_probe is not None and self.on_demand is not OnDemandDisposition.DEFER:
            raise ValueError(_PROBE_REQUIRES_DEFER_ERROR)
        return self


class CheckpointScopeConfig(ClosedModel):
    """A glob scope: ``include`` minus ``exclude``, re-added by ``override``."""

    include: list[str] = []
    exclude: list[str] = []
    override: list[str] = []


class CheckpointBindingConfig(ClosedModel):
    """Maps exactly one path, event, or canonical-main trigger to action ids."""

    scope: CheckpointScopeConfig = CheckpointScopeConfig()
    events: list[str] | None = None
    activation: CheckpointActivation | None = None
    actions: list[str] = []

    @field_validator("events")
    @classmethod
    def parse_event_patterns(cls, value: list[str] | None) -> list[str] | None:
        """Refuse an empty list and any entry that is not a well-formed event type pattern."""
        if value is None:
            return value
        if not value:
            raise ValueError(_EVENT_BINDING_EMPTY_ERROR)
        for pattern in value:
            TypePattern(pattern)
        return value

    @model_validator(mode="after")
    def validate_single_trigger_kind(self) -> CheckpointBindingConfig:
        """A binding names exactly one of paths, events, or canonical-main activation."""
        has_scope = _EVENT_BINDING_SCOPE_FIELD in self.model_fields_set
        if self.activation is not None and (self.events is not None or has_scope):
            raise ValueError(_ACTIVATION_TRIGGER_KIND_ERROR)
        if self.events is not None and has_scope:
            raise ValueError(_EVENT_BINDING_SCOPE_ERROR)
        return self


class CheckpointCodeConfig(ClosedModel):
    """The conventional ``code`` kind: a scope onto which base ``test`` / ``log-check`` attach."""

    scope: CheckpointScopeConfig = CheckpointScopeConfig()


class CheckpointExtraActionsConfig(ClosedModel):
    """Optional extra actions appended atop a conventional base binding (``docs`` / ``agents``)."""

    actions: list[str] = []


class CheckpointConfig(ClosedModel):
    """Project checkpoint maintenance overlay merged atop the platform-universal base.

    Authored at analyze-time by intelligence (``telec sessions run --command
    /projects-analyze``) per ``local/projects/teleclaude/procedure/checkpoint-overlay-projection``;
    consumed structurally by
    the checkpoint engine. An unreadable overlay degrades to base-only (fail-open).
    """

    actions: dict[str, CheckpointActionConfig] = {}
    maintenance: dict[str, CheckpointMaintenanceConfig] = {}
    integrator_judgment: list[str] = []
    code: CheckpointCodeConfig | None = None
    bindings: list[CheckpointBindingConfig] = []
    docs: CheckpointExtraActionsConfig | None = None
    agents: CheckpointExtraActionsConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_action_key_placement(cls, data: Any) -> Any:
        """Give a misplaced action/maintenance key registry-specific guidance.

        A closed ``CheckpointActionConfig``/``CheckpointMaintenanceConfig`` rejects an
        unknown key during its own field validation, which runs before this model's
        after-validator, so the targeted message must come from the raw mapping here
        instead of from the parsed fields.
        """
        if not isinstance(data, dict):
            return data
        for action_id, action in (data.get("actions") or {}).items():
            if isinstance(action, dict) and "command" in action:
                raise ValueError(f"checkpoint.actions.{action_id}.command belongs under checkpoint.maintenance")
        for maintenance_id, maintenance_action in (data.get("maintenance") or {}).items():
            if isinstance(maintenance_action, dict) and (
                "run" in maintenance_action or "evidence" in maintenance_action
            ):
                raise ValueError(f"checkpoint.maintenance.{maintenance_id} may not declare run or evidence")
        return data

    @model_validator(mode="after")
    def validate_action_references(self) -> CheckpointConfig:
        """Every referenced action id must resolve to the base registry or a declared action.

        The runtime silently drops unknown action ids (``run_heuristics`` filters to
        the merged registry), so an unresolved reference would validate while the
        declared maintenance never surfaces. Reject it at the boundary instead, and
        reject a binding/extra block that references no action at all.
        """
        action_ids = set(CHECKPOINT_BASE_ACTIONS) | set(self.actions)
        maintenance_ids = set(CHECKPOINT_BASE_MAINTENANCE) | set(self.maintenance)
        duplicate_ids = action_ids & maintenance_ids
        if duplicate_ids:
            raise ValueError(
                "checkpoint action ids must belong to exactly one registry; "
                f"declared in both actions and maintenance: {', '.join(sorted(duplicate_ids))}"
            )
        valid_ids = action_ids | maintenance_ids
        main_only_action_ids = {action_id for action_id, action in CHECKPOINT_BASE_ACTIONS.items() if action.main_only}
        main_only_action_ids.difference_update(self.actions)
        main_only_action_ids.update(action_id for action_id, action in self.actions.items() if action.main_only)
        invalid_integrator_ids = [
            action_id for action_id in self.integrator_judgment if action_id not in main_only_action_ids
        ]
        if invalid_integrator_ids:
            raise ValueError(
                "checkpoint.integrator_judgment references unknown or non-main-only checkpoint action id(s): "
                f"{', '.join(invalid_integrator_ids)}"
            )

        def _check(action_ids: list[str], where: str) -> None:
            if not action_ids:
                raise ValueError(f"checkpoint.{where} declares no actions")
            unknown = [action_id for action_id in action_ids if action_id not in valid_ids]
            if unknown:
                raise ValueError(
                    f"checkpoint.{where} references unknown action id(s): {', '.join(unknown)}; "
                    f"declare them under checkpoint.actions or checkpoint.maintenance, or reference a base action "
                    f"({', '.join(sorted(valid_ids))})"
                )

        for index, binding in enumerate(self.bindings):
            _check(binding.actions, f"bindings[{index}].actions")
            if binding.events is not None:
                judgment = [action_id for action_id in binding.actions if action_id not in maintenance_ids]
                if judgment:
                    raise ValueError(
                        _EVENT_BINDING_JUDGMENT_ACTION_ERROR.format(
                            index=index, actions=_ACTION_LIST_SEPARATOR.join(judgment)
                        )
                    )
            if binding.activation is not None:
                non_maintenance = [action_id for action_id in binding.actions if action_id not in maintenance_ids]
                if non_maintenance:
                    raise ValueError(
                        _ACTIVATION_MAIN_ONLY_ACTION_ERROR_TEMPLATE.format(
                            index=index, actions=_ACTION_LIST_SEPARATOR.join(non_maintenance)
                        )
                    )
                main_only_maintenance_ids = {
                    action_id for action_id, action in CHECKPOINT_BASE_MAINTENANCE.items() if action.main_only
                }
                for action_id, action in self.maintenance.items():
                    if action.main_only:
                        main_only_maintenance_ids.add(action_id)
                    else:
                        main_only_maintenance_ids.discard(action_id)
                not_main_only = [
                    action_id for action_id in binding.actions if action_id not in main_only_maintenance_ids
                ]
                if not_main_only:
                    raise ValueError(
                        _ACTIVATION_MAIN_ONLY_ACTION_ERROR_TEMPLATE.format(
                            index=index, actions=_ACTION_LIST_SEPARATOR.join(not_main_only)
                        )
                    )
        if self.docs is not None:
            _check(self.docs.actions, "docs.actions")
        if self.agents is not None:
            _check(self.agents.actions, "agents.actions")
        return self

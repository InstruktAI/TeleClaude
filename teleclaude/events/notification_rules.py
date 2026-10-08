"""Notification rules — how the notification projector turns an event type into incident rows.

These rules are notification behavior, owned by the integration context's
outbound notifications. They live beside the projector that reads them and never
in an event's declaration (an event states facts only). Each rule is keyed by
the current type name; a type with no rule is signal-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, model_validator


class LifecycleFamily(StrEnum):
    """Closed incident families for lifecycle rows that share a group value."""

    AGENT_RESTART = "agent_restart"
    AGENT_SESSION_LIFECYCLE = "agent_session_lifecycle"
    BRANCH_PUSHED = "branch_pushed"
    BUILD = "build"
    CONFIG_SYNC = "config_sync"
    CONTENT_LIFECYCLE = "content_lifecycle"
    DEPLOY_ATTEMPT = "deploy_attempt"
    DEPLOYMENT_LIFECYCLE = "deployment_lifecycle"
    DEPLOYMENT_OUTCOME = "deployment_outcome"
    ENTITY_DEGRADATION = "entity_degradation"
    JOB_RUN = "job_run"
    NOTIFICATION_ESCALATION = "notification_escalation"
    PLANNING_READINESS = "planning_readiness"
    PREPARE_PIPELINE = "prepare_pipeline"
    REVIEW = "review"
    REVIEW_GATE_APPROVED = "review_gate_approved"
    TODO_LIFECYCLE = "todo_lifecycle"


class NotificationLifecycle(BaseModel):
    """Notification projection semantics for an event type."""

    creates: bool = False
    updates: bool = False
    resolves: bool = False
    group_key: str | None = None
    family: LifecycleFamily | None = None
    meaningful_fields: list[str] = []
    silent_fields: list[str] = []

    @model_validator(mode="after")
    def _validate_group_family(self) -> NotificationLifecycle:
        """Reject a grouped lifecycle whose incident family is implicit."""
        if self.group_key and self.family is None:
            raise ValueError("NotificationLifecycle group_key requires family")
        return self


@dataclass(frozen=True)
class NotificationRule:
    """The projector's reading of one event type: lifecycle, actionability and debounce window."""

    lifecycle: NotificationLifecycle | None = None
    actionable: bool = False
    # Per-event delivery-debounce override: None inherits the platform default,
    # a positive value sets the window, <= 0 delivers immediately.
    delivery_debounce_s: float | None = None


NOTIFICATION_RULES: dict[str, NotificationRule] = {
    "teleclaude.agent_runtime.session.restart_failed": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            updates=True,
            group_key="restart_group",
            family=LifecycleFamily.AGENT_RESTART,
            meaningful_fields=["reason", "phase"],
        ),
        actionable=True,
    ),
    "teleclaude.agent_runtime.session.ended": NotificationRule(
        lifecycle=NotificationLifecycle(
            resolves=True,
            group_key="session_id",
            family=LifecycleFamily.AGENT_SESSION_LIFECYCLE,
            meaningful_fields=["session_id", "project_path"],
        )
    ),
    "teleclaude.config.effective.updated": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True,
            group_key="project_path",
            family=LifecycleFamily.CONFIG_SYNC,
            meaningful_fields=["project_path"],
        )
    ),
    "teleclaude.content.dumped": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["content_id"])
    ),
    "teleclaude.content.published": NotificationRule(
        lifecycle=NotificationLifecycle(resolves=True, group_key="content_id", family=LifecycleFamily.CONTENT_LIFECYCLE)
    ),
    "teleclaude.content.refined": NotificationRule(
        lifecycle=NotificationLifecycle(updates=True, group_key="content_id", family=LifecycleFamily.CONTENT_LIFECYCLE)
    ),
    "teleclaude.deployment.succeeded": NotificationRule(
        lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.DEPLOYMENT_OUTCOME)
    ),
    "teleclaude.deployment.failed": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "reason"]), actionable=True
    ),
    "teleclaude.deployment.rolled_back": NotificationRule(
        lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.DEPLOYMENT_OUTCOME)
    ),
    "teleclaude.deployment.started": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"])
    ),
    "sdlc.branch.pushed": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True, group_key="branch", family=LifecycleFamily.BRANCH_PUSHED, meaningful_fields=["pushed_at"]
        )
    ),
    "sdlc.build.completed": NotificationRule(
        lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.BUILD)
    ),
    "sdlc.deploy.failed": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.DEPLOY_ATTEMPT, meaningful_fields=["error"]
        ),
        actionable=True,
    ),
    "sdlc.deploy.succeeded": NotificationRule(
        lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.DEPLOY_ATTEMPT)
    ),
    "sdlc.deploy.triggered": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug", "environment"])
    ),
    "sdlc.deployment.completed": NotificationRule(
        lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.DEPLOYMENT_LIFECYCLE)
    ),
    "sdlc.deployment.failed": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True,
            group_key="slug",
            family=LifecycleFamily.DEPLOYMENT_LIFECYCLE,
            meaningful_fields=["blocked_at"],
        ),
        actionable=True,
    ),
    "sdlc.deployment.started": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True, group_key="slug", family=LifecycleFamily.DEPLOYMENT_LIFECYCLE, meaningful_fields=["ready_at"]
        )
    ),
    "sdlc.planning.dor_assessed": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            updates=True,
            group_key="slug",
            family=LifecycleFamily.PLANNING_READINESS,
            meaningful_fields=["score", "verdict"],
        ),
        actionable=True,
    ),
    "sdlc.planning.todo_finalize_ready": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            group_key="slug",
            family=LifecycleFamily.PLANNING_READINESS,
            meaningful_fields=["slug", "branch", "sha", "worker_session_id", "ready_at"],
        )
    ),
    "sdlc.prepare.artifact_invalidated": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True,
            group_key="slug",
            family=LifecycleFamily.PREPARE_PIPELINE,
            meaningful_fields=["stale_artifacts"],
        ),
        actionable=True,
    ),
    "sdlc.prepare.artifact_produced": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True,
            group_key="slug",
            family=LifecycleFamily.PREPARE_PIPELINE,
            meaningful_fields=["artifact", "digest"],
        )
    ),
    "sdlc.prepare.blocked": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["blocker"]
        ),
        actionable=True,
    ),
    "sdlc.prepare.completed": NotificationRule(
        lifecycle=NotificationLifecycle(resolves=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE)
    ),
    "sdlc.prepare.discovery_started": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["slug"])
    ),
    "sdlc.prepare.input_consumed": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.prepare.input_refined": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.prepare.phase_skipped": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True,
            group_key="slug",
            family=LifecycleFamily.PREPARE_PIPELINE,
            meaningful_fields=["phase", "reason"],
        )
    ),
    "sdlc.prepare.plan_approved": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.prepare.plan_drafted": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.prepare.requirements_approved": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.prepare.requirements_drafted": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.PREPARE_PIPELINE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.prepare.review_scoped": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True,
            group_key="slug",
            family=LifecycleFamily.PREPARE_PIPELINE,
            meaningful_fields=["findings_artifact"],
        )
    ),
    "sdlc.review.approved": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            group_key="slug",
            family=LifecycleFamily.REVIEW_GATE_APPROVED,
            meaningful_fields=["approved_at"],
        )
    ),
    "sdlc.review.needs_decision": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.REVIEW, meaningful_fields=["question", "round"]
        ),
        actionable=True,
    ),
    "sdlc.review.verdict_ready": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.REVIEW, meaningful_fields=["verdict", "round"]
        )
    ),
    "teleclaude.job.run.failed": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            group_key="job_name",
            family=LifecycleFamily.JOB_RUN,
            meaningful_fields=["job_name", "status", "message"],
        ),
        actionable=True,
    ),
    "teleclaude.job.run.stalled": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            group_key="job_name",
            family=LifecycleFamily.JOB_RUN,
            meaningful_fields=["job_name", "status", "message"],
        ),
        actionable=True,
    ),
    "teleclaude.job.run.succeeded": NotificationRule(lifecycle=NotificationLifecycle()),
    "teleclaude.notification.escalation": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["escalation_id", "reason"]), actionable=True
    ),
    "teleclaude.notification.resolution": NotificationRule(
        lifecycle=NotificationLifecycle(
            resolves=True, group_key="escalation_id", family=LifecycleFamily.NOTIFICATION_ESCALATION
        )
    ),
    "teleclaude.scheduler.tick.minute": NotificationRule(
        lifecycle=NotificationLifecycle(updates=True, meaningful_fields=["ticked_at", "computer"])
    ),
    "teleclaude.signal.synthesis.ready": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True, meaningful_fields=["synthesis"]), actionable=True
    ),
    "teleclaude.system.burst.detected": NotificationRule(lifecycle=NotificationLifecycle(creates=True)),
    "teleclaude.system.daemon.restarted": NotificationRule(lifecycle=NotificationLifecycle(creates=True)),
    "teleclaude.system.entity.degraded": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            updates=True,
            group_key="entity",
            family=LifecycleFamily.ENTITY_DEGRADATION,
            meaningful_fields=["failure_count"],
        ),
        actionable=True,
    ),
    "teleclaude.system.event.dead_lettered": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True), actionable=True
    ),
    "teleclaude.system.failure_cascade.detected": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True), actionable=True
    ),
    "teleclaude.system.process.reaped": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True,
            meaningful_fields=[
                "pid",
                "signature_id",
                "signature_name",
                "reason",
                "observe_only",
                "owner",
                "lease_expires_at",
            ],
        )
    ),
    "teleclaude.system.session.bootstrap_failed": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True), actionable=True
    ),
    "teleclaude.system.worker.crashed": NotificationRule(
        lifecycle=NotificationLifecycle(creates=True), actionable=True
    ),
    "sdlc.roadmap.entry_moved": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.TODO_LIFECYCLE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.todo.created": NotificationRule(
        lifecycle=NotificationLifecycle(
            creates=True, group_key="slug", family=LifecycleFamily.TODO_LIFECYCLE, meaningful_fields=["slug", "kind"]
        )
    ),
    "sdlc.todo.delivered": NotificationRule(
        lifecycle=NotificationLifecycle(
            resolves=True, group_key="slug", family=LifecycleFamily.TODO_LIFECYCLE, meaningful_fields=["slug"]
        )
    ),
    "sdlc.todo.phase_advanced": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True,
            group_key="slug",
            family=LifecycleFamily.TODO_LIFECYCLE,
            meaningful_fields=["slug", "prior_lifecycle_phase", "lifecycle_phase"],
        )
    ),
    "sdlc.todo.updated": NotificationRule(
        lifecycle=NotificationLifecycle(
            updates=True, group_key="slug", family=LifecycleFamily.TODO_LIFECYCLE, meaningful_fields=["slug"]
        )
    ),
}


def rule_for(event_type: str) -> NotificationRule | None:
    """Return the notification rule for a type name, or None for a signal-only type."""
    return NOTIFICATION_RULES.get(event_type)

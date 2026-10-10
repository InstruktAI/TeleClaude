"""Platform event type renames: the one table that maps earlier type names to current ones.

The legacy wire projection reads it from current to earlier name, the upcaster
and the stored-data migrations read it from earlier to current. A type with no
earlier name is absent. Retiring this table is the contract step taken when no
live computer reads the earlier names.
"""

from __future__ import annotations

#: The one session-ended type name that is retired, not renamed: endings are reported under the kinded types
#: below it, and the earlier name below still decodes to it on events older computers emit.
RETIRED_SESSION_ENDED_TYPE = "teleclaude.agent_runtime.session.ended"

#: Earlier type name to current type name.
TYPE_RENAMES: dict[str, str] = {
    "agent_runtime.restart.failed": "teleclaude.agent_runtime.session.restart_failed",
    "agent_runtime.session.ended": RETIRED_SESSION_ENDED_TYPE,
    "config.effective.updated": "teleclaude.config.effective.updated",
    "content.dumped": "teleclaude.content.dumped",
    "content.published": "teleclaude.content.published",
    "content.refined": "teleclaude.content.refined",
    "deployment.completed": "teleclaude.deployment.succeeded",
    "deployment.failed": "teleclaude.deployment.failed",
    "deployment.rolled_back": "teleclaude.deployment.rolled_back",
    "deployment.started": "teleclaude.deployment.started",
    "domain.sdlc.branch.pushed": "sdlc.branch.pushed",
    "domain.sdlc.build.completed": "sdlc.build.completed",
    "domain.sdlc.deploy.failed": "sdlc.deploy.failed",
    "domain.sdlc.deploy.succeeded": "sdlc.deploy.succeeded",
    "domain.sdlc.deploy.triggered": "sdlc.deploy.triggered",
    "domain.sdlc.deployment.completed": "sdlc.deployment.completed",
    "domain.sdlc.deployment.failed": "sdlc.deployment.failed",
    "domain.sdlc.deployment.started": "sdlc.deployment.started",
    "domain.sdlc.integration.candidate.blocked": "sdlc.integration.candidate.blocked",
    "domain.sdlc.integration.candidate.delivered": "sdlc.integration.candidate.delivered",
    "domain.sdlc.integration.candidate.parked": "sdlc.integration.candidate.parked",
    "domain.sdlc.integration.drain.completed": "sdlc.integration.drain.completed",
    "domain.sdlc.integration.started": "sdlc.integration.started",
    "domain.sdlc.planning.dor_assessed": "sdlc.planning.dor_assessed",
    "domain.sdlc.planning.todo_finalize_ready": "sdlc.planning.todo_finalize_ready",
    "domain.sdlc.prepare.artifact_invalidated": "sdlc.prepare.artifact_invalidated",
    "domain.sdlc.prepare.artifact_produced": "sdlc.prepare.artifact_produced",
    "domain.sdlc.prepare.blocked": "sdlc.prepare.blocked",
    "domain.sdlc.prepare.completed": "sdlc.prepare.completed",
    "domain.sdlc.prepare.discovery_started": "sdlc.prepare.discovery_started",
    "domain.sdlc.prepare.input_consumed": "sdlc.prepare.input_consumed",
    "domain.sdlc.prepare.input_refined": "sdlc.prepare.input_refined",
    "domain.sdlc.prepare.phase_skipped": "sdlc.prepare.phase_skipped",
    "domain.sdlc.prepare.plan_approved": "sdlc.prepare.plan_approved",
    "domain.sdlc.prepare.plan_drafted": "sdlc.prepare.plan_drafted",
    "domain.sdlc.prepare.requirements_approved": "sdlc.prepare.requirements_approved",
    "domain.sdlc.prepare.requirements_drafted": "sdlc.prepare.requirements_drafted",
    "domain.sdlc.prepare.review_scoped": "sdlc.prepare.review_scoped",
    "domain.sdlc.review.approved": "sdlc.review.approved",
    "domain.sdlc.review.needs_decision": "sdlc.review.needs_decision",
    "domain.sdlc.review.verdict_ready": "sdlc.review.verdict_ready",
    "job.run.failed": "teleclaude.job.run.failed",
    "job.run.stalled": "teleclaude.job.run.stalled",
    "job.run.succeeded": "teleclaude.job.run.succeeded",
    "node.alive": "teleclaude.node.alive",
    "node.descriptor_updated": "teleclaude.node.descriptor_updated",
    "node.leaving": "teleclaude.node.leaving",
    "notification.escalation": "teleclaude.notification.escalation",
    "notification.resolution": "teleclaude.notification.resolution",
    "scheduler.tick.minute": "teleclaude.scheduler.tick.minute",
    "schema.adopted": "teleclaude.schema.adopted",
    "schema.proposed": "teleclaude.schema.proposed",
    "signal.cluster.formed": "teleclaude.signal.cluster.formed",
    "signal.ingest.received": "teleclaude.signal.ingest.received",
    "signal.synthesis.ready": "teleclaude.signal.synthesis.ready",
    "system.burst.detected": "teleclaude.system.burst.detected",
    "system.daemon.restarted": "teleclaude.system.daemon.restarted",
    "system.entity.degraded": "teleclaude.system.entity.degraded",
    "system.event.dead_lettered": "teleclaude.system.event.dead_lettered",
    "system.failure_cascade.detected": "teleclaude.system.failure_cascade.detected",
    "system.process.reaped": "teleclaude.system.process.reaped",
    "system.session.bootstrap_failed": "teleclaude.system.session.bootstrap_failed",
    "system.worker.crashed": "teleclaude.system.worker.crashed",
    "workflow.roadmap.entry_moved": "sdlc.roadmap.entry_moved",
    "workflow.todo.created": "sdlc.todo.created",
    "workflow.todo.delivered": "sdlc.todo.delivered",
    "workflow.todo.phase_advanced": "sdlc.todo.phase_advanced",
    "workflow.todo.updated": "sdlc.todo.updated",
}

_EARLIER_NAMES: dict[str, str] = {current: earlier for earlier, current in TYPE_RENAMES.items()}


def current_type_name(earlier_name: str) -> str:
    """Return the current name for an earlier type name; an unknown name passes through."""
    return TYPE_RENAMES.get(earlier_name, earlier_name)


def earlier_type_name(current_name: str) -> str:
    """Return the name an older computer knows a current type by; a type with none keeps its own."""
    return _EARLIER_NAMES.get(current_name, current_name)

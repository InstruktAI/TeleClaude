"""System event schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from teleclaude.events.catalog import EventSchema, LifecycleFamily, NotificationLifecycle
from teleclaude.events.envelope import EventLevel, EventVisibility

if TYPE_CHECKING:
    from teleclaude.events.catalog import EventCatalog


def register_system(catalog: EventCatalog) -> None:
    """Register core system event schemas."""
    catalog.register(
        EventSchema(
            event_type="config.effective.updated",
            description="Effective project configuration changed and may affect workflow runner eligibility",
            default_level=EventLevel.WORKFLOW,
            domain="config",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(
                updates=True,
                group_key="project_path",
                family=LifecycleFamily.CONFIG_SYNC,
                meaningful_fields=["project_path"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="agent_runtime.session.ended",
            description="A session was closed and may require lifecycle-runner re-evaluation of its todo",
            default_level=EventLevel.WORKFLOW,
            domain="agent_runtime",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                resolves=True,
                group_key="session_id",
                family=LifecycleFamily.AGENT_SESSION_LIFECYCLE,
                meaningful_fields=["session_id", "project_path"],
            ),
        )
    )
    catalog.register(
        EventSchema(
            event_type="agent_runtime.restart.failed",
            description="An agent restart failed before the agent could resume, and the session was kept alive for inspection",
            default_level=EventLevel.OPERATIONAL,
            domain="agent_runtime",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                creates=True,
                updates=True,
                group_key="restart_group",
                family=LifecycleFamily.AGENT_RESTART,
                meaningful_fields=["reason", "phase"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.daemon.restarted",
            description="Daemon process restarted on a computer",
            default_level=EventLevel.INFRASTRUCTURE,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.worker.crashed",
            description="A background worker crashed unexpectedly",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.session.bootstrap_failed",
            description="A session's tmux/identity bootstrap failed, stranding it before it reached active",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.process.reaped",
            description="Process janitor reaped or observed a reapable process",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
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
            ),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.event.dead_lettered",
            description="An event exhausted its retry ceiling and transitioned to the dead-letter destination",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.docs_watcher.sync_failed",
            description="Docs watcher sync failed or entered a repeated trigger loop",
            default_level=EventLevel.WORKFLOW,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                creates=True,
                updates=True,
                group_key="entity",
                family=LifecycleFamily.DOCS_WATCHER_SYNC,
                meaningful_fields=["reason", "returncode", "trigger_count"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.burst.detected",
            description=(
                "A burst of events of the same type was detected within a short window. "
                "Payload: event_type, window_start, count"
            ),
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.failure_cascade.detected",
            description=(
                "Multiple worker crashes detected within a short window. Payload: crash_count, window_start, workers"
            ),
            default_level=EventLevel.BUSINESS,
            domain="system",
            default_visibility=EventVisibility.CLUSTER,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.entity.degraded",
            description=(
                "Repeated failures detected for the same entity within a short window. "
                "Payload: entity, failure_count, window_start"
            ),
            default_level=EventLevel.WORKFLOW,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(
                creates=True,
                updates=True,
                group_key="entity",
                family=LifecycleFamily.ENTITY_DEGRADATION,
                meaningful_fields=["failure_count"],
            ),
            actionable=True,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.sandbox-container.unhealthy",
            description="Sandbox container failed repeated health checks and is permanently disabled",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )
    catalog.register(
        EventSchema(
            event_type="system.sandbox-container.docker-unavailable",
            description="Docker is not available; sandbox container subsystem is disabled",
            default_level=EventLevel.OPERATIONAL,
            domain="system",
            default_visibility=EventVisibility.LOCAL,
            lifecycle=NotificationLifecycle(creates=True),
            actionable=False,
        )
    )

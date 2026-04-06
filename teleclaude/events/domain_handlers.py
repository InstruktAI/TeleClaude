"""Static registry for repo-owned domain event handlers."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from teleclaude.events.domains.creative_production.handlers.asset_lifecycle.handler import (
    process as creative_asset_lifecycle,
)
from teleclaude.events.domains.creative_production.handlers.review_gatekeeper.handler import (
    process as creative_review_gatekeeper,
)
from teleclaude.events.domains.customer_relations.handlers.escalation_handler.handler import (
    process as customer_escalation_handler,
)
from teleclaude.events.domains.customer_relations.handlers.helpdesk_triage.handler import (
    process as customer_helpdesk_triage,
)
from teleclaude.events.domains.customer_relations.handlers.satisfaction_tracker.handler import (
    process as customer_satisfaction_tracker,
)
from teleclaude.events.domains.marketing.handlers.campaign_budget_monitor.handler import (
    process as marketing_campaign_budget_monitor,
)
from teleclaude.events.domains.marketing.handlers.content_pipeline.handler import process as marketing_content_pipeline
from teleclaude.events.domains.marketing.handlers.feed_monitor.handler import process as marketing_feed_monitor
from teleclaude.events.domains.software_development.handlers.build_notifier.handler import (
    process as software_build_notifier,
)
from teleclaude.events.domains.software_development.handlers.deploy_tracker.handler import (
    process as software_deploy_tracker,
)
from teleclaude.events.domains.software_development.handlers.todo_lifecycle.handler import (
    process as software_todo_lifecycle,
)
from teleclaude.events.envelope import EventEnvelope
from teleclaude.events.pipeline import PipelineContext

DomainHandler = Callable[[EventEnvelope, PipelineContext], Awaitable[EventEnvelope | None]]


class DomainHandlerError(Exception):
    """Base exception for static domain handler registry errors."""


class DomainDependencyError(DomainHandlerError):
    """Raised when a handler declares a missing or cyclic dependency."""


@dataclass(frozen=True)
class DomainHandlerSpec:
    """Static definition for one repo-owned domain handler."""

    handler_id: str
    process: DomainHandler
    depends_on: tuple[str, ...] = ()


_DOMAIN_HANDLERS: dict[str, tuple[DomainHandlerSpec, ...]] = {
    "software-development": (
        DomainHandlerSpec("todo-lifecycle", software_todo_lifecycle),
        DomainHandlerSpec("build-notifier", software_build_notifier),
        DomainHandlerSpec("deploy-tracker", software_deploy_tracker),
    ),
    "marketing": (
        DomainHandlerSpec("content-pipeline", marketing_content_pipeline),
        DomainHandlerSpec("campaign-budget-monitor", marketing_campaign_budget_monitor),
        DomainHandlerSpec("feed-monitor", marketing_feed_monitor),
    ),
    "creative-production": (
        DomainHandlerSpec("asset-lifecycle", creative_asset_lifecycle),
        DomainHandlerSpec("review-gatekeeper", creative_review_gatekeeper, depends_on=("asset-lifecycle",)),
    ),
    "customer-relations": (
        DomainHandlerSpec("helpdesk-triage", customer_helpdesk_triage),
        DomainHandlerSpec("satisfaction-tracker", customer_satisfaction_tracker),
        DomainHandlerSpec("escalation-handler", customer_escalation_handler, depends_on=("helpdesk-triage",)),
    ),
}


def handler_ids_for_domain(domain_name: str) -> tuple[str, ...]:
    """Return the configured handler ids for a domain."""
    return tuple(spec.handler_id for spec in _DOMAIN_HANDLERS.get(domain_name, ()))


def build_handler_levels(domain_name: str) -> list[list[DomainHandlerSpec]]:
    """Return topologically sorted execution levels for one domain."""
    specs = list(_DOMAIN_HANDLERS.get(domain_name, ()))
    if not specs:
        return []

    by_id = {spec.handler_id: spec for spec in specs}
    in_degree: dict[str, int] = {spec.handler_id: 0 for spec in specs}
    dependents: dict[str, list[str]] = defaultdict(list)

    for spec in specs:
        for dependency in spec.depends_on:
            if dependency not in by_id:
                raise DomainDependencyError(
                    f"Domain '{domain_name}' handler '{spec.handler_id}' depends on missing handler '{dependency}'"
                )
            dependents[dependency].append(spec.handler_id)
            in_degree[spec.handler_id] += 1

    queue: deque[str] = deque(handler_id for handler_id, degree in in_degree.items() if degree == 0)
    processed: set[str] = set()
    levels: list[list[DomainHandlerSpec]] = []

    while queue:
        current_level = list(queue)
        queue.clear()
        processed.update(current_level)
        levels.append([by_id[handler_id] for handler_id in current_level])

        next_queue: list[str] = []
        for handler_id in current_level:
            for dependent in dependents[handler_id]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_queue.append(dependent)
        queue.extend(next_queue)

    if len(processed) != len(specs):
        unresolved = sorted(handler_id for handler_id in by_id if handler_id not in processed)
        raise DomainDependencyError(f"Domain '{domain_name}' has a dependency cycle among handlers: {unresolved}")

    return levels

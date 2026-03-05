"""Domain pipeline runtime — parallel per-domain execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude_events.cartridge_loader import LoadedCartridge
from teleclaude_events.domain_config import (
    AutonomyLevel,
    AutonomyMatrix,
    DomainConfig,
    DomainGuardianConfig,
)
from teleclaude_events.envelope import EventEnvelope
from teleclaude_events.pipeline import PipelineContext

if TYPE_CHECKING:
    from teleclaude_events.personal_pipeline import PersonalPipeline

logger = get_logger(__name__)


@dataclass
class DomainPipelineContext(PipelineContext):
    domain_name: str = ""
    autonomy_matrix: AutonomyMatrix = field(default_factory=AutonomyMatrix)
    guardian_config: DomainGuardianConfig = field(default_factory=DomainGuardianConfig)


class DomainPipeline:
    def __init__(self, domain: DomainConfig, levels: list[list[LoadedCartridge]]) -> None:
        self._domain = domain
        self._levels = levels

    async def run(self, event: EventEnvelope, base_context: PipelineContext) -> EventEnvelope | None:
        base_fields = {f.name: getattr(base_context, f.name) for f in fields(PipelineContext)}
        ctx = DomainPipelineContext(
            **base_fields,
            domain_name=self._domain.name,
            autonomy_matrix=self._domain.autonomy,
            guardian_config=self._domain.guardian,
        )

        current: EventEnvelope | None = event

        for level in self._levels:
            if current is None:
                return None

            level_event = current
            results = await asyncio.gather(
                *[self._run_cartridge(c, level_event, ctx) for c in level],
                return_exceptions=True,
            )

            # Take last non-None result; exceptions already logged by _run_cartridge
            last_result: EventEnvelope | None = None
            for r in results:
                if isinstance(r, BaseException):
                    continue
                if r is not None:
                    last_result = r

            current = last_result

        return current

    async def _run_cartridge(
        self,
        cartridge: LoadedCartridge,
        event: EventEnvelope,
        ctx: DomainPipelineContext,
    ) -> EventEnvelope | None:
        cartridge_id = cartridge.manifest.id
        autonomy = ctx.autonomy_matrix.resolve(ctx.domain_name, cartridge_id, event.event)

        if autonomy == AutonomyLevel.manual:
            logger.debug(
                "Cartridge '%s' in domain '%s' skipped: autonomy=manual",
                cartridge_id,
                ctx.domain_name,
            )
            return None

        try:
            result = await cartridge.process(event, ctx)
        except Exception as e:
            logger.error(
                "Cartridge '%s' in domain '%s' raised an exception: %s",
                cartridge_id,
                ctx.domain_name,
                e,
                exc_info=True,
            )
            return None

        if autonomy == AutonomyLevel.notify and result is not None:
            logger.info(
                "Cartridge '%s' in domain '%s' ran (notify mode); result produced",
                cartridge_id,
                ctx.domain_name,
            )
        elif autonomy == AutonomyLevel.auto_notify and result is None:
            logger.debug(
                "Cartridge '%s' in domain '%s' returned None (auto_notify, suppressing notification)",
                cartridge_id,
                ctx.domain_name,
            )

        return result


class DomainPipelineRunner:
    def __init__(self) -> None:
        self._pipelines: dict[str, DomainPipeline] = {}
        self._personal_pipelines: dict[str, PersonalPipeline] = {}

    def register_domain_pipeline(self, domain_name: str, pipeline: DomainPipeline) -> None:
        self._pipelines[domain_name] = pipeline

    def register_personal_pipeline(self, member_id: str, pipeline: PersonalPipeline) -> None:
        self._personal_pipelines[member_id] = pipeline

    async def run_all(self, event: EventEnvelope, context: PipelineContext) -> dict[str, EventEnvelope | None]:
        results: dict[str, EventEnvelope | None] = {}
        if not self._pipelines and not self._personal_pipelines:
            return results

        domain_results = await asyncio.gather(
            *[self._run_domain(name, p, event, context) for name, p in self._pipelines.items()],
            return_exceptions=True,
        )

        for name, result in zip(self._pipelines.keys(), domain_results):
            if isinstance(result, BaseException):
                logger.error("Domain pipeline '%s' failed: %s", name, result, exc_info=result)
                results[name] = None
            else:
                results[name] = result

        # Run personal pipelines in parallel after domain pipelines
        if self._personal_pipelines:
            personal_results = await asyncio.gather(
                *[p.run(event, context) for p in self._personal_pipelines.values()],
                return_exceptions=True,
            )
            for member_id, presult in zip(self._personal_pipelines.keys(), personal_results):
                if isinstance(presult, BaseException):
                    logger.error(
                        "Personal pipeline '%s' failed: %s", member_id, presult, exc_info=presult
                    )

        return results

    async def _run_domain(
        self,
        name: str,
        pipeline: DomainPipeline,
        event: EventEnvelope,
        context: PipelineContext,
    ) -> EventEnvelope | None:
        return await pipeline.run(event, context)

    async def run_for_domain(self, domain: str, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None:
        pipeline = self._pipelines.get(domain)
        if pipeline is None:
            return None
        return await pipeline.run(event, context)

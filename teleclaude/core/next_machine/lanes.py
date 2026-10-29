"""Workflow-owned groupings of catalog roles by lifecycle lane.

The role catalog composes what each role may reach; which lifecycle lane a role belongs to is the
workflow's own decision, expressed here as sets of catalog role names.
"""

from __future__ import annotations

from enum import StrEnum

from teleclaude.constants import DriverLaunchClass
from teleclaude.core.next_machine.runner_types import RunnerLane
from teleclaude.core.roles import REVIEWER_ROLES, RoleName


class LifecycleProcedure(StrEnum):
    """The entry procedures the lifecycle state machines and the platform's own dispatchers name."""

    PREPARE = "sdlc/procedure/lifecycle/prepare/overview"
    INTAKE = "sdlc/procedure/lifecycle/prepare/intake"
    ARCHITECTURE = "sdlc/procedure/lifecycle/prepare/architecture"
    PLAN_DRAFT = "sdlc/procedure/lifecycle/prepare/plan-draft"
    DIAGNOSE = "sdlc/procedure/lifecycle/prepare/diagnose-peer"
    REVIEW_PRD = "sdlc/procedure/lifecycle/prepare/review-prd"
    REVIEW_ARCHITECTURE = "sdlc/procedure/lifecycle/prepare/review-architecture"
    REVIEW_PLAN = "sdlc/procedure/lifecycle/prepare/review-plan"
    DRIFT_ANALYZE = "sdlc/procedure/lifecycle/prepare/drift-analyze"
    WORK = "sdlc/procedure/lifecycle/work/overview"
    BUILD = "sdlc/procedure/lifecycle/work/build"
    REVIEW_BUILD = "sdlc/procedure/lifecycle/work/review-build"
    REVIEW_COMMITS = "sdlc/procedure/lifecycle/work/review-commits"
    FINALIZE = "sdlc/procedure/lifecycle/work/finalize"
    DEFERRALS = "sdlc/procedure/lifecycle/work/deferrals"
    INTEGRATE = "sdlc/procedure/lifecycle/integrate"
    COORDINATE = "sdlc/procedure/lifecycle/coordinate"
    PREPARE_TASK = "sdlc/procedure/lifecycle/task/prepare-task"
    RUN_TASK = "sdlc/procedure/lifecycle/task/run-task"
    CREATE = "creative/procedure/creative-orchestration"
    CREATE_ART = "creative/procedure/image-generation/nano-banana"
    CREATE_HTML = "creative/procedure/visual-drafting"


#: The entry procedure a driver of each lane is started through; the procedure declares the driver's role.
LANE_ENTRY_PROCEDURES: dict[RunnerLane, LifecycleProcedure] = {
    RunnerLane.PREPARE: LifecycleProcedure.PREPARE,
    RunnerLane.WORK: LifecycleProcedure.WORK,
    RunnerLane.TASK_PREPARE: LifecycleProcedure.PREPARE_TASK,
    RunnerLane.TASK_RUN: LifecycleProcedure.RUN_TASK,
}

#: The procedures whose session must run in the todo's worktree: the work lane's per-slug workers.
WORKTREE_BOUND_PROCEDURES: frozenset[str] = frozenset(
    {LifecycleProcedure.BUILD.value, LifecycleProcedure.REVIEW_BUILD.value, LifecycleProcedure.FINALIZE.value}
)

#: The roles that drive a todo's lifecycle: a prepare or work orchestrator, a creative orchestrator, and the
#: prepare drafting phases a prepare orchestrator performs inline.
DRIVER_ROLES: frozenset[str] = frozenset(
    {
        RoleName.PREPARE_ORCHESTRATOR.value,
        RoleName.WORK_ORCHESTRATOR.value,
        RoleName.CREATE_ORCHESTRATOR.value,
        RoleName.INTAKER.value,
        RoleName.ARCHITECT.value,
        RoleName.PLANNER.value,
    }
)

#: The roles of the prepare lane, used to adopt a prepare phase in place. The diagnoser is dispatched as a
#: worker while every other prepare phase runs inline as the orchestrator. Prepare-artifact write authority is
#: the role catalog's ``prepare-artifact-write`` capability, not this grouping.
PREPARE_AUTHOR_ROLES: frozenset[str] = frozenset(
    {
        RoleName.PREPARE_ORCHESTRATOR.value,
        RoleName.INTAKER.value,
        RoleName.ARCHITECT.value,
        RoleName.DIAGNOSER.value,
        RoleName.PLANNER.value,
    }
)

#: The lifecycle build and finalize roles: the todo-worktree source writers.
TODO_WORKTREE_WRITER_ROLES: frozenset[str] = frozenset({RoleName.BUILDER.value, RoleName.FINALIZER.value})

#: The roles that belong to the work lane: the work orchestrator and its worktree writers. The reviewer and the
#: drift analyzer are dispatched by both lanes, so no role places them in either one.
WORK_LANE_ROLES: frozenset[str] = frozenset({RoleName.WORK_ORCHESTRATOR.value, *TODO_WORKTREE_WRITER_ROLES})


def classify_driver_launch(role: str | None) -> DriverLaunchClass:
    """Classify a session-create launch by the role its procedure declares, for driver-start dedup.

    The create-door guard keys on what the requested launch IS: a lifecycle driver role is an
    ``ORCHESTRATOR`` driver, the task runner is the ``TASK_LANE`` driver, a reviewer is a ``REVIEWER``,
    and every other role (including no role) is a ``WORKER_CHILD`` that a driver may legitimately spawn
    against a shared ``working_slug``.
    """
    if role == RoleName.TASK_RUNNER.value:
        return DriverLaunchClass.TASK_LANE
    if role in DRIVER_ROLES:
        return DriverLaunchClass.ORCHESTRATOR
    if role in REVIEWER_ROLES:
        return DriverLaunchClass.REVIEWER
    return DriverLaunchClass.WORKER_CHILD

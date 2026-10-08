"""Deployment event declarations: the deployed project's deployment is the subject across all its deployments."""

from __future__ import annotations

from pydantic import JsonValue

from teleclaude.events.catalog import DeclaredEvent, EventData, LifecycleState, PlatformEvent
from teleclaude.events.envelope import EventHomeKind
from teleclaude.events.references import DeploymentRef

DEPLOYMENT_FAMILY = "teleclaude.deployment"
_PROJECT_HOME = (EventHomeKind.PROJECT,)


class DeploymentSlugData(EventData):
    slug: JsonValue


class DeploymentStartedData(EventData):
    slug: JsonValue | None = None


class DeploymentFailedData(EventData):
    reason: JsonValue | None = None
    slug: JsonValue | None = None


class DeploymentStarted(PlatformEvent[DeploymentRef, DeploymentStartedData]):
    NAME = "teleclaude.deployment.started"
    DESCRIPTION = "Deployment initiated"
    HOME_KINDS = _PROJECT_HOME


class DeploymentSucceeded(PlatformEvent[DeploymentRef, DeploymentSlugData]):
    FAMILY = DEPLOYMENT_FAMILY
    STATE = LifecycleState.SUCCEEDED
    DESCRIPTION = "Deployment succeeded"
    HOME_KINDS = _PROJECT_HOME


class DeploymentFailed(PlatformEvent[DeploymentRef, DeploymentFailedData]):
    FAMILY = DEPLOYMENT_FAMILY
    STATE = LifecycleState.FAILED
    DESCRIPTION = "Deployment failed and requires attention"
    HOME_KINDS = _PROJECT_HOME


class DeploymentRolledBack(PlatformEvent[DeploymentRef, DeploymentSlugData]):
    NAME = "teleclaude.deployment.rolled_back"
    DESCRIPTION = "Rollback executed after deployment failure"
    HOME_KINDS = _PROJECT_HOME


DECLARED: tuple[DeclaredEvent, ...] = (
    DeploymentStarted,
    DeploymentSucceeded,
    DeploymentFailed,
    DeploymentRolledBack,
)

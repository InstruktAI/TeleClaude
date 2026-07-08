"""Recurring job event schemas."""

from __future__ import annotations

import pytest

from teleclaude.events.catalog import build_default_catalog
from teleclaude.events.envelope import EventLevel
from teleclaude.events.schemas.jobs import (
    JOB_OUTCOME_GROUP_KEY,
    JOB_OUTCOME_MEANINGFUL_FIELDS,
    JOBS_DOMAIN,
    JobRunEventType,
)

pytestmark = pytest.mark.functional


def test_register_all_exposes_job_run_outcome_schemas() -> None:
    """The default catalog includes every recurring-job outcome schema."""
    catalog = build_default_catalog()

    for event_type in JobRunEventType:
        assert catalog.get(event_type) is not None


def test_success_schema_is_quiet_workflow_outcome() -> None:
    """A successful job run is workflow-level and does not create an actionable notification."""
    schema = build_default_catalog().get(JobRunEventType.SUCCEEDED)

    assert schema is not None
    assert schema.default_level is EventLevel.WORKFLOW
    assert schema.domain == JOBS_DOMAIN
    assert schema.actionable is False
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is False


def test_failed_schema_creates_actionable_job_notification() -> None:
    """A failed job run creates an actionable notification grouped by job name."""
    schema = build_default_catalog().get(JobRunEventType.FAILED)

    assert schema is not None
    assert schema.default_level is EventLevel.OPERATIONAL
    assert schema.domain == JOBS_DOMAIN
    assert schema.actionable is True
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.group_key == JOB_OUTCOME_GROUP_KEY
    assert schema.lifecycle.meaningful_fields == JOB_OUTCOME_MEANINGFUL_FIELDS


def test_stalled_schema_creates_actionable_job_notification() -> None:
    """A stalled job run creates an actionable notification grouped by job name."""
    schema = build_default_catalog().get(JobRunEventType.STALLED)

    assert schema is not None
    assert schema.default_level is EventLevel.OPERATIONAL
    assert schema.domain == JOBS_DOMAIN
    assert schema.actionable is True
    assert schema.lifecycle is not None
    assert schema.lifecycle.creates is True
    assert schema.lifecycle.group_key == JOB_OUTCOME_GROUP_KEY
    assert schema.lifecycle.meaningful_fields == JOB_OUTCOME_MEANINGFUL_FIELDS

"""Characterization tests for teleclaude.cli.tui.views._config_constants."""

from __future__ import annotations

import pytest

from teleclaude.cli.config_handlers import EnvVarInfo, EnvVarStatus
from teleclaude.cli.tui.views._config_constants import (
    _ADAPTER_ENV_KEYS,
    _ADAPTER_LABELS,
    _ADAPTER_TABS,
    _GUIDED_STEPS,
    _SUBTABS,
    _VALID_ROLES,
    AdapterSectionProjection,
    NotificationProjection,
    classify_adapter_status,
    completion_summary,
    project_adapter_sections,
)


def _make_env_status(adapter: str, *, is_set: bool) -> EnvVarStatus:
    info = EnvVarInfo(name=f"FAKE_{adapter.upper()}", adapter=adapter, description="", example="")
    return EnvVarStatus(info=info, is_set=is_set)


# --- classify_adapter_status ---


@pytest.mark.unit
def test_classify_adapter_status_returns_unconfigured_when_list_empty() -> None:
    assert classify_adapter_status([]) == "unconfigured"


@pytest.mark.unit
def test_classify_adapter_status_returns_unconfigured_when_none_set() -> None:
    statuses = [_make_env_status("telegram", is_set=False)]
    assert classify_adapter_status(statuses) == "unconfigured"


@pytest.mark.unit
def test_classify_adapter_status_returns_configured_when_all_set() -> None:
    statuses = [
        _make_env_status("telegram", is_set=True),
        _make_env_status("telegram", is_set=True),
    ]
    assert classify_adapter_status(statuses) == "configured"


@pytest.mark.unit
def test_classify_adapter_status_returns_partial_when_some_set() -> None:
    statuses = [
        _make_env_status("telegram", is_set=True),
        _make_env_status("telegram", is_set=False),
    ]
    assert classify_adapter_status(statuses) == "partial"


# --- completion_summary ---


@pytest.mark.unit
def test_completion_summary_counts_configured_adapters() -> None:
    sections = [
        AdapterSectionProjection(
            key="telegram", label="Telegram", env_statuses=[], status="configured", configured_count=1, total_count=1
        ),
        AdapterSectionProjection(
            key="discord", label="Discord", env_statuses=[], status="unconfigured", configured_count=0, total_count=1
        ),
    ]
    configured, total = completion_summary(
        sections, has_people=False, notifications_configured=False, environment_configured=False
    )
    assert configured == 1
    assert total == 5  # 2 adapters + 3 core sections


@pytest.mark.unit
def test_completion_summary_counts_all_core_sections_when_all_true() -> None:
    sections = [
        AdapterSectionProjection(
            key="telegram", label="Telegram", env_statuses=[], status="configured", configured_count=1, total_count=1
        ),
    ]
    configured, total = completion_summary(
        sections, has_people=True, notifications_configured=True, environment_configured=True
    )
    assert configured == 4  # 1 adapter + 3 core
    assert total == 4  # 1 adapter + 3 core


# --- project_adapter_sections ---


@pytest.mark.unit
def test_project_adapter_sections_returns_one_section_per_adapter_tab() -> None:
    sections = project_adapter_sections([])
    assert len(sections) == len(_ADAPTER_TABS)


@pytest.mark.unit
def test_project_adapter_sections_keys_match_adapter_tabs() -> None:
    sections = project_adapter_sections([])
    for section, tab_key in zip(sections, _ADAPTER_TABS):
        assert section.key == tab_key


@pytest.mark.unit
def test_project_adapter_sections_filters_env_data_by_adapter() -> None:
    tg_status = _make_env_status("telegram", is_set=True)
    dc_status = _make_env_status("discord", is_set=False)
    sections = project_adapter_sections([tg_status, dc_status])

    tg_section = next(s for s in sections if s.key == "telegram")
    dc_section = next(s for s in sections if s.key == "discord")

    assert tg_section.configured_count == 1
    assert dc_section.configured_count == 0


@pytest.mark.unit
def test_project_adapter_sections_labels_match_adapter_labels() -> None:
    sections = project_adapter_sections([])
    for section in sections:
        assert section.label == _ADAPTER_LABELS[section.key]


# --- constants ---


@pytest.mark.unit
def test_subtabs_contains_four_tabs() -> None:
    assert len(_SUBTABS) == 4


@pytest.mark.unit
def test_valid_roles_contains_expected_roles() -> None:
    assert "admin" in _VALID_ROLES
    assert "member" in _VALID_ROLES


@pytest.mark.unit
def test_guided_steps_cover_all_subtabs() -> None:
    covered_subtabs = {step.subtab for step in _GUIDED_STEPS}
    for subtab in _SUBTABS:
        assert subtab in covered_subtabs


@pytest.mark.unit
def test_adapter_env_keys_maps_all_adapter_tabs() -> None:
    for tab in _ADAPTER_TABS:
        assert tab in _ADAPTER_ENV_KEYS


# --- data classes ---


@pytest.mark.unit
def test_guided_step_adapter_tab_optional_for_non_adapter_steps() -> None:
    people_step = next(s for s in _GUIDED_STEPS if s.subtab == "people")
    assert people_step.adapter_tab is None


@pytest.mark.unit
def test_notification_projection_stores_fields() -> None:
    proj = NotificationProjection(
        configured=True,
        total_people=3,
        people_with_subscriptions=2,
        total_subscriptions=5,
        next_action="none",
    )
    assert proj.configured is True
    assert proj.total_people == 3

"""Characterization tests for teleclaude.core.command_service."""

from __future__ import annotations

import pytest

from teleclaude.constants import JobRole, SlashCommand
from teleclaude.core.command_service import COMMAND_ROLE_MAP


class TestCommandRoleMap:
    @pytest.mark.unit
    def test_next_build_maps_to_worker_builder(self):
        role_info = COMMAND_ROLE_MAP.get(SlashCommand.NEXT_BUILD)
        assert role_info is not None
        _, job_role = role_info
        assert job_role == JobRole.BUILDER

    @pytest.mark.unit
    def test_next_review_build_maps_to_reviewer(self):
        role_info = COMMAND_ROLE_MAP.get(SlashCommand.NEXT_REVIEW_BUILD)
        assert role_info is not None
        _, job_role = role_info
        assert job_role == JobRole.REVIEWER

    @pytest.mark.unit
    def test_next_integrate_maps_to_integrator(self):
        role_info = COMMAND_ROLE_MAP.get(SlashCommand.NEXT_INTEGRATE)
        assert role_info is not None
        _, job_role = role_info
        assert job_role == JobRole.INTEGRATOR

    @pytest.mark.unit
    def test_all_entries_have_two_tuple_shape(self):
        for cmd, role_info in COMMAND_ROLE_MAP.items():
            assert len(role_info) == 2, f"Expected 2-tuple for {cmd}"
            system_role, job_role = role_info
            assert isinstance(system_role, str)
            assert isinstance(job_role, JobRole)

    @pytest.mark.unit
    def test_map_is_not_empty(self):
        assert len(COMMAND_ROLE_MAP) > 0

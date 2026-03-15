"""Characterization tests for teleclaude.config.schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from teleclaude.config.schema import (
    DeploymentConfig,
    GlobalConfig,
    IntegratorCutoverConfig,
    JobWhenConfig,
    PersonConfig,
    ProjectConfig,
)


class TestJobWhenConfig:
    @pytest.mark.unit
    @pytest.mark.parametrize("every", ["1m", "2h", "3d"])
    def test_accepts_supported_every_values(self, every: str) -> None:
        config = JobWhenConfig(every=every)
        assert config.every == every

    @pytest.mark.unit
    @pytest.mark.parametrize("every", ["0m", "soon", "15x"])
    def test_rejects_invalid_every_values(self, every: str) -> None:
        with pytest.raises(ValidationError):
            JobWhenConfig(every=every)

    @pytest.mark.unit
    @pytest.mark.parametrize("at_value", ["09:00", ["09:00", "14:30"]])
    def test_accepts_wall_clock_times(self, at_value: str | list[str]) -> None:
        config = JobWhenConfig(at=at_value)
        assert config.at == at_value

    @pytest.mark.unit
    @pytest.mark.parametrize("at_value", ["9:00", "24:00", ["07:00", "12:99"]])
    def test_rejects_invalid_wall_clock_times(self, at_value: str | list[str]) -> None:
        with pytest.raises(ValidationError):
            JobWhenConfig(at=at_value)

    @pytest.mark.unit
    def test_requires_exactly_one_schedule_mode(self) -> None:
        with pytest.raises(ValidationError, match="Specify exactly one of 'every' or 'at'"):
            JobWhenConfig()

        with pytest.raises(ValidationError, match="Specify exactly one of 'every' or 'at'"):
            JobWhenConfig(every="10m", at="09:00")

    @pytest.mark.unit
    def test_weekdays_require_explicit_time(self) -> None:
        with pytest.raises(ValidationError, match="'weekdays' requires 'at'"):
            JobWhenConfig(every="10m", weekdays=["mon"])


class TestSchemaValidators:
    @pytest.mark.unit
    def test_integrator_cutover_requires_parity_acceptance(self) -> None:
        with pytest.raises(ValidationError, match="parity_evidence_accepted=true"):
            IntegratorCutoverConfig(enabled=True)

    @pytest.mark.unit
    def test_deployment_stable_requires_pinned_minor(self) -> None:
        with pytest.raises(ValidationError, match="pinned_minor is required"):
            DeploymentConfig(channel="stable")

    @pytest.mark.unit
    def test_project_config_rejects_global_only_keys(self) -> None:
        with pytest.raises(ValidationError, match="Keys not allowed at project level: people"):
            ProjectConfig.model_validate({"people": []})

    @pytest.mark.unit
    def test_global_config_parses_interests_tags_dict(self) -> None:
        config = GlobalConfig.model_validate({"interests": {"tags": ["ai", "ops"]}})
        assert config.interests == ["ai", "ops"]

    @pytest.mark.unit
    def test_global_config_rejects_person_only_keys(self) -> None:
        with pytest.raises(ValidationError, match="Keys not allowed at global level: creds"):
            GlobalConfig.model_validate({"creds": {}})

    @pytest.mark.unit
    def test_person_config_parses_interests_tags_dict(self) -> None:
        config = PersonConfig.model_validate({"interests": {"tags": ["devtools"]}})
        assert config.interests == ["devtools"]

    @pytest.mark.unit
    def test_person_config_rejects_project_only_keys(self) -> None:
        with pytest.raises(ValidationError, match="Keys not allowed at per-person level: business"):
            PersonConfig.model_validate({"business": {}})

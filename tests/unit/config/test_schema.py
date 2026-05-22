"""Characterization tests for teleclaude.config.schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from syrupy.assertion import SnapshotAssertion

from teleclaude.config.schema import (
    DeploymentConfig,
    GlobalConfig,
    IntegratorCutoverConfig,
    JobWhenConfig,
    PersonConfig,
    PersonEntry,
    ProjectConfig,
)


class TestJobWhenConfig:
    @pytest.mark.unit
    # guard: parametrize-cleanup-pending - tracked by main-lint-debt-cleanup
    @pytest.mark.parametrize("every", ["1m", "2h", "3d"])
    def test_accepts_supported_every_values(self, every: str) -> None:
        config = JobWhenConfig(every=every)
        assert config.every == every

    @pytest.mark.unit
    # guard: parametrize-cleanup-pending - tracked by main-lint-debt-cleanup
    @pytest.mark.parametrize("every", ["0m", "soon", "15x"])
    def test_rejects_invalid_every_values(self, every: str) -> None:
        with pytest.raises(ValidationError):
            JobWhenConfig(every=every)

    @pytest.mark.unit
    # guard: parametrize-cleanup-pending - tracked by main-lint-debt-cleanup
    @pytest.mark.parametrize("at_value", ["09:00", ["09:00", "14:30"]])
    def test_accepts_wall_clock_times(self, at_value: str | list[str]) -> None:
        config = JobWhenConfig(at=at_value)
        assert config.at == at_value

    @pytest.mark.unit
    # guard: parametrize-cleanup-pending - tracked by main-lint-debt-cleanup
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

    @pytest.mark.unit
    def test_person_entry_requires_non_empty_email(self) -> None:
        with pytest.raises(ValidationError):
            PersonEntry.model_validate({"name": "Alice", "email": ""})

    @pytest.mark.unit
    def test_person_entry_rejects_blank_email(self) -> None:
        with pytest.raises(ValidationError):
            PersonEntry.model_validate({"name": "Alice", "email": "   "})

    @pytest.mark.unit
    def test_person_entry_strips_email(self) -> None:
        entry = PersonEntry.model_validate({"name": "Alice", "email": " alice@example.com "})
        assert entry.email == "alice@example.com"

    @pytest.mark.unit
    def test_project_slug_defaults_to_none_for_legacy_configs(self) -> None:
        config = ProjectConfig.model_validate({"project_name": "Alpha"})
        assert config.project_slug is None

    @pytest.mark.unit
    def test_project_slug_accepts_well_formed_slug_and_trims_whitespace(self) -> None:
        config = ProjectConfig.model_validate({"project_slug": "  alpha-one  "})
        assert config.project_slug == "alpha-one"

    @pytest.mark.unit
    def test_project_slug_rejects_invalid_characters(self) -> None:
        with pytest.raises(ValidationError, match="Invalid slug"):
            ProjectConfig.model_validate({"project_slug": "Alpha One"})

    @pytest.mark.unit
    def test_project_slug_empty_string_is_normalized_to_none(self) -> None:
        config = ProjectConfig.model_validate({"project_slug": "   "})
        assert config.project_slug is None

    @pytest.mark.unit
    def test_project_env_allow_list_trims_and_deduplicates_names(self) -> None:
        config = ProjectConfig.model_validate({"env_allow_list": [" OPENAI_API_KEY ", "OPENAI_API_KEY", "_CUSTOM"]})
        assert config.env_allow_list == ["OPENAI_API_KEY", "_CUSTOM"]

    @pytest.mark.unit
    def test_project_env_allow_list_rejects_invalid_names(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig.model_validate({"env_allow_list": ["NOT-AN-ENV"]})

    @pytest.mark.unit
    def test_global_env_allow_list_uses_same_validation(self, snapshot: SnapshotAssertion) -> None:
        config = GlobalConfig.model_validate({"env_allow_list": [" OPENAI_API_KEY ", "OPENAI_API_KEY", "_CUSTOM"]})
        assert config.env_allow_list == snapshot

        with pytest.raises(ValidationError):
            GlobalConfig.model_validate({"env_allow_list": ["NOT-AN-ENV"]})


class TestMultiLanguageConfig:
    """ProjectConfig supports multi-language configuration via languages list."""

    @pytest.mark.unit
    def test_accepts_languages_list(self) -> None:
        """ProjectConfig accepts a languages list with multiple entries."""
        config = ProjectConfig.model_validate({"languages": ["python", "typescript"]})
        assert config.languages == ["python", "typescript"]

    @pytest.mark.unit
    def test_languages_defaults_to_empty_list(self) -> None:
        """languages defaults to empty list when absent."""
        config = ProjectConfig.model_validate({})
        assert config.languages == []

    @pytest.mark.unit
    def test_accepts_frontend_root(self) -> None:
        """ProjectConfig accepts a frontend_root string."""
        config = ProjectConfig.model_validate({"frontend_root": "frontend"})
        assert config.frontend_root == "frontend"

    @pytest.mark.unit
    def test_frontend_root_defaults_to_none(self) -> None:
        """frontend_root defaults to None when absent."""
        config = ProjectConfig.model_validate({})
        assert config.frontend_root is None

    @pytest.mark.unit
    def test_legacy_language_field_still_accepted(self) -> None:
        """Backward compat: singular language field is still accepted."""
        config = ProjectConfig.model_validate({"language": "python"})
        assert config.language == "python"

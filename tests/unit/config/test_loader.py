"""Characterization tests for teleclaude.config.loader."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import call, patch

import pytest

from teleclaude.config.loader import load_config, load_project_config, validate_config
from teleclaude.config.schema import GlobalConfig, PersonConfig, ProjectConfig


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


class TestLoadConfig:
    @pytest.mark.unit
    def test_missing_file_returns_default_model(self, tmp_path: Path) -> None:
        result = load_config(tmp_path / "missing.yml", ProjectConfig)
        assert isinstance(result, ProjectConfig)
        assert result.project_name is None
        assert result.jobs == {}

    @pytest.mark.unit
    def test_expands_env_vars_and_warns_about_unknown_keys(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        config_path = tmp_path / "teleclaude.yml"
        _write_yaml(
            config_path,
            """
            project_name: Demo
            git:
              checkout_root: ${WORK_ROOT}/checkouts
            jobs:
              nightly:
                category: system
                when:
                  at: "09:00"
                extra_job: true
            unknown_root: surprise
            """,
        )
        monkeypatch.setenv("WORK_ROOT", "/srv/work")

        with patch("teleclaude.config.loader.logger.warning") as warning:
            result = load_project_config(config_path)

        assert result.git.checkout_root == "/srv/work/checkouts"
        assert warning.call_args_list == [
            call("Unknown keys in %s at %s: %s", "root", config_path, ["unknown_root"]),
            call("Unknown keys in %s at %s: %s", "root.jobs.nightly", config_path, ["extra_job"]),
        ]

    @pytest.mark.unit
    def test_invalid_yaml_raises_value_error(self, tmp_path: Path) -> None:
        config_path = tmp_path / "broken.yml"
        config_path.write_text("project_name: [broken\n", encoding="utf-8")

        with patch("teleclaude.config.loader.logger.error") as error:
            with pytest.raises(ValueError, match="Failed to read config file"):
                load_config(config_path, ProjectConfig)

        error.assert_called_once()


class TestValidateConfig:
    @pytest.mark.unit
    def test_dispatches_to_specific_loader(self) -> None:
        path = Path("/tmp/config.yml")
        project_config = ProjectConfig(project_name="demo")
        global_config = GlobalConfig()
        person_config = PersonConfig()

        with (
            patch("teleclaude.config.loader.load_project_config", return_value=project_config) as load_project,
            patch("teleclaude.config.loader.load_global_config", return_value=global_config) as load_global,
            patch("teleclaude.config.loader.load_person_config", return_value=person_config) as load_person,
        ):
            assert validate_config(path, "project") is project_config
            assert validate_config(path, "global") is global_config
            assert validate_config(path, "person") is person_config

        load_project.assert_called_once_with(path)
        load_global.assert_called_once_with(path)
        load_person.assert_called_once_with(path)

    @pytest.mark.unit
    def test_invalid_level_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid config level: workspace"):
            validate_config(tmp_path / "teleclaude.yml", "workspace")

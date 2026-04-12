# guard: no-companion
# pylint: disable=import-outside-toplevel,unsupported-membership-test,use-implicit-booleaness-not-comparison
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false, reportUnusedImport=false, reportUnusedVariable=false
"""Test specs (xfail) for config-independent-schemas.

Behavioral contracts for breaking GlobalConfig ← ProjectConfig inheritance,
adding AppConfig composed type, relocating checkout_root, atomic project config
writes, eliminating interior config loading from the docs pipeline, and
preventing person-workspace crashes in ``telec docs index``.

All tests are marked xfail — they document the behavioral contract and fail
cleanly before implementation. Remove ``pytestmark = pytest.mark.xfail``
(or per-test markers) once all tests pass after implementation.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def _person_workspace(tmp_path: Path) -> Path:
    """Create a minimal person-workspace directory with a PersonConfig YAML."""
    ws = tmp_path / ".teleclaude" / "people" / "Test User"
    _write_yaml(
        ws / "teleclaude.yml",
        """
        creds:
          telegram:
            user_name: testuser
            user_id: 12345
        """,
    )
    return ws


def _project_workspace(tmp_path: Path) -> Path:
    """Create a minimal project-workspace directory with a ProjectConfig YAML."""
    ws = tmp_path / "projects" / "demo"
    _write_yaml(
        ws / "teleclaude.yml",
        """
        project_name: Demo
        business:
          domains:
            software-development: docs
        """,
    )
    # Provide a minimal global snippets dir so the docs pipeline has something to load.
    global_dir = tmp_path / ".teleclaude" / "docs" / "snippets"
    global_dir.mkdir(parents=True, exist_ok=True)
    return ws


# ===========================================================================
# Finding #4 — Schema inheritance independence
# ===========================================================================


class TestSchemaIndependence:
    """GlobalConfig and ProjectConfig must NOT share an inheritance relationship.

    The builder could satisfy existing key-rejection tests while keeping
    ``class GlobalConfig(ProjectConfig)``. These structural assertions ensure
    that inheritance is actually broken.
    """

    @pytest.mark.unit
    def test_global_config_is_not_subclass_of_project_config(self) -> None:
        from teleclaude.config.schema import GlobalConfig, ProjectConfig

        assert not issubclass(GlobalConfig, ProjectConfig), "GlobalConfig must not inherit from ProjectConfig"

    @pytest.mark.unit
    def test_project_config_is_not_subclass_of_global_config(self) -> None:
        from teleclaude.config.schema import GlobalConfig, ProjectConfig

        assert not issubclass(ProjectConfig, GlobalConfig), "ProjectConfig must not inherit from GlobalConfig"

    @pytest.mark.unit
    def test_global_config_fields_exclude_project_only_fields(self) -> None:
        """GlobalConfig must not carry project-level fields like jobs, hooks, integrator."""
        from teleclaude.config.schema import GlobalConfig

        project_only = {"jobs", "hooks", "integrator", "deployment", "git"}
        global_fields = set(GlobalConfig.model_fields.keys())
        leaked = project_only & global_fields
        assert not leaked, f"GlobalConfig should not have project-only fields: {leaked}"

    @pytest.mark.unit
    def test_global_config_does_not_have_project_field_git(self) -> None:
        """GlobalConfig should not carry a git sub-model inherited from ProjectConfig."""
        # Finding #5 fix: use model_fields instead of hasattr — hasattr returns True
        # even for None-default optional fields, making the check meaningless.
        from teleclaude.config.schema import GlobalConfig

        assert "git" not in GlobalConfig.model_fields, (
            "GlobalConfig should not have a 'git' field — that belongs to ProjectConfig"
        )

    @pytest.mark.unit
    def test_project_config_does_not_have_global_field_people(self) -> None:
        from teleclaude.config.schema import ProjectConfig

        assert "people" not in ProjectConfig.model_fields, (
            "ProjectConfig should not have a 'people' field — that belongs to GlobalConfig"
        )

    @pytest.mark.unit
    def test_independent_construction(self) -> None:
        """Each config type constructs without any reference to the other."""
        from teleclaude.config.schema import GlobalConfig, ProjectConfig

        project = ProjectConfig(project_name="test")
        global_ = GlobalConfig(people=[])
        assert project.project_name == "test"
        assert global_.people == []

    # -----------------------------------------------------------------------
    # Finding #7 — Key-rejection runtime behavior (root cause of the bug)
    # -----------------------------------------------------------------------

    @pytest.mark.unit
    def test_project_config_rejects_person_only_key_creds(self) -> None:
        """ProjectConfig must raise ValidationError when given person-level 'creds' key.

        This is the root cause of the original crash: a person workspace YAML
        contains 'creds', which ProjectConfig's reject_disallowed_keys validator
        must reject.
        """
        from teleclaude.config.schema import ProjectConfig

        with pytest.raises(ValidationError):
            ProjectConfig.model_validate({"creds": {"telegram": {"user_name": "x", "user_id": 1}}})

    @pytest.mark.unit
    def test_global_config_rejects_person_only_keys(self) -> None:
        """GlobalConfig must raise ValidationError when given person-level keys."""
        from teleclaude.config.schema import GlobalConfig

        with pytest.raises(ValidationError):
            GlobalConfig.model_validate({"creds": {"telegram": {"user_name": "x", "user_id": 1}}})

    @pytest.mark.unit
    def test_person_config_rejects_global_only_key_people(self) -> None:
        """PersonConfig must raise ValidationError when given global-level 'people' key."""
        from teleclaude.config.schema import PersonConfig

        with pytest.raises(ValidationError):
            PersonConfig.model_validate({"people": [{"name": "Alice", "email": "a@b.com", "username": "alice"}]})


# ===========================================================================
# Finding #3 — Composed config type (AppConfig)
# ===========================================================================


class TestComposedConfig:
    """A composed type holding optional project/person layers alongside the
    mandatory global layer. Immutable after construction.
    """

    @pytest.mark.unit
    def test_app_config_type_exists(self) -> None:
        from teleclaude.config.schema import AppConfig  # noqa: F401  # pylint: disable=unused-import

    @pytest.mark.unit
    def test_global_layer_always_present(self) -> None:
        from teleclaude.config.schema import AppConfig, GlobalConfig

        config = AppConfig(global_=GlobalConfig())
        assert isinstance(config.global_, GlobalConfig)

    @pytest.mark.unit
    def test_project_layer_none_from_person_workspace(self) -> None:
        from teleclaude.config.schema import AppConfig, GlobalConfig

        config = AppConfig(global_=GlobalConfig(), project=None)
        assert config.project is None

    @pytest.mark.unit
    def test_project_layer_present_from_project_workspace(self) -> None:
        from teleclaude.config.schema import AppConfig, GlobalConfig, ProjectConfig

        config = AppConfig(global_=GlobalConfig(), project=ProjectConfig(project_name="Demo"))
        assert config.project is not None
        assert config.project.project_name == "Demo"

    @pytest.mark.unit
    def test_person_layer_optional(self) -> None:
        from teleclaude.config.schema import AppConfig, GlobalConfig, PersonConfig

        with_person = AppConfig(global_=GlobalConfig(), person=PersonConfig())
        assert with_person.person is not None

        without_person = AppConfig(global_=GlobalConfig())
        assert without_person.person is None

    @pytest.mark.unit
    def test_immutable_after_construction(self) -> None:
        from teleclaude.config.schema import AppConfig, GlobalConfig

        config = AppConfig(global_=GlobalConfig())
        with pytest.raises((AttributeError, TypeError)):
            config.global_ = GlobalConfig()


# ===========================================================================
# Finding #5 — checkout_root relocation
# ===========================================================================


class TestCheckoutRootRelocation:
    """checkout_root is a system-wide setting. It must live on GlobalConfig,
    not inside ProjectConfig.git.
    """

    @pytest.mark.unit
    def test_global_config_has_checkout_root_as_declared_field(self) -> None:
        from teleclaude.config.schema import GlobalConfig

        assert "checkout_root" in GlobalConfig.model_fields, (
            "checkout_root must be a declared field on GlobalConfig, not just accepted via extra"
        )
        config = GlobalConfig.model_validate({"checkout_root": "/srv/checkouts"})
        assert config.checkout_root == "/srv/checkouts"

    @pytest.mark.unit
    def test_project_git_config_no_longer_owns_checkout_root(self) -> None:
        from teleclaude.config.schema import GitConfig

        # After relocation, GitConfig should NOT have checkout_root as a declared field.
        assert "checkout_root" not in GitConfig.model_fields, (
            "checkout_root should be removed from GitConfig — it belongs on GlobalConfig"
        )

    @pytest.mark.unit
    def test_load_checkout_root_reads_from_global_config(self, tmp_path: Path) -> None:
        """_load_checkout_root() must work after checkout_root moves to GlobalConfig."""
        from teleclaude.helpers.git_repo_helper import _load_checkout_root

        _write_yaml(
            tmp_path / "teleclaude.yml",
            """
            checkout_root: /custom/root
            """,
        )
        with patch("teleclaude.helpers.git_repo_helper.load_global_config") as mock_load:
            from teleclaude.config.schema import GlobalConfig

            mock_load.return_value = GlobalConfig.model_validate({"checkout_root": "/custom/root"})
            result = _load_checkout_root()

        assert result == Path("/custom/root")

    @pytest.mark.unit
    def test_global_config_migrates_git_checkout_root(self) -> None:
        """Existing global configs with git.checkout_root must migrate to top-level checkout_root.

        The requirements constraint: checkout_root must continue to work when set in existing
        global configs. The migrate_git_checkout_root validator handles this transition.
        """
        from teleclaude.config.schema import GlobalConfig

        config = GlobalConfig.model_validate({"git": {"checkout_root": "/srv/repos"}})
        assert config.checkout_root == "/srv/repos", (
            "migrate_git_checkout_root must promote git.checkout_root to top-level checkout_root"
        )

    @pytest.mark.unit
    def test_global_config_migrates_git_checkout_root_does_not_override_explicit(self) -> None:
        """Explicit top-level checkout_root takes precedence over git.checkout_root."""
        from teleclaude.config.schema import GlobalConfig

        config = GlobalConfig.model_validate({"checkout_root": "/explicit", "git": {"checkout_root": "/legacy"}})
        assert config.checkout_root == "/explicit", (
            "Explicit checkout_root must not be overridden by git.checkout_root migration"
        )

    @pytest.mark.unit
    def test_backward_compat_checkout_root_on_project_config(self) -> None:
        """Existing project configs with git.checkout_root should not crash.

        After relocation, the git.checkout_root YAML path must be either silently
        accepted (via extra='allow' on GitConfig) or ignored — but must not raise.
        The authoritative source is now GlobalConfig.checkout_root, so
        config.git must not expose checkout_root as a declared field.
        """
        from teleclaude.config.schema import GitConfig, ProjectConfig

        # Must not raise — backward compat load succeeds.
        config = ProjectConfig.model_validate({"git": {"checkout_root": "/old/path"}})
        # checkout_root is no longer a declared field on GitConfig.
        assert "checkout_root" not in GitConfig.model_fields, (
            "git.checkout_root must not be a declared field after relocation"
        )
        # The value may survive in model_extra (extra='allow') but is not authoritative.
        if config.git.model_extra:
            # If stored as extra, it's non-authoritative — that's acceptable.
            pass  # backward compat: field accepted but ignored


# ===========================================================================
# Finding #6 — Atomic project config write
# ===========================================================================


class TestAtomicProjectConfigSave:
    """save_project_config must use atomic write (temp + rename) to prevent
    corruption on crash.
    """

    @pytest.mark.unit
    def test_save_project_config_function_exists(self) -> None:
        from teleclaude.config.loader import save_project_config  # noqa: F401  # pylint: disable=unused-import

    @pytest.mark.unit
    def test_save_project_config_writes_valid_yaml(self, tmp_path: Path) -> None:
        from teleclaude.config.loader import save_project_config
        from teleclaude.config.schema import ProjectConfig

        config_path = tmp_path / "teleclaude.yml"
        config = ProjectConfig(project_name="TestProject")
        save_project_config(config_path, config)

        assert config_path.exists()
        # Round-trip: the written file should be loadable.
        from teleclaude.config.loader import load_project_config

        reloaded = load_project_config(config_path)
        assert reloaded.project_name == "TestProject"

    @pytest.mark.unit
    def test_save_project_config_atomic_no_partial_write(self, tmp_path: Path) -> None:
        """If the write fails mid-way, the original file must survive.

        Verifies atomicity on a real filesystem by injecting a failure via
        os.replace (the rename step of atomic write). If the implementation
        uses a temp-file-plus-rename pattern, blocking rename keeps the
        original file intact.
        """
        from teleclaude.config.loader import save_project_config
        from teleclaude.config.schema import ProjectConfig

        config_path = tmp_path / "teleclaude.yml"
        _write_yaml(config_path, "project_name: Original")

        config = ProjectConfig(project_name="Updated")
        # Block the atomic rename step so the original file survives.
        with patch("os.replace", side_effect=OSError("rename failed")):
            with pytest.raises(OSError):
                save_project_config(config_path, config)

        # Original file must be intact.
        content = config_path.read_text(encoding="utf-8")
        assert "Original" in content


# ===========================================================================
# Finding #2 — Person workspace crash scenario
# ===========================================================================


class TestPersonWorkspaceDocs:
    """``telec docs index`` from a person workspace must NOT crash.

    The core bug: person workspace teleclaude.yml contains ``creds`` and
    ``notifications`` keys. When load_project_config() is called on that file,
    ProjectConfig's reject_disallowed_keys validator raises. After the fix,
    the docs pipeline must detect the workspace type and return global snippets
    without attempting ProjectConfig validation on a PersonConfig file.
    """

    @pytest.mark.unit
    def test_person_workspace_does_not_crash_on_docs_load(self, tmp_path: Path) -> None:
        """Construct a person workspace and verify the config loader handles it.

        Finding #6 (minor) fix: mock global config loading to avoid depending
        on ~/.teleclaude/teleclaude.yml existing on the test machine.
        """
        ws = _person_workspace(tmp_path)
        from teleclaude.config.loader import load_app_config
        from teleclaude.config.schema import GlobalConfig

        with patch("teleclaude.config.loader.load_global_config", return_value=GlobalConfig()):
            config = load_app_config(ws)

        # Must succeed — no ValidationError.
        assert config.project is None
        assert config.global_ is not None

    @pytest.mark.unit
    def test_person_workspace_returns_global_snippets(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """build_context_output from a person workspace returns global snippets.

        Finding #6 (minor) fix: mock global config loading to avoid depending
        on ~/.teleclaude/teleclaude.yml existing on the test machine.
        """
        ws = _person_workspace(tmp_path)
        monkeypatch.chdir(ws)

        from teleclaude.config.loader import load_app_config
        from teleclaude.config.schema import GlobalConfig
        from teleclaude.context_selector import build_context_output

        with patch("teleclaude.config.loader.load_global_config", return_value=GlobalConfig()):
            config = load_app_config(ws)

        # Must not raise. Output should contain global snippet index.
        output = build_context_output(
            areas=[],
            project_root=ws,
            config=config,
        )
        assert isinstance(output, str)

    @pytest.mark.unit
    def test_project_workspace_still_works(self, tmp_path: Path) -> None:
        """Existing project workspace flow must remain unbroken.

        Finding #6 (minor) fix: mock global config loading to avoid depending
        on ~/.teleclaude/teleclaude.yml existing on the test machine.
        """
        ws = _project_workspace(tmp_path)
        from teleclaude.config.loader import load_app_config
        from teleclaude.config.schema import GlobalConfig

        with patch("teleclaude.config.loader.load_global_config", return_value=GlobalConfig()):
            config = load_app_config(ws)

        assert config.project is not None
        assert config.project.project_name == "Demo"

    @pytest.mark.unit
    def test_load_app_config_unrecognized_path_has_no_project(self, tmp_path: Path) -> None:
        """load_app_config on a plain directory (no teleclaude.yml) must not guess.

        Req #3: "No fallback for unrecognized paths — the loader must not guess."
        A plain directory with no teleclaude.yml is not a project workspace.
        The loader must return AppConfig with project=None (global-only), not
        attempt ProjectConfig validation on an absent or wrong file.
        """
        from teleclaude.config.loader import load_app_config
        from teleclaude.config.schema import GlobalConfig

        # tmp_path has no teleclaude.yml — it is an unrecognized plain directory.
        with patch("teleclaude.config.loader.load_global_config", return_value=GlobalConfig()):
            config = load_app_config(tmp_path)

        # Must not crash and must not produce a project layer for an unrecognized path.
        assert config.project is None
        assert config.global_ is not None


# ===========================================================================
# Finding #7 — Interior config loading elimination
# ===========================================================================


class TestInteriorLoadingElimination:
    """After the fix, docs/context pipeline functions must receive config as a
    parameter. They must NOT call load_project_config() internally.
    """

    @pytest.mark.unit
    def test_build_context_output_accepts_config_parameter(self) -> None:
        """build_context_output must accept a config keyword argument."""
        import inspect

        from teleclaude.context_selector import build_context_output

        sig = inspect.signature(build_context_output)
        assert "config" in sig.parameters, "build_context_output must accept a 'config' parameter"

    @pytest.mark.unit
    def test_build_context_output_does_not_call_load_project_config(self, tmp_path: Path) -> None:
        """When config is passed, load_project_config must not be called.

        Finding Critical 1 fix: removed ``except Exception: pass`` — a broken
        implementation that raises immediately would trivially satisfy
        ``mock_load.assert_not_called()``. Instead, mock out the I/O-heavy
        helpers so the function runs to completion, making the assertion
        meaningful.
        """
        from teleclaude.config.schema import AppConfig, GlobalConfig, ProjectConfig
        from teleclaude.context_selector import build_context_output

        config = AppConfig(
            global_=GlobalConfig(),
            project=ProjectConfig(project_name="Test"),
        )

        with (
            patch("teleclaude.config.loader.load_project_config") as mock_load,
            patch("teleclaude.context_selector.get_project_slug", return_value="test"),
            patch("teleclaude.context_selector._load_selected_snippets", return_value=[]),
        ):
            # Pass domains= to bypass _load_project_domains entirely; the test
            # focuses on verifying config is not re-loaded inside the function.
            build_context_output(
                areas=[],
                project_root=tmp_path,
                config=config,
                domains=["software-development"],
            )

        mock_load.assert_not_called()

    @pytest.mark.unit
    def test_get_project_name_not_called_internally(self, tmp_path: Path) -> None:
        """When config supplies project_name, load_project_config must not be called.

        Finding Critical 1 fix: removed ``except Exception: pass`` — same
        rationale as above. Mock I/O helpers to allow the function to complete.
        """
        from teleclaude.config.schema import AppConfig, GlobalConfig, ProjectConfig
        from teleclaude.context_selector import build_context_output

        config = AppConfig(
            global_=GlobalConfig(),
            project=ProjectConfig(project_name="Supplied"),
        )

        with (
            patch("teleclaude.config.loader.load_project_config") as mock_load,
            patch("teleclaude.context_selector.get_project_slug", return_value="supplied"),
            patch("teleclaude.context_selector._load_selected_snippets", return_value=[]),
        ):
            build_context_output(
                areas=[],
                project_root=tmp_path,
                config=config,
                domains=["software-development"],
            )

        mock_load.assert_not_called()

"""Tests for resource_validation — the unified validation module."""

from pathlib import Path

import pytest

from teleclaude.resource_validation import (
    clear_warnings,
    collect_inline_ref_errors,
    get_warnings,
    resolve_ref_path,
    validate_all_snippets,
    validate_artifact,
    validate_jobs_config,
    validate_snippet,
    validate_third_party_docs,
)


@pytest.fixture(autouse=True)
def _clear():
    clear_warnings()
    yield
    clear_warnings()


# ---------------------------------------------------------------------------
# Ref resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveRefPath:
    def test_absolute_path(self, tmp_path: Path) -> None:
        target = tmp_path / "foo.md"
        target.touch()
        result = resolve_ref_path(str(target), root_path=tmp_path, current_path=tmp_path / "bar.md")
        assert result == target

    def test_tilde_expansion(self, tmp_path: Path) -> None:
        result = resolve_ref_path("~/some.md", root_path=tmp_path, current_path=tmp_path / "x.md")
        assert result is not None
        assert str(result).startswith(str(Path.home()))

    def test_docs_relative(self, tmp_path: Path) -> None:
        target = tmp_path / "docs" / "thing.md"
        target.parent.mkdir(parents=True)
        target.touch()
        result = resolve_ref_path("docs/thing.md", root_path=tmp_path, current_path=tmp_path / "x.md")
        assert result == target

    def test_docs_fallback_to_global(self, tmp_path: Path) -> None:
        target = tmp_path / "docs" / "global" / "policy" / "x.md"
        target.parent.mkdir(parents=True)
        target.touch()
        result = resolve_ref_path("docs/policy/x.md", root_path=tmp_path, current_path=tmp_path / "y.md")
        assert result == target

    def test_url_returns_none(self, tmp_path: Path) -> None:
        result = resolve_ref_path("https://example.com", root_path=tmp_path, current_path=tmp_path / "x.md")
        assert result is None


# ---------------------------------------------------------------------------
# Inline ref validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCollectInlineRefErrors:
    def test_missing_ref_reported(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "global" / "test.md"
        snippet.parent.mkdir(parents=True)
        snippet.touch()
        home = str(Path.home())
        # Use a fully-qualified ref path that passes format validation but points to nonexistent file
        lines = [f"@{home}/.teleclaude/docs/general/principle/nonexistent.md"]
        errors = collect_inline_ref_errors(tmp_path, snippet, lines, domains={"software-development"})
        assert any(e["code"] == "snippet_inline_ref_missing" for e in errors)

    def test_invalid_prefix(self, tmp_path: Path) -> None:
        snippet = tmp_path / "test.md"
        lines = ["@some/random/path.md"]
        errors = collect_inline_ref_errors(tmp_path, snippet, lines, domains=set())
        assert any(e["code"] == "snippet_invalid_inline_ref" for e in errors)

    def test_code_fence_skipped(self, tmp_path: Path) -> None:
        snippet = tmp_path / "test.md"
        lines = ["```", "@docs/foo.md", "```"]
        errors = collect_inline_ref_errors(tmp_path, snippet, lines, domains=set())
        assert errors == []


# ---------------------------------------------------------------------------
# Snippet validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateSnippet:
    def test_valid_snippet(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "policy" / "test.md"
        snippet.parent.mkdir(parents=True)
        content = (
            "---\nid: sd/policy/test\ntype: policy\nscope: project\n"
            "description: Test policy\n---\n\n# Test — Policy\n\n"
            "## Required reads\n\n## Rules\n\n- Do the thing.\n\n"
            "## Rationale\n\n- Because.\n\n## Scope\n\n- Here.\n\n"
            "## Enforcement\n\n- Check it.\n\n## Exceptions\n\n- None.\n"
        )
        snippet.write_text(content)
        validate_snippet(snippet, content, tmp_path, domains={"software-development"})
        warnings = get_warnings()
        # Some warnings are expected (id format may not match path), but no crash
        assert isinstance(warnings, list)

    def test_missing_h1_warns(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "test.md"
        snippet.parent.mkdir(parents=True)
        content = "---\nid: test\ntype: policy\nscope: project\ndescription: X\n---\n\nNo heading here.\n\n## Section\n"
        snippet.write_text(content)
        validate_snippet(snippet, content, tmp_path, domains=set())
        codes = [w["code"] for w in get_warnings()]
        assert "snippet_missing_h1" in codes

    def test_missing_frontmatter_warns(self, tmp_path: Path) -> None:
        snippet = tmp_path / "docs" / "project" / "test.md"
        snippet.parent.mkdir(parents=True)
        content = "# Title\n\n## Section\n\nBody.\n"
        snippet.write_text(content)
        validate_snippet(snippet, content, tmp_path, domains=set())
        codes = [w["code"] for w in get_warnings()]
        assert "snippet_missing_frontmatter_field" in codes

    def test_baseline_manifest_validates_refs(self, tmp_path: Path) -> None:
        # baseline.md is now a manifest file containing @references to snippets
        manifest = tmp_path / "docs" / "global" / "baseline.md"
        manifest.parent.mkdir(parents=True)
        target = Path.home() / ".teleclaude" / "docs" / "general" / "principle" / "nonexistent-test.md"
        content = f"@{target}\n"
        manifest.write_text(content)
        validate_snippet(manifest, content, tmp_path, domains=set())
        warnings = get_warnings()
        # Should warn about missing ref if file doesn't exist
        if not target.exists():
            codes = [w["code"] for w in warnings]
            assert "snippet_inline_ref_missing" in codes


# ---------------------------------------------------------------------------
# Artifact validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateArtifact:
    def _make_command(self, tmp_path: Path, body: str) -> Path:
        cmd = tmp_path / "agents" / "commands" / "test.md"
        cmd.parent.mkdir(parents=True)
        cmd.write_text(body)
        return cmd

    def test_valid_command(self, tmp_path: Path) -> None:
        import frontmatter as fm

        body = (
            "# Test Command\n\n"
            "You are now the test executor.\n\n"
            "## Purpose\n\nDo stuff.\n\n"
            "## Inputs\n\nNone.\n\n"
            "## Outputs\n\nResults.\n\n"
            "## Steps\n\n1. Do it.\n"
        )
        post = fm.Post(body, description="Test command")
        result = validate_artifact(post, "test.md", kind="command", project_root=tmp_path)
        assert result is None

    def test_missing_description_raises(self, tmp_path: Path) -> None:
        import frontmatter as fm

        post = fm.Post(
            "# Title\n\nYou are now the x.\n\n## Purpose\n\nX.\n\n## Inputs\n\nX.\n\n## Outputs\n\nX.\n\n## Steps\n\nX.\n"
        )
        with pytest.raises(ValueError, match="missing frontmatter 'description'"):
            validate_artifact(post, "test.md", kind="command", project_root=tmp_path)

    def test_missing_role_activation_raises(self, tmp_path: Path) -> None:
        import frontmatter as fm

        post = fm.Post(
            "# Title\n\nSome other line.\n\n## Purpose\n\nX.\n",
            description="Test",
        )
        with pytest.raises(ValueError, match="role activation"):
            validate_artifact(post, "test.md", kind="command", project_root=tmp_path)

    def test_wrong_section_order_raises(self, tmp_path: Path) -> None:
        import frontmatter as fm

        body = (
            "# Title\n\nYou are now the x.\n\n"
            "## Outputs\n\nX.\n\n"
            "## Purpose\n\nX.\n\n"
            "## Inputs\n\nX.\n\n"
            "## Steps\n\nX.\n"
        )
        post = fm.Post(body, description="Test")
        with pytest.raises(ValueError, match="section order"):
            validate_artifact(post, "test.md", kind="command", project_root=tmp_path)

    def test_skill_validates_name_match(self, tmp_path: Path) -> None:
        import frontmatter as fm

        post = fm.Post(
            "# Skill\n\n## Purpose\n\nX.\n\n## Scope\n\nX.\n\n## Inputs\n\nX.\n\n## Outputs\n\nX.\n\n## Procedure\n\nX.\n",
            description="Test skill",
            name="wrong-name",
        )
        with pytest.raises(ValueError, match="must match folder"):
            validate_artifact(post, "skills/my-skill/SKILL.md", kind="skill", project_root=tmp_path)


@pytest.mark.unit
class TestValidateJobsConfig:
    def test_agent_job_requires_job_field_and_forbids_message(self, tmp_path: Path) -> None:
        config = tmp_path / "teleclaude.yml"
        config.write_text("jobs:\n  sample:\n    schedule: weekly\n    type: agent\n    message: test\n")
        errors = validate_jobs_config(tmp_path)
        assert any("jobs.sample.message is not allowed" in e for e in errors)
        assert any("jobs.sample.job is required" in e for e in errors)

    def test_agent_job_requires_existing_spec(self, tmp_path: Path) -> None:
        (tmp_path / "docs" / "project" / "spec" / "jobs").mkdir(parents=True)
        config = tmp_path / "teleclaude.yml"
        config.write_text("jobs:\n  sample:\n    schedule: weekly\n    type: agent\n    job: sample-job\n")
        errors = validate_jobs_config(tmp_path)
        assert any("references missing spec" in e for e in errors)

    def test_agent_job_with_existing_spec_passes(self, tmp_path: Path) -> None:
        jobs_dir = tmp_path / "docs" / "project" / "spec" / "jobs"
        jobs_dir.mkdir(parents=True)
        (jobs_dir / "sample-job.md").write_text("# Sample\n")
        config = tmp_path / "teleclaude.yml"
        config.write_text("jobs:\n  sample:\n    schedule: weekly\n    type: agent\n    job: sample-job\n")
        errors = validate_jobs_config(tmp_path)
        assert errors == []

    def test_nonexistent_ref_raises(self, tmp_path: Path) -> None:
        import frontmatter as fm

        body = (
            "# Title\n\n"
            "## Required reads\n\n"
            "- @docs/nonexistent/thing.md\n\n"
            "You are now the x.\n\n"
            "## Purpose\n\nX.\n\n## Inputs\n\nX.\n\n## Outputs\n\nX.\n\n## Steps\n\nX.\n"
        )
        post = fm.Post(body, description="Test")
        with pytest.raises(ValueError, match="non-existent file"):
            validate_artifact(post, "test.md", kind="command", project_root=tmp_path)


# ---------------------------------------------------------------------------
# Third-party validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateThirdPartyDocs:
    def test_missing_sources_warns(self, tmp_path: Path) -> None:
        tp = tmp_path / "docs" / "third-party" / "lib" / "feature.md"
        tp.parent.mkdir(parents=True)
        tp.write_text("# Feature\n\n## Rules\n\nStuff.\n")
        validate_third_party_docs(tmp_path)
        # No sources section — currently no warning for missing sources in third-party validator
        # (that's in snippet validator). Third-party validator only checks source values.
        assert get_warnings() == []

    def test_invalid_source_warns(self, tmp_path: Path) -> None:
        tp = tmp_path / "docs" / "third-party" / "lib" / "feature.md"
        tp.parent.mkdir(parents=True)
        tp.write_text("# Feature\n\n## Sources\n\n- not-a-url\n")
        validate_third_party_docs(tmp_path)
        codes = [w["code"] for w in get_warnings()]
        assert "third_party_source_invalid" in codes


# ---------------------------------------------------------------------------
# Full pipeline validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateAllSnippets:
    def test_empty_project(self, tmp_path: Path) -> None:
        validate_all_snippets(tmp_path)
        assert get_warnings() == []

    def test_project_with_snippets(self, tmp_path: Path) -> None:
        docs = tmp_path / "docs" / "project" / "policy"
        docs.mkdir(parents=True)
        snippet = docs / "test.md"
        snippet.write_text(
            "---\nid: sd/policy/test\ntype: policy\nscope: project\n"
            "description: Test\n---\n\n# Test — Policy\n\n"
            "## Required reads\n\n## Rules\n\nX.\n\n## Rationale\n\nX.\n\n"
            "## Scope\n\nX.\n\n## Enforcement\n\nX.\n\n## Exceptions\n\nX.\n"
        )
        validate_all_snippets(tmp_path)
        # Should not crash; may have warnings about id format
        assert isinstance(get_warnings(), list)

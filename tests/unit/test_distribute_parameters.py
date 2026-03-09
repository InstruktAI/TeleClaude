"""Tests for command parameter preamble generation in distribute.py.

Commands can declare named parameters in frontmatter. At compile time,
distribute.py injects a preamble mapping parameter names to positional
arguments derived from list order. The body content stays identical
across all runtimes.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from frontmatter import Post


def _load_distribute_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "distribute.py"
    spec = importlib.util.spec_from_file_location("distribute", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["distribute"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def distribute():
    return _load_distribute_module()


# ---------------------------------------------------------------------------
# Preamble helper
# ---------------------------------------------------------------------------


class TestBuildParameterPreamble:
    """Tests for the _build_parameter_preamble helper."""

    def test_single_required_parameter(self, distribute):
        params = [{"name": "slug", "required": True}]
        result = distribute._build_parameter_preamble(params)
        assert "<!-- $slug = argument at position 0 (required) -->" in result

    def test_multiple_parameters(self, distribute):
        params = [
            {"name": "slug", "required": True},
            {"name": "mode"},
        ]
        result = distribute._build_parameter_preamble(params)
        assert "<!-- $slug = argument at position 0 (required) -->" in result
        assert "<!-- $mode = argument at position 1 -->" in result

    def test_parameter_with_default(self, distribute):
        params = [
            {"name": "slug", "required": True},
            {"name": "mode", "default": "standard"},
        ]
        result = distribute._build_parameter_preamble(params)
        assert '<!-- $mode = argument at position 1 (default: "standard") -->' in result

    def test_empty_parameters_returns_empty(self, distribute):
        result = distribute._build_parameter_preamble([])
        assert result == ""

    def test_position_derived_from_list_order(self, distribute):
        params = [
            {"name": "slug", "required": True},
            {"name": "mode"},
            {"name": "output"},
        ]
        result = distribute._build_parameter_preamble(params)
        lines = [line for line in result.splitlines() if line.strip()]
        assert "position 0" in lines[0]
        assert "position 1" in lines[1]
        assert "position 2" in lines[2]

    def test_no_args_variable_in_preamble(self, distribute):
        """Preamble must NOT reference $ARGUMENTS or {{args}} to avoid empty-string issues."""
        params = [{"name": "slug", "required": True}]
        result = distribute._build_parameter_preamble(params)
        assert "$ARGUMENTS" not in result
        assert "{{args}}" not in result


# ---------------------------------------------------------------------------
# Claude output (dump_frontmatter path)
# ---------------------------------------------------------------------------


class TestClaudeParameterInjection:
    """Parameters preamble injected into Claude command output."""

    def test_preamble_injected_before_body(self, distribute):
        post = Post(
            "# Next Build\n\nBuild `$slug` in `$mode` mode.\n",
            description="Build implementation",
            parameters=[
                {"name": "slug", "required": True},
                {"name": "mode", "default": "standard"},
            ],
        )
        result = distribute.dump_frontmatter(post)
        # Preamble appears before the body content
        preamble_pos = result.find("<!-- $slug")
        body_pos = result.find("# Next Build")
        assert preamble_pos != -1, "Preamble must be present"
        assert body_pos != -1, "Body must be present"
        assert preamble_pos < body_pos, "Preamble must appear before body"

    def test_parameters_stripped_from_frontmatter(self, distribute):
        post = Post(
            "# Test\n\nBody.\n",
            description="Test",
            parameters=[{"name": "slug", "required": True}],
        )
        result = distribute.dump_frontmatter(post)
        assert "parameters:" not in result.split("---")[1]

    def test_body_content_unchanged(self, distribute):
        body = "# Next Build\n\nBuild `$slug` in `$mode` mode.\n"
        post = Post(
            body,
            description="Build implementation",
            parameters=[
                {"name": "slug", "required": True},
                {"name": "mode", "default": "standard"},
            ],
        )
        result = distribute.dump_frontmatter(post)
        assert "Build `$slug` in `$mode` mode." in result


# ---------------------------------------------------------------------------
# Codex output
# ---------------------------------------------------------------------------


class TestCodexParameterInjection:
    """Parameters preamble injected into Codex command output."""

    def test_preamble_injected(self, distribute):
        post = Post(
            "# Test\n\nUse `$slug`.\n",
            description="Test",
            parameters=[{"name": "slug", "required": True}],
        )
        result = distribute.transform_to_codex(post)
        assert "<!-- $slug = argument at position 0 (required) -->" in result

    def test_parameters_stripped_from_frontmatter(self, distribute):
        post = Post(
            "# Test\n\nBody.\n",
            description="Test",
            parameters=[{"name": "slug", "required": True}],
        )
        result = distribute.transform_to_codex(post)
        assert "parameters:" not in result.split("---")[1]

    def test_body_identical_to_claude(self, distribute):
        body = "# Build\n\nBuild `$slug` in `$mode` mode.\n"
        params = [
            {"name": "slug", "required": True},
            {"name": "mode", "default": "standard"},
        ]
        claude_post = Post(body, description="Build", parameters=params)
        codex_post = Post(body, description="Build", parameters=params)

        claude_result = distribute.dump_frontmatter(claude_post)
        codex_result = distribute.transform_to_codex(codex_post)

        # Extract body after frontmatter for both
        claude_body = claude_result.split("---", 2)[-1].strip()
        codex_body = codex_result.split("---", 2)[-1].strip()

        # Preamble + body must be identical
        assert claude_body == codex_body


# ---------------------------------------------------------------------------
# Gemini output
# ---------------------------------------------------------------------------


class TestGeminiParameterInjection:
    """Parameters preamble injected into Gemini TOML output."""

    def test_preamble_injected(self, distribute):
        post = Post(
            "# Test\n\nUse `$slug`.\n",
            description="Test",
            parameters=[{"name": "slug", "required": True}],
        )
        result = distribute.transform_to_gemini(post)
        assert "<!-- $slug = argument at position 0 (required) -->" in result

    def test_parameters_not_in_toml_metadata(self, distribute):
        post = Post(
            "# Test\n\nBody.\n",
            description="Test",
            parameters=[{"name": "slug", "required": True}],
        )
        result = distribute.transform_to_gemini(post)
        # TOML header should not contain parameters
        toml_header = result.split("prompt = '''")[0]
        assert "parameters" not in toml_header

    def test_preamble_identical_to_claude(self, distribute):
        """Preamble content must be identical across all runtimes."""
        params = [
            {"name": "slug", "required": True},
            {"name": "mode", "default": "standard"},
        ]
        preamble = distribute._build_parameter_preamble(params)

        post = Post("# Test\n\nUse `$slug`.\n", description="Test", parameters=params)

        claude_result = distribute.dump_frontmatter(post)
        gemini_result = distribute.transform_to_gemini(post)

        assert preamble in claude_result
        assert preamble in gemini_result


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestParameterBackwardCompat:
    """Commands without parameters must work exactly as before."""

    def test_no_preamble_without_parameters_claude(self, distribute):
        post = Post("# Test\n\nUse $ARGUMENTS.\n", description="Test")
        result = distribute.dump_frontmatter(post)
        assert "<!--" not in result

    def test_no_preamble_without_parameters_codex(self, distribute):
        post = Post("# Test\n\nUse $ARGUMENTS.\n", description="Test")
        result = distribute.transform_to_codex(post)
        assert "<!--" not in result

    def test_no_preamble_without_parameters_gemini(self, distribute):
        post = Post("# Test\n\nUse $ARGUMENTS.\n", description="Test")
        result = distribute.transform_to_gemini(post)
        assert "<!--" not in result

    def test_arguments_still_transformed_for_gemini(self, distribute):
        post = Post("# Test\n\nUse $ARGUMENTS.\n", description="Test")
        result = distribute.transform_to_gemini(post)
        assert "{{args}}" in result
        assert "$ARGUMENTS" not in result


# ---------------------------------------------------------------------------
# Frontmatter filtering
# ---------------------------------------------------------------------------


class TestParameterFrontmatterFiltering:
    """Parameters must be stripped from all emitted frontmatter."""

    def test_filter_strips_parameters_claude(self, distribute):
        metadata = {"description": "Test", "parameters": [{"name": "slug"}]}
        filtered = distribute._filter_frontmatter(metadata, "claude")
        assert "parameters" not in filtered

    def test_filter_strips_parameters_codex(self, distribute):
        metadata = {"description": "Test", "parameters": [{"name": "slug"}]}
        filtered = distribute._filter_frontmatter(metadata, "codex")
        assert "parameters" not in filtered

    def test_filter_strips_parameters_gemini(self, distribute):
        metadata = {"description": "Test", "parameters": [{"name": "slug"}]}
        filtered = distribute._filter_frontmatter(metadata, "gemini")
        assert "parameters" not in filtered

    def test_filter_preserves_other_fields(self, distribute):
        metadata = {
            "description": "Test",
            "argument-hint": "<slug>",
            "parameters": [{"name": "slug"}],
        }
        filtered = distribute._filter_frontmatter(metadata, "claude")
        assert filtered["description"] == "Test"
        assert filtered["argument-hint"] == "<slug>"
        assert "parameters" not in filtered


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestParameterValidation:
    """Validation of the parameters frontmatter field."""

    def test_valid_parameters_accepted(self, distribute):
        post = Post(
            "# Test\n\nYou are now the Builder.\n\n"
            "## Purpose\n\nBuild.\n\n"
            "## Inputs\n\n- Slug: `$slug`\n\n"
            "## Outputs\n\nNone.\n\n"
            "## Steps\n\n1. Build.\n",
            description="Test",
            parameters=[
                {"name": "slug", "required": True},
                {"name": "mode", "default": "standard"},
            ],
        )
        # Should not raise
        from teleclaude.resource_validation import validate_artifact_frontmatter

        validate_artifact_frontmatter(post, "test.md", kind="command")

    def test_parameters_not_a_list_rejected(self, distribute):
        post = Post("# Test\n\nBody.\n", description="Test", parameters="invalid")
        from teleclaude.resource_validation import validate_artifact_frontmatter

        with pytest.raises(ValueError, match="parameters.*list"):
            validate_artifact_frontmatter(post, "test.md", kind="command")

    def test_parameter_missing_name_rejected(self, distribute):
        post = Post("# Test\n\nBody.\n", description="Test", parameters=[{"required": True}])
        from teleclaude.resource_validation import validate_artifact_frontmatter

        with pytest.raises(ValueError, match="name"):
            validate_artifact_frontmatter(post, "test.md", kind="command")

    def test_duplicate_names_rejected(self, distribute):
        post = Post(
            "# Test\n\nBody.\n",
            description="Test",
            parameters=[
                {"name": "slug"},
                {"name": "slug"},
            ],
        )
        from teleclaude.resource_validation import validate_artifact_frontmatter

        with pytest.raises(ValueError, match="duplicate.*name"):
            validate_artifact_frontmatter(post, "test.md", kind="command")

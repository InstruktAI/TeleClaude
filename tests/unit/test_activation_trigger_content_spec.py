# guard: no-companion
"""Test spec for R5/R6/R7/R8/R9: content, annotations, and cleanup.

R5: The 6 procedure references are removed from baseline-progressive.md.
R6: The 11 target procedures have ``activation_trigger`` in their frontmatter
    with the required trigger text.
R7: The skill-authoring procedure is updated to reflect that activation_trigger
    on procedures is the primary capability discovery mechanism.
R8: The skill-creator skill directory is deleted.
R9: The snippet-authoring-schema spec documents ``activation_trigger`` as an
    optional field for procedure snippets.

These tests document the behavioral contract that the implementation must
preserve.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GLOBAL_DOCS = _REPO_ROOT / "docs" / "global"
_BASELINE_PROGRESSIVE = _GLOBAL_DOCS / "baseline-progressive.md"
_SKILL_CREATOR_DIR = _REPO_ROOT / "agents" / "skills" / "skill-creator"
_SNIPPET_AUTHORING_SCHEMA = _GLOBAL_DOCS / "general" / "spec" / "snippet-authoring-schema.md"
_SKILL_AUTHORING_PROCEDURE = _GLOBAL_DOCS / "general" / "procedure" / "skill-authoring.md"


# ---------------------------------------------------------------------------
# R5: Baseline progressive cleanup
# ---------------------------------------------------------------------------

_REMOVED_PROCEDURE_IDS = [
    "general/procedure/agent-artifact-authoring",
    "general/procedure/doc-snippet-authoring",
    "general/procedure/peer-discussion",
    "general/procedure/memory-management",
    "general/procedure/brainstorming",
    "software-development/procedure/debugging",
]


class TestBaselineProgressiveCleanup:
    """R5: 6 procedure references removed from baseline-progressive.md."""

    @pytest.mark.parametrize("procedure_id", _REMOVED_PROCEDURE_IDS)
    def test_procedure_removed_from_baseline_progressive(self, procedure_id: str) -> None:
        """Each of the 6 procedures must not be referenced in baseline-progressive.md.

        These procedures will be surfaced via the activatable procedures section
        instead.  Keeping them in both locations would duplicate them.
        """
        content = _BASELINE_PROGRESSIVE.read_text(encoding="utf-8")
        assert procedure_id not in content, (
            f"baseline-progressive.md must not contain '{procedure_id}' after R5 cleanup"
        )


# ---------------------------------------------------------------------------
# R6: Procedure activation annotations
# ---------------------------------------------------------------------------

_PROCEDURE_TRIGGERS: list[tuple[str, str]] = [
    (
        "general/procedure/brainstorming",
        "Use when the user wants to refine an idea before implementation",
    ),
    (
        "software-development/procedure/debugging",
        "Use when you encounter a bug, test failure, or unexpected behavior",
    ),
    (
        "general/procedure/peer-discussion",
        "Use when a complex topic would benefit from two agents covering it together",
    ),
    (
        "general/procedure/youtube-research",
        "Use when user needs YouTube video search, channel research, or transcripts",
    ),
    (
        "general/procedure/git-repo-ingestion",
        "Use when you need to analyze an external Git repository",
    ),
    (
        "general/procedure/firecrawl-web-scraping",
        "Use when web search fails and you need to scrape JavaScript-rendered content",
    ),
    (
        "general/procedure/memory-management",
        "Use when you encounter a durable user preference, friction, or relationship context",
    ),
    (
        "software-development/procedure/research/tech-stack-documentation",
        "Use when researching a library or framework not yet in consolidated docs",
    ),
    (
        "general/procedure/doc-snippet-authoring",
        "Use when creating or updating documentation snippets",
    ),
    (
        "general/procedure/agent-artifact-authoring",
        "Use when creating or updating agent artifacts",
    ),
    (
        "software-development/procedure/research/third-party-research",
        "Use when researching third-party documentation and consolidating findings",
    ),
]


def _procedure_file(snippet_id: str) -> Path:
    """Resolve a snippet ID to its file path under the repo docs/global/ tree."""
    parts = snippet_id.split("/")
    return _GLOBAL_DOCS / Path(*parts).with_suffix(".md")


class TestProcedureActivationAnnotations:
    """R6: 11 procedures have activation_trigger in their frontmatter."""

    @pytest.mark.parametrize("snippet_id,expected_trigger", _PROCEDURE_TRIGGERS)
    def test_procedure_has_activation_trigger(self, snippet_id: str, expected_trigger: str) -> None:
        """The procedure file must have activation_trigger in its frontmatter.

        The value must exactly match the required trigger text from requirements R6.
        """
        proc_path = _procedure_file(snippet_id)
        assert proc_path.exists(), f"Procedure file not found: {proc_path}"

        text = proc_path.read_text(encoding="utf-8")

        # Extract frontmatter block
        if not text.lstrip().startswith("---"):
            pytest.fail(f"{snippet_id}: file has no frontmatter")

        lines = text.splitlines()
        fm_lines: list[str] = []
        in_fm = False
        for line in lines:
            if line.strip() == "---":
                if not in_fm:
                    in_fm = True
                    continue
                break
            if in_fm:
                fm_lines.append(line)

        fm = yaml.safe_load("\n".join(fm_lines)) or {}
        assert "activation_trigger" in fm, f"{snippet_id}: frontmatter must contain 'activation_trigger' field"
        assert fm["activation_trigger"] == expected_trigger, (
            f"{snippet_id}: activation_trigger value mismatch.\n"
            f"  Expected: {expected_trigger!r}\n"
            f"  Got:      {fm['activation_trigger']!r}"
        )


# ---------------------------------------------------------------------------
# R7: Skill-authoring procedure update
# ---------------------------------------------------------------------------


class TestSkillAuthoringProcedureUpdate:
    """R7: skill-authoring procedure reflects activation_trigger as primary discovery mechanism."""

    def test_procedure_mentions_activation_trigger(self) -> None:
        """The procedure body must mention activation_trigger.

        Post-R7, the procedure must explain that procedural capabilities use
        activation_trigger for progressive disclosure rather than baseline index.
        """
        content = _SKILL_AUTHORING_PROCEDURE.read_text(encoding="utf-8")
        assert (
            "add an `activation_trigger` to the procedure frontmatter so it is progressively disclosed in AGENTS.md"
        ) in content, (
            "skill-authoring procedure gate must direct scriptless capabilities to procedure "
            "frontmatter with activation_trigger-based disclosure"
        )

    def test_procedure_explains_procedural_knowledge_uses_activation_trigger(self) -> None:
        """The procedure must explicitly distinguish procedural knowledge from skills.

        The gate step must state that procedural capabilities use activation_trigger
        for progressive disclosure — not baseline index inclusion or skill creation.
        """
        content = _SKILL_AUTHORING_PROCEDURE.read_text(encoding="utf-8")
        assert (
            "Procedural capabilities use `activation_trigger` for progressive disclosure; "
            "skill creation is gated exclusively on carrying executable scripts."
        ) in content, (
            "skill-authoring procedure must explain that procedural capabilities "
            "use activation_trigger for progressive disclosure"
        )


# ---------------------------------------------------------------------------
# R8: Skill-creator skill deletion
# ---------------------------------------------------------------------------


class TestSkillCreatorDeletion:
    """R8: The skill-creator skill directory must be deleted."""

    def test_skill_creator_directory_does_not_exist(self) -> None:
        """The agents/skills/skill-creator/ directory must not exist after R8.

        Its function is superseded by the activation_trigger mechanism on the
        agent-artifact-authoring procedure and the skill-authoring procedure gate.
        """
        assert not _SKILL_CREATOR_DIR.exists(), (
            f"agents/skills/skill-creator/ must be deleted as part of R8, "
            f"but the directory still exists at {_SKILL_CREATOR_DIR}"
        )


# ---------------------------------------------------------------------------
# R9: Schema documentation
# ---------------------------------------------------------------------------


class TestSchemaDocumentation:
    """R9: snippet-authoring-schema spec documents activation_trigger."""

    def test_schema_documents_activation_trigger_field(self) -> None:
        """The schema spec must document the activation_trigger field.

        Post-R9, the field must appear in the spec with its type constraint
        and scope (procedure snippets only).
        """
        content = _SNIPPET_AUTHORING_SCHEMA.read_text(encoding="utf-8")
        assert "- `activation_trigger` — procedures only." in content, (
            "snippet-authoring-schema must document activation_trigger in the optional frontmatter field list"
        )

    def test_schema_documents_procedures_only_constraint(self) -> None:
        """The schema spec must state that activation_trigger is for procedures only.

        Validation rejects the field on all other snippet types.  The schema
        must document this constraint explicitly.
        """
        content = _SNIPPET_AUTHORING_SCHEMA.read_text(encoding="utf-8")
        assert "Validation rejects this field on non-procedure snippet types." in content, (
            "snippet-authoring-schema must document that activation_trigger is only valid on procedure snippets"
        )

    def test_schema_documents_non_empty_string_constraint(self) -> None:
        """The schema spec must document that activation_trigger must be a non-empty string.

        The value constraint (non-empty string) must be stated in the spec
        so documentation consumers know what constitutes a valid value.
        """
        content = _SNIPPET_AUTHORING_SCHEMA.read_text(encoding="utf-8")
        assert "A non-empty string describing when to activate the procedure." in content, (
            "snippet-authoring-schema must document that activation_trigger must be a non-empty string"
        )

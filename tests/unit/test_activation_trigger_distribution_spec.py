# guard: no-companion
# pyright: reportAttributeAccessIssue=false, reportCallIssue=false, reportPrivateUsage=false

"""Test spec for R3/R4: Activatable Procedures distribution.

R3: The distribution pipeline renders a dedicated "Activatable Procedures"
section in generated AGENTS.md for procedures with ``activation_trigger``.
The section appears after the baseline index, entries are sorted, and a
brief header tells agents to load the full procedure via ``telec docs get``.

R4: Procedures with ``activation_trigger`` are automatically excluded from
the progressive baseline index to prevent duplication.

These tests document the behavioral contract that the implementation must
preserve.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DISTRIBUTE_SCRIPT = _REPO_ROOT / "scripts" / "distribute.py"


def _import_distribute():
    """Import scripts/distribute.py as a module."""
    spec = importlib.util.spec_from_file_location("distribute", _DISTRIBUTE_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Temporarily add repo root to sys.path for the script's internal imports
    original_path = sys.path[:]
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = original_path
    return mod


def _make_procedure_snippet(
    project_root: Path,
    *,
    snippet_id: str,
    description: str,
    activation_trigger: str | None = None,
) -> Path:
    """Create a minimal procedure snippet file with frontmatter."""
    parts = snippet_id.split("/")
    domain = parts[0]
    rel_path = "/".join(parts[1:])
    snippet_path = project_root / "docs" / "global" / domain / f"{rel_path}.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)

    fm_lines = [
        "---",
        f"id: {snippet_id}",
        "type: procedure",
        f"domain: {domain}",
        f"description: {description}",
    ]
    if activation_trigger is not None:
        fm_lines.append(f'activation_trigger: "{activation_trigger}"')
    fm_lines.append("---")

    body = dedent(f"""\
        # {parts[-1].replace("-", " ").title()} — Procedure

        ## Required reads

        ## Rules

        Procedure content.
    """)

    snippet_path.write_text("\n".join(fm_lines) + "\n" + body, encoding="utf-8")
    return snippet_path


def _make_baseline_progressive(project_root: Path, refs: list[str]) -> Path:
    """Create a baseline-progressive.md referencing the given doc paths."""
    baseline_dir = project_root / "docs" / "global"
    baseline_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = baseline_dir / "baseline-progressive.md"
    content = "\n".join(f"@{ref}" for ref in refs)
    baseline_path.write_text(content + "\n", encoding="utf-8")
    return baseline_path


class TestBaselineExclusion:
    """R4: Procedures with ``activation_trigger`` are excluded from the progressive baseline index."""

    def test_procedure_with_activation_trigger_excluded_from_baseline(self, tmp_path: Path) -> None:
        """A procedure with ``activation_trigger`` must not appear in the baseline index output."""
        distribute = _import_distribute()

        # Procedure WITHOUT activation_trigger — should appear in baseline
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/brainstorming",
            description="Refine ideas into designs",
        )
        # Procedure WITH activation_trigger — should be EXCLUDED from baseline
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/peer-discussion",
            description="Two agents discuss a topic",
            activation_trigger="Use when a complex topic needs two agents",
        )

        baseline_path = _make_baseline_progressive(
            tmp_path,
            [
                "docs/global/general/procedure/brainstorming.md",
                "docs/global/general/procedure/peer-discussion.md",
            ],
        )

        output = distribute._render_progressive_index(
            baseline_path,
            project_root=tmp_path,
            warn_only=False,
        )

        assert "general/procedure/brainstorming" in output, "Non-trigger procedure should remain in baseline"
        assert "general/procedure/peer-discussion" not in output, (
            "Procedure with activation_trigger should be excluded from baseline"
        )

    def test_all_trigger_procedures_excluded_leaves_remaining_entries(self, tmp_path: Path) -> None:
        """When some procedures have triggers and others don't, baseline contains only the non-trigger ones."""
        distribute = _import_distribute()

        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/regular-a",
            description="Regular procedure A",
        )
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/regular-b",
            description="Regular procedure B",
        )
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/triggered",
            description="Triggered procedure",
            activation_trigger="Use when triggered",
        )

        baseline_path = _make_baseline_progressive(
            tmp_path,
            [
                "docs/global/general/procedure/regular-a.md",
                "docs/global/general/procedure/regular-b.md",
                "docs/global/general/procedure/triggered.md",
            ],
        )

        output = distribute._render_progressive_index(
            baseline_path,
            project_root=tmp_path,
            warn_only=False,
        )

        assert "general/procedure/regular-a" in output
        assert "general/procedure/regular-b" in output
        assert "general/procedure/triggered" not in output


class TestActivatableProceduresSection:
    """R3: AGENTS.md includes an "Activatable Procedures" section."""

    def test_activatable_section_rendered_for_trigger_procedures(self, tmp_path: Path) -> None:
        """Procedures with ``activation_trigger`` appear in a dedicated section."""
        distribute = _import_distribute()

        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/peer-discussion",
            description="Two agents discuss a topic",
            activation_trigger="Use when a complex topic needs two agents",
        )

        _make_baseline_progressive(
            tmp_path,
            ["docs/global/general/procedure/peer-discussion.md"],
        )

        # Test the combined AGENTS.md output through _write_project_agents.
        master_path = tmp_path / "AGENTS.master.md"
        master_path.write_text(
            dedent("""\
                # Test Project

                @docs/global/baseline-progressive.md
            """),
            encoding="utf-8",
        )

        distribute._write_project_agents(master_path, project_root=tmp_path, warn_only=False)

        agents_path = tmp_path / "AGENTS.md"
        agents_content = agents_path.read_text(encoding="utf-8")

        assert "Activatable Procedures" in agents_content, (
            "Generated AGENTS.md must contain an 'Activatable Procedures' section"
        )

    def test_activatable_section_appears_after_baseline_index(self, tmp_path: Path) -> None:
        """The activatable section must appear after the baseline index block."""
        distribute = _import_distribute()

        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/regular",
            description="Regular procedure",
        )
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/triggered",
            description="Triggered procedure",
            activation_trigger="Use when triggered",
        )

        _make_baseline_progressive(
            tmp_path,
            [
                "docs/global/general/procedure/regular.md",
                "docs/global/general/procedure/triggered.md",
            ],
        )

        master_path = tmp_path / "AGENTS.master.md"
        master_path.write_text(
            dedent("""\
                # Test Project

                @docs/global/baseline-progressive.md
            """),
            encoding="utf-8",
        )

        distribute._write_project_agents(master_path, project_root=tmp_path, warn_only=False)

        agents_content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

        baseline_pos = agents_content.find("Baseline index")
        activatable_pos = agents_content.find("Activatable Procedures")

        assert baseline_pos >= 0, "Baseline index section must be present"
        assert activatable_pos >= 0, "Activatable Procedures section must be present"
        assert activatable_pos > baseline_pos, "Activatable Procedures must appear after the baseline index"

    def test_activatable_entries_are_sorted(self, tmp_path: Path) -> None:
        """Entries in the activatable section must be deterministically sorted."""
        distribute = _import_distribute()

        # Create procedures in non-alphabetical order
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/zebra-proc",
            description="Zebra procedure",
            activation_trigger="Use for zebras",
        )
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/alpha-proc",
            description="Alpha procedure",
            activation_trigger="Use for alphas",
        )
        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/middle-proc",
            description="Middle procedure",
            activation_trigger="Use for middles",
        )

        _make_baseline_progressive(
            tmp_path,
            [
                "docs/global/general/procedure/zebra-proc.md",
                "docs/global/general/procedure/alpha-proc.md",
                "docs/global/general/procedure/middle-proc.md",
            ],
        )

        master_path = tmp_path / "AGENTS.master.md"
        master_path.write_text(
            dedent("""\
                # Test Project

                @docs/global/baseline-progressive.md
            """),
            encoding="utf-8",
        )

        distribute._write_project_agents(master_path, project_root=tmp_path, warn_only=False)

        agents_content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

        alpha_pos = agents_content.find("general/procedure/alpha-proc")
        middle_pos = agents_content.find("general/procedure/middle-proc")
        zebra_pos = agents_content.find("general/procedure/zebra-proc")

        assert alpha_pos >= 0 and middle_pos >= 0 and zebra_pos >= 0, (
            "All three activatable procedures must appear in the output"
        )
        assert alpha_pos < middle_pos < zebra_pos, "Activatable entries must be sorted alphabetically by snippet ID"

    def test_activatable_section_includes_docs_get_header(self, tmp_path: Path) -> None:
        """The section header must instruct agents to load full procedures via ``telec docs get``."""
        distribute = _import_distribute()

        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/test-proc",
            description="Test procedure",
            activation_trigger="Use for testing",
        )

        _make_baseline_progressive(
            tmp_path,
            ["docs/global/general/procedure/test-proc.md"],
        )

        master_path = tmp_path / "AGENTS.master.md"
        master_path.write_text(
            dedent("""\
                # Test Project

                @docs/global/baseline-progressive.md
            """),
            encoding="utf-8",
        )

        distribute._write_project_agents(master_path, project_root=tmp_path, warn_only=False)

        agents_content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

        assert "telec docs get" in agents_content, (
            "Activatable section must include instruction to load via telec docs get"
        )

    def test_activatable_entry_shows_trigger_text(self, tmp_path: Path) -> None:
        """Each activatable entry shows the snippet ID and its activation trigger text."""
        distribute = _import_distribute()

        _make_procedure_snippet(
            tmp_path,
            snippet_id="general/procedure/brainstorming",
            description="Refine ideas into designs",
            activation_trigger="Use when the user wants to refine an idea before implementation",
        )

        _make_baseline_progressive(
            tmp_path,
            ["docs/global/general/procedure/brainstorming.md"],
        )

        master_path = tmp_path / "AGENTS.master.md"
        master_path.write_text(
            dedent("""\
                # Test Project

                @docs/global/baseline-progressive.md
            """),
            encoding="utf-8",
        )

        distribute._write_project_agents(master_path, project_root=tmp_path, warn_only=False)

        agents_content = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

        assert "general/procedure/brainstorming" in agents_content
        assert "Use when the user wants to refine an idea before implementation" in agents_content

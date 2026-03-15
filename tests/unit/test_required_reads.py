"""Characterization tests for teleclaude.required_reads."""

from __future__ import annotations

from teleclaude.required_reads import (
    extract_required_reads,
    normalize_required_refs,
    strip_required_reads_section,
)


def test_extract_required_reads_returns_refs_and_removes_section() -> None:
    refs, stripped = extract_required_reads("# Title\n\n## Required Reads\n- @docs/a\n@docs/b\n\n## Notes\nBody\n")

    assert refs == ["docs/a", "docs/b"]
    assert stripped == "# Title\n\n## Notes\nBody\n"


def test_extract_required_reads_stops_when_section_contains_non_ref_content() -> None:
    refs, stripped = extract_required_reads("## Required Reads\nnot-a-ref\n@docs/after\n")

    assert refs == []
    assert stripped == "not-a-ref\n@docs/after\n"


def test_strip_required_reads_section_and_normalize_refs() -> None:
    stripped = strip_required_reads_section("Intro\n\n## Required Reads\n@docs/a\n\n### Later\nText\n")

    assert stripped == "Intro\n\n### Later\nText\n"
    assert normalize_required_refs([" @docs/a ", "", "docs/b", "@ "]) == ["docs/a", "docs/b"]

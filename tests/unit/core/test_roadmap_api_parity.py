"""Chain test: assemble_roadmap() output must match API /todos serialization.

Verifies that TodoInfo fields survive the full serialization chain:
  assemble_roadmap() → TodoInfo → TodoDTO (API) → dict
vs.
  assemble_roadmap() → TodoInfo → to_dict() (CLI --json)

Any field present in one path but absent or different in the other
indicates a serialization gap that would cause the TUI to show
different data than `telec roadmap --json`.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from teleclaude.api_models import TodoDTO
from teleclaude.core.models import TodoInfo
from teleclaude.core.next_machine.core import RoadmapEntry
from teleclaude.core.roadmap import assemble_roadmap


@pytest.fixture
def project_with_rich_state(tmp_path: Path) -> Path:
    """Project with state.yaml files covering all marker fields."""
    todos = tmp_path / "todos"
    todos.mkdir()
    (todos / "icebox.yaml").touch()

    # Item with full state: DOR, build, review, findings, deferrals, deps
    (todos / "full-item").mkdir()
    (todos / "full-item" / "requirements.md").write_text("# Req")
    (todos / "full-item" / "implementation-plan.md").write_text("# Plan")
    (todos / "full-item" / "state.yaml").write_text(
        json.dumps(
            {
                "phase": "in_progress",
                "build": "complete",
                "review": "changes_requested",
                "deferrals_processed": True,
                "dor": {"score": 9, "status": "pass", "schema_version": 1},
                "unresolved_findings": ["F1", "F2"],
                "breakdown": {"assessed": True, "todos": ["child-item"]},
            }
        )
    )

    # Child item with minimal state
    (todos / "child-item").mkdir()
    (todos / "child-item" / "requirements.md").write_text("# Req")
    (todos / "child-item" / "state.yaml").write_text(json.dumps({"phase": "pending", "dor": {"score": 3}}))

    # Item with no state.yaml (only input.md)
    (todos / "bare-item").mkdir()
    (todos / "bare-item" / "input.md").write_text("# Input")

    return tmp_path


def _roadmap_entries() -> list[RoadmapEntry]:
    return [
        RoadmapEntry(slug="full-item", description="Full markers", group="core"),
        RoadmapEntry(slug="child-item", description="Child", group="core"),
        RoadmapEntry(slug="bare-item", description="Bare"),
    ]


def _todo_info_to_api_dict(
    info: TodoInfo, computer: str = "test", project_path: str = "/test"
) -> dict[str, object]:  # guard: loose-dict - Pydantic model_dump output
    """Simulate the API server's TodoInfo → TodoDTO conversion (api_server.py:1168-1190)."""
    dto = TodoDTO(
        slug=info.slug,
        status=info.status,
        description=info.description,
        computer=computer,
        project_path=project_path,
        has_requirements=info.has_requirements,
        has_impl_plan=info.has_impl_plan,
        build_status=info.build_status,
        review_status=info.review_status,
        dor_score=info.dor_score,
        deferrals_status=info.deferrals_status,
        findings_count=info.findings_count,
        files=info.files,
        after=info.after,
        group=info.group,
    )
    return dto.model_dump()


# --- Marker fields that both paths must preserve ---

_MARKER_FIELDS = (
    "slug",
    "status",
    "description",
    "has_requirements",
    "has_impl_plan",
    "build_status",
    "review_status",
    "dor_score",
    "deferrals_status",
    "findings_count",
    "files",
    "after",
    "group",
)


def test_cli_and_api_produce_same_markers(project_with_rich_state: Path) -> None:
    """The CLI (to_dict) and API (TodoDTO) paths must agree on all marker fields."""
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=_roadmap_entries()):
        with patch("teleclaude.core.roadmap.load_icebox_slugs", return_value=[]):
            todos = assemble_roadmap(str(project_with_rich_state))

    for info in todos:
        cli_dict = info.to_dict()
        api_dict = _todo_info_to_api_dict(info)

        for field in _MARKER_FIELDS:
            cli_val = cli_dict.get(field)
            api_val = api_dict.get(field)
            assert cli_val == api_val, f"{info.slug}.{field}: CLI={cli_val!r} != API={api_val!r}"


def test_full_item_markers(project_with_rich_state: Path) -> None:
    """Verify the fully-populated item preserves all markers through both paths."""
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=_roadmap_entries()):
        with patch("teleclaude.core.roadmap.load_icebox_slugs", return_value=[]):
            todos = assemble_roadmap(str(project_with_rich_state))

    full = next(t for t in todos if t.slug == "full-item")
    cli_dict = full.to_dict()
    api_dict = _todo_info_to_api_dict(full)

    # Both paths must show the same rich state
    for d in (cli_dict, api_dict):
        assert d["status"] == "in_progress"
        assert d["build_status"] == "complete"
        assert d["review_status"] == "changes_requested"
        assert d["dor_score"] == 9
        assert d["deferrals_status"] == "processed"
        assert d["findings_count"] == 2
        assert d["has_requirements"] is True
        assert d["has_impl_plan"] is True


def test_bare_item_defaults(project_with_rich_state: Path) -> None:
    """Item without state.yaml still produces consistent defaults across paths."""
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=_roadmap_entries()):
        with patch("teleclaude.core.roadmap.load_icebox_slugs", return_value=[]):
            todos = assemble_roadmap(str(project_with_rich_state))

    bare = next(t for t in todos if t.slug == "bare-item")
    cli_dict = bare.to_dict()
    api_dict = _todo_info_to_api_dict(bare)

    for d in (cli_dict, api_dict):
        assert d["status"] == "pending"
        assert d["build_status"] is None
        assert d["review_status"] is None
        assert d["dor_score"] is None
        assert d["deferrals_status"] is None
        assert d["findings_count"] == 0
        assert d["has_requirements"] is False
        assert d["has_impl_plan"] is False


def test_dependency_injection_preserved(project_with_rich_state: Path) -> None:
    """Container→child dependency injection appears in both paths."""
    with patch("teleclaude.core.roadmap.load_roadmap", return_value=_roadmap_entries()):
        with patch("teleclaude.core.roadmap.load_icebox_slugs", return_value=[]):
            todos = assemble_roadmap(str(project_with_rich_state))

    child = next(t for t in todos if t.slug == "child-item")
    cli_dict = child.to_dict()
    api_dict = _todo_info_to_api_dict(child)

    cli_after = cli_dict["after"]
    api_after = api_dict["after"]
    assert isinstance(cli_after, list) and "full-item" in cli_after
    assert isinstance(api_after, list) and "full-item" in api_after


def test_api_dto_has_no_extra_fields() -> None:
    """TodoDTO must not introduce fields absent from TodoInfo.to_dict().

    If TodoDTO grows a field that TodoInfo doesn't have, the API
    would return data the CLI can't produce — a silent divergence.
    """
    info_fields = set(TodoInfo.__dataclass_fields__.keys())
    dto_fields = set(TodoDTO.model_fields.keys())

    # These fields are API-only (transport metadata, not todo state)
    api_only_allowed = {"computer", "project_path"}

    extra = dto_fields - info_fields - api_only_allowed
    assert not extra, f"TodoDTO has fields not in TodoInfo: {extra}"


def test_todo_info_has_no_fields_missing_from_dto() -> None:
    """Every TodoInfo field must have a corresponding TodoDTO field.

    If TodoInfo grows a field that TodoDTO doesn't have, the CLI
    would show data the API can't deliver — a silent divergence.
    """
    info_fields = set(TodoInfo.__dataclass_fields__.keys())
    dto_fields = set(TodoDTO.model_fields.keys())

    missing = info_fields - dto_fields
    assert not missing, f"TodoInfo has fields not in TodoDTO: {missing}"

"""Shared TUI test fixtures and support classes."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import yaml
from textual.widget import Widget

import teleclaude.cli.tui.widgets.chip as chip
import teleclaude.config.loader as loader
import teleclaude.core.identity as identity
from teleclaude.api_models import (
    AgentAvailabilityDTO,
    ChiptunesStatusDTO,
    ComputerDTO,
    ProjectWithTodosDTO,
    SessionDTO,
    SettingsDTO,
    TTSSettingsDTO,
    TuiBootstrapDataDTO,
    TuiBootstrapDTO,
    TuiBootstrapPillar,
)
from teleclaude.cli.tui.messages import DataRefreshed
from teleclaude.cli.tui.pane_bridge import PaneManagerBridge

PILLAR_COMPUTERS: TuiBootstrapPillar = "computers"
PILLAR_PROJECTS: TuiBootstrapPillar = "projects"
PILLAR_SESSIONS: TuiBootstrapPillar = "sessions"
PILLAR_AVAILABILITY: TuiBootstrapPillar = "availability"
PILLAR_JOBS: TuiBootstrapPillar = "jobs"
PILLAR_SETTINGS: TuiBootstrapPillar = "settings"
PILLAR_CHIPTUNES: TuiBootstrapPillar = "chiptunes"


class StubPaneBridge(PaneManagerBridge):
    """Pane bridge shell that satisfies app data-refresh queries without tmux."""

    def __init__(self, *, is_reload: bool = False, **kwargs: object) -> None:
        Widget.__init__(self, **kwargs)
        self._active_doc_preview = None

    def sync_layout_state(self, *, preview_session_id: str | None, sticky_session_ids: list[str]) -> None:
        return None

    def on_data_refreshed(self, message: DataRefreshed) -> None:
        return None


def build_bootstrap_response(
    pillars: list[TuiBootstrapPillar],
    *,
    sessions: list[SessionDTO] | None = None,
    availability: dict[str, AgentAvailabilityDTO] | None = None,
    projects_with_todos: list[ProjectWithTodosDTO] | None = None,
    computers: list[ComputerDTO] | None = None,
) -> TuiBootstrapDTO:
    """Build a successful TUI bootstrap response for the requested pillars.

    Each field is populated only when its pillar was requested, matching the
    daemon's partial-pillar-success contract; ``sessions`` seeds the sessions
    pillar's payload when requested, ``availability`` seeds the availability
    pillar's payload when requested, ``projects_with_todos`` seeds the
    projects pillar's payload when requested, and ``computers`` seeds the
    computers pillar's payload when requested.
    """
    requested = set(pillars)
    data = TuiBootstrapDataDTO(
        computers=(computers or []) if PILLAR_COMPUTERS in requested else None,
        projects_with_todos=(projects_with_todos or []) if PILLAR_PROJECTS in requested else None,
        sessions=(sessions or []) if PILLAR_SESSIONS in requested else None,
        availability=(availability or {}) if PILLAR_AVAILABILITY in requested else None,
        jobs=[] if PILLAR_JOBS in requested else None,
        settings=SettingsDTO(tts=TTSSettingsDTO()) if PILLAR_SETTINGS in requested else None,
        chiptunes=ChiptunesStatusDTO() if PILLAR_CHIPTUNES in requested else None,
    )
    return TuiBootstrapDTO(requested=list(pillars), data=data)


@pytest.fixture
def wire_people(tmp_path, monkeypatch) -> Callable[..., identity.IdentityResolver]:
    """Wire a real IdentityResolver over a temp global config + person overlays.

    Returns a builder that registers the given people (and optional per-person
    overlay YAML keyed by folder slug), constructs a resolver against them, and
    points the chip helper's resolver lookup at it. Drives the real
    YAML→config→resolver path that the chip renderer consumes.
    """

    def _wire(people: list[dict], *, overlays: dict[str, str] | None = None) -> identity.IdentityResolver:
        people_dir = tmp_path / "people"
        people_dir.mkdir(exist_ok=True)
        global_path = tmp_path / "teleclaude.yml"
        with open(global_path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"people": people}, f)
        for slug, overlay_yaml in (overlays or {}).items():
            person_dir = people_dir / slug
            person_dir.mkdir(parents=True, exist_ok=True)
            (person_dir / "teleclaude.yml").write_text(overlay_yaml, encoding="utf-8")

        monkeypatch.setattr(loader, "GLOBAL_CONFIG_PATH", global_path)
        monkeypatch.setattr(loader, "PEOPLE_DIR", people_dir)
        monkeypatch.setattr(identity, "PEOPLE_DIR", people_dir)
        monkeypatch.setattr(identity, "_PEOPLE_DIR", people_dir)
        monkeypatch.setattr(identity, "_GLOBAL_CONFIG_PATH", global_path)

        resolver = identity.IdentityResolver()
        monkeypatch.setattr(chip, "get_identity_resolver", lambda: resolver)
        return resolver

    return _wire

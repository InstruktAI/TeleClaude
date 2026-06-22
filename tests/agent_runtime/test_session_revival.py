"""Functional coverage for native-form revival project resolution (UC-SR1, UC-SR2).

Drives the real revive surface (the `POST /sessions/{id}/revive` route, real auth,
real in-process session creation) with only the process/network/filesystem line
faked: the transcript-filesystem the existence guard reads and the identity
resolution the session-create path depends on. Assertions target the persisted
contract — the minted session row's `project_path`/`subdir` read back through the
DB — never internal calls or response passthroughs.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

import teleclaude.api.sessions_actions_routes as revive_mod
from teleclaude.config import config as config_module
from teleclaude.core.command_handlers import _session as session_handler_mod
from teleclaude.core.identity import IdentityContext

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-revival"
_NATIVE_ID = "native-revive-uc"
_CALLER_EMAIL = "test@test.com"
_HEADERS = {"x-telec-email": _CALLER_EMAIL}


def _fake_revive_boundary(monkeypatch: pytest.MonkeyPatch, native_id: str) -> None:
    """Resolve ``native_id`` on disk and resolve an admin identity for the mint."""
    monkeypatch.setattr(
        revive_mod,
        "discover_transcripts",
        lambda _agents: [SimpleNamespace(path=Path("/fake/transcript.jsonl"))],
    )
    monkeypatch.setattr(revive_mod, "extract_session_id", lambda _path, _agent: native_id)
    admin_identity = IdentityContext(person_email=_CALLER_EMAIL, person_role="admin")
    monkeypatch.setattr(
        session_handler_mod,
        "get_identity_resolver",
        lambda: SimpleNamespace(resolve=lambda _origin, _meta: admin_identity),
    )


async def _seed_closed_row(
    api: AsyncClient,
    *,
    native_id: str,
    project_path: str,
    subdir: str | None,
    created_at: str,
) -> None:
    """Create a closed session row bound to ``native_id`` at a fixed created_at."""
    session = await api.db.create_session(
        computer_name="TestComputer",
        tmux_session_name=f"tc-{created_at}",
        last_input_origin="terminal",
        title="prior",
        project_path=project_path,
        subdir=subdir,
        native_session_id=native_id,
        active_agent="claude",
        emit_session_started=False,
    )
    await api.db.update_session(session.session_id, created_at=created_at)
    await api.db.close_session(session.session_id)


@pytest.mark.spec(_SPEC, "UC-SR1")
async def test_fresh_adoption_recovers_recorded_project_from_earliest_row(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The minted row inherits the earliest prior row's project, not Q or caller cwd."""
    subdir_s = "sub-a"
    project_p = tmp_path / "projP"
    (project_p / subdir_s).mkdir(parents=True)
    project_q = str(tmp_path / "projQ")
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()
    caller_cwd = str(caller_dir)

    # Earliest closed row records project P; a later closed row records Q.
    await _seed_closed_row(
        api,
        native_id=_NATIVE_ID,
        project_path=str(project_p),
        subdir=subdir_s,
        created_at="2026-01-01T00:00:00+00:00",
    )
    await _seed_closed_row(
        api,
        native_id=_NATIVE_ID,
        project_path=project_q,
        subdir="sub-b",
        created_at="2026-02-01T00:00:00+00:00",
    )
    _fake_revive_boundary(monkeypatch, _NATIVE_ID)

    await api.post(
        f"/sessions/{_NATIVE_ID}/revive",
        params={"agent": "claude", "project": caller_cwd},
        headers=_HEADERS,
    )

    minted = await api.db.get_session_by_field("native_session_id", _NATIVE_ID, include_initializing=True)
    assert minted is not None
    assert minted.project_path == str(project_p)
    assert minted.subdir == subdir_s


@pytest.mark.spec(_SPEC, "UC-SR2")
async def test_fresh_adoption_without_prior_row_falls_back_to_provided_argument(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no prior row, the provided project argument is split against trusted dirs."""
    expected_subdir = "wt"
    trusted_root = (tmp_path / "trusted").resolve()
    (trusted_root / expected_subdir).mkdir(parents=True)
    provided = str(trusted_root / expected_subdir)

    monkeypatch.setattr(
        config_module.computer,
        "get_all_trusted_dirs",
        lambda: [SimpleNamespace(path=str(trusted_root))],
    )
    _fake_revive_boundary(monkeypatch, _NATIVE_ID)

    await api.post(
        f"/sessions/{_NATIVE_ID}/revive",
        params={"agent": "claude", "project": provided},
        headers=_HEADERS,
    )

    minted = await api.db.get_session_by_field("native_session_id", _NATIVE_ID, include_initializing=True)
    assert minted is not None
    assert minted.project_path == str(trusted_root)
    assert minted.subdir == expected_subdir

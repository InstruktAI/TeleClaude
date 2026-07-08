"""Functional coverage for native-form revival project and title resolution (UC-SR1..UC-SR6).

Drives the real revive surface (the `POST /sessions/{id}/revive` route, real auth,
real in-process session creation) with only the process/network/filesystem line
faked: the transcript-filesystem the existence guard and the recovery helper read,
and the identity resolution the session-create path depends on. No test scans the
real agent transcript roots — discovery is faked so runs stay hermetic and fast.
Assertions target the persisted contract — the minted session row's
`project_path`/`subdir` read back through the DB — never internal calls or response
passthroughs. Each test uses a distinct native id so nothing bleeds across tests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

import teleclaude.api.sessions_actions_routes as revive_mod
import teleclaude.utils.transcript_discovery as recovery_mod
from teleclaude.config import config as config_module
from teleclaude.constants import ROLE_TASKER
from teleclaude.core.command_handlers import _session as session_handler_mod
from teleclaude.core.identity import IdentityContext

pytestmark = [pytest.mark.functional, pytest.mark.asyncio]

_SPEC = "project/spec/feature/agent_runtime/session-revival"
_CALLER_EMAIL = "test@test.com"
_ORIGIN_TITLE = "prior"
_HEADERS = {"x-telec-email": _CALLER_EMAIL}


def _fake_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve an admin identity so the mint path stamps the caller."""
    admin_identity = IdentityContext(person_email=_CALLER_EMAIL, person_role="admin")
    monkeypatch.setattr(
        session_handler_mod,
        "get_identity_resolver",
        lambda: SimpleNamespace(resolve=lambda _origin, _meta: admin_identity),
    )


def _fake_transcript_existence(monkeypatch: pytest.MonkeyPatch, native_id: str, path: Path) -> None:
    """Make the existence guard resolve ``native_id`` to a Claude/Gemini transcript."""
    monkeypatch.setattr(revive_mod, "discover_transcripts", lambda _agents: [SimpleNamespace(path=path)])
    monkeypatch.setattr(revive_mod, "extract_session_id", lambda _path, _agent: native_id)


def _fake_transcript_recovery(monkeypatch: pytest.MonkeyPatch, native_id: str, path: Path) -> None:
    """Make the recovery helper resolve ``native_id`` to a discovered transcript path."""
    monkeypatch.setattr(recovery_mod, "discover_transcripts", lambda _agents: [SimpleNamespace(path=path)])
    monkeypatch.setattr(recovery_mod, "extract_session_id", lambda _path, _agent: native_id)


def _trust(monkeypatch: pytest.MonkeyPatch, trusted_root: Path) -> None:
    """Register a single trusted root for project-path splitting."""
    monkeypatch.setattr(
        config_module.computer,
        "get_all_trusted_dirs",
        lambda: [SimpleNamespace(path=str(trusted_root))],
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
        title=_ORIGIN_TITLE,
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
    native_id = "native-revive-sr1"
    subdir_s = "sub-a"
    project_p = tmp_path / "projP"
    (project_p / subdir_s).mkdir(parents=True)
    project_q = str(tmp_path / "projQ")
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()

    # Earliest closed row records project P; a later closed row records Q.
    await _seed_closed_row(
        api,
        native_id=native_id,
        project_path=str(project_p),
        subdir=subdir_s,
        created_at="2026-01-01T00:00:00+00:00",
    )
    await _seed_closed_row(
        api,
        native_id=native_id,
        project_path=project_q,
        subdir="sub-b",
        created_at="2026-02-01T00:00:00+00:00",
    )
    _fake_transcript_existence(monkeypatch, native_id, Path("/fake/transcript.jsonl"))
    _fake_identity(monkeypatch)

    await api.post(
        f"/sessions/{native_id}/revive",
        params={"agent": "claude", "project": str(caller_dir)},
        headers=_HEADERS,
    )

    minted = await api.db.get_session_by_field("native_session_id", native_id, include_initializing=True)
    assert minted is not None
    assert minted.project_path == str(project_p)
    assert minted.subdir == subdir_s


@pytest.mark.spec(_SPEC, "UC-SR2")
async def test_fresh_adoption_without_prior_row_recovers_from_claude_transcript(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no prior row, the Claude transcript's embedded cwd — not caller cwd — is stored."""
    native_id = "native-revive-sr2"
    expected_subdir = "wt"
    trusted_root = (tmp_path / "trusted").resolve()
    (trusted_root / expected_subdir).mkdir(parents=True)
    recovered_dir = str(trusted_root / expected_subdir)
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()

    transcript = tmp_path / "claude.jsonl"
    transcript.write_text(json.dumps({"type": "user", "cwd": recovered_dir}) + "\n", encoding="utf-8")

    _trust(monkeypatch, trusted_root)
    _fake_transcript_existence(monkeypatch, native_id, transcript)
    _fake_transcript_recovery(monkeypatch, native_id, transcript)
    _fake_identity(monkeypatch)

    await api.post(
        f"/sessions/{native_id}/revive",
        params={"agent": "claude", "project": str(caller_dir)},
        headers=_HEADERS,
    )

    minted = await api.db.get_session_by_field("native_session_id", native_id, include_initializing=True)
    assert minted is not None
    assert minted.project_path == str(trusted_root)
    assert minted.subdir == expected_subdir


@pytest.mark.spec(_SPEC, "UC-SR3")
async def test_fresh_adoption_without_prior_row_recovers_from_codex_rollout(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no prior row, the Codex rollout's session-metadata cwd is stored."""
    native_id = "native-revive-sr3"
    expected_subdir = "wt"
    trusted_root = (tmp_path / "trusted").resolve()
    (trusted_root / expected_subdir).mkdir(parents=True)
    recovered_dir = str(trusted_root / expected_subdir)
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()

    rollout = tmp_path / "rollout.jsonl"
    meta_line = json.dumps({"type": "session_meta", "payload": {"id": "thr-1", "cwd": recovered_dir}})
    rollout.write_text(meta_line + "\n", encoding="utf-8")

    _trust(monkeypatch, trusted_root)
    _fake_identity(monkeypatch)
    # Existence guard and recovery helper both resolve the rollout by native id.
    monkeypatch.setattr(revive_mod, "discover_codex_transcript_path", lambda _id: str(rollout))
    monkeypatch.setattr(recovery_mod, "discover_codex_transcript_path", lambda _id: str(rollout))

    await api.post(
        f"/sessions/{native_id}/revive",
        params={"agent": "codex", "project": str(caller_dir)},
        headers=_HEADERS,
    )

    minted = await api.db.get_session_by_field("native_session_id", native_id, include_initializing=True)
    assert minted is not None
    assert minted.project_path == str(trusted_root)
    assert minted.subdir == expected_subdir


@pytest.mark.spec(_SPEC, "UC-SR4")
async def test_fresh_adoption_confirms_gemini_project_by_hash(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A Gemini caller directory whose hash matches the legacy project hash is stored."""
    native_id = "native-revive-sr4"
    expected_subdir = "proj"
    trusted_root = (tmp_path / "trusted").resolve()
    caller_dir = trusted_root / expected_subdir
    caller_dir.mkdir(parents=True)

    legacy_root = tmp_path / "gemini_tmp"
    project_hash = hashlib.sha256(str(caller_dir).encode()).hexdigest()
    transcript = legacy_root / project_hash / "chats" / f"session-{native_id}.json"

    monkeypatch.setenv("TELECLAUDE_LEGACY_GEMINI_ROOT", str(legacy_root))
    _trust(monkeypatch, trusted_root)
    _fake_transcript_existence(monkeypatch, native_id, transcript)
    _fake_transcript_recovery(monkeypatch, native_id, transcript)
    _fake_identity(monkeypatch)

    await api.post(
        f"/sessions/{native_id}/revive",
        params={"agent": "gemini", "project": str(caller_dir)},
        headers=_HEADERS,
    )

    minted = await api.db.get_session_by_field("native_session_id", native_id, include_initializing=True)
    assert minted is not None
    assert minted.project_path == str(trusted_root)
    assert minted.subdir == expected_subdir


@pytest.mark.spec(_SPEC, "UC-SR5")
async def test_fresh_adoption_fails_loud_when_project_unlocatable(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No recoverable project → the route rejects and mints no row at the caller cwd."""
    native_id = "native-revive-sr5"
    caller_dir = tmp_path / "caller"
    caller_dir.mkdir()

    _fake_transcript_existence(monkeypatch, native_id, Path("/fake/transcript.jsonl"))
    _fake_identity(monkeypatch)
    # Existence passes, but the recovery helper finds no matching transcript.
    monkeypatch.setattr(recovery_mod, "discover_transcripts", lambda _agents: [])

    response = await api.post(
        f"/sessions/{native_id}/revive",
        params={"agent": "claude", "project": str(caller_dir)},
        headers=_HEADERS,
    )

    assert response.status_code == 422
    minted = await api.db.get_session_by_field("native_session_id", native_id, include_initializing=True)
    assert minted is None


@pytest.mark.spec(_SPEC, "UC-SR6")
async def test_fresh_adoption_recovers_title_from_earliest_row(
    api: AsyncClient,
    cluster_event_bus: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The minted row inherits the earliest prior row's title, not the "Untitled" default."""
    native_id = "native-revive-sr6"
    project_p = tmp_path / "projP"
    project_p.mkdir()

    await _seed_closed_row(
        api,
        native_id=native_id,
        project_path=str(project_p),
        subdir=None,
        created_at="2026-01-01T00:00:00+00:00",
    )
    _fake_transcript_existence(monkeypatch, native_id, Path("/fake/transcript.jsonl"))
    _fake_identity(monkeypatch)

    await api.post(
        f"/sessions/{native_id}/revive",
        params={"agent": "claude"},
        headers=_HEADERS,
    )

    minted = await api.db.get_session_by_field("native_session_id", native_id, include_initializing=True)
    assert minted is not None
    assert minted.title == _ORIGIN_TITLE


@pytest.mark.spec("project/spec/feature/agent_runtime/run-session-with-command", "UC-DPE1")
async def test_tasker_caller_is_rejected_by_the_real_revive_route(api: AsyncClient) -> None:
    """A tasker-identified caller must 403 on the real route, not just the helper.

    `clearance_sessions_revive` previously reused `sessions run`'s clearance target,
    so widening `sessions run` for tasker silently widened this route too even
    though the CLI surface denies tasker `sessions revive`. Drive the actual
    `POST /sessions/{id}/revive` route with a real tasker session row to prove the
    HTTP enforcement seam, not just the dependency function in isolation.
    """
    tasker_session_id = "tasker-caller-revive-guard"
    await api.db.create_session(
        computer_name="test",
        tmux_session_name=f"tmux-{tasker_session_id}",
        last_input_origin="cli",
        title="tasker",
        session_id=tasker_session_id,
        system_role=ROLE_TASKER,
        emit_session_started=False,
    )

    response = await api.post(
        "/sessions/native-revive-guard/revive",
        params={"agent": "claude"},
        headers={"x-caller-session-id": tasker_session_id},
    )

    assert response.status_code == 403

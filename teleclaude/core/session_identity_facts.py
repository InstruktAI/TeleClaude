"""Dependency-light reads of session facts needed to resolve callers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

_IDENTITY_QUERY = """SELECT session_id, computer_name, principal, human_email, human_role,
role, working_slug, job, initiator_session_id, company, closed_at, project_path,
json_extract(origin_metadata, '$.confinement.profile')
FROM sessions WHERE session_id = ?"""  # guard: raw-sql
_LEGACY_IDENTITY_QUERY = """SELECT session_id, computer_name, principal, human_email, human_role,
role, working_slug, job, initiator_session_id, closed_at, project_path
FROM sessions WHERE session_id = ?"""  # guard: raw-sql
_COMPANY_COLUMN_MISSING = "no such column: company"
_ACTIVE_AGENT_QUERY = "SELECT active_agent FROM sessions WHERE session_id = ?"  # guard: raw-sql


@dataclass(frozen=True)
class SessionIdentityFacts:
    """Identity and work-role facts read from one session row."""

    session_id: str
    computer_name: str
    principal: str | None
    human_email: str | None
    human_role: str | None
    role: str | None
    working_slug: str | None
    job: str | None
    initiator_session_id: str | None
    company: str | None
    closed_at: str | None
    project_path: str | None
    confinement_profile: str | None = None


def read_session_identity_facts(db_path: str, session_id: str) -> SessionIdentityFacts | None:
    """Return one row's identity facts, tolerating databases before company migration."""
    if not Path(db_path).is_file():
        return None
    try:
        with sqlite3.connect(db_path, timeout=0.2) as connection:
            try:
                row = connection.execute(_IDENTITY_QUERY, (session_id,)).fetchone()
                has_company = True
            except sqlite3.OperationalError as error:
                if _COMPANY_COLUMN_MISSING not in str(error):
                    return None
                row = connection.execute(_LEGACY_IDENTITY_QUERY, (session_id,)).fetchone()
                has_company = False
    except sqlite3.Error:
        return None
    if row is None:
        return None
    company = row[9] if has_company else None
    closed_at = row[10] if has_company else row[9]
    project_path = row[11] if has_company else row[10]
    return SessionIdentityFacts(
        session_id=str(row[0]),
        computer_name=str(row[1]),
        principal=row[2],
        human_email=row[3],
        human_role=row[4],
        role=row[5],
        working_slug=row[6],
        job=row[7],
        initiator_session_id=row[8],
        company=str(company) if company is not None else None,
        closed_at=str(closed_at) if closed_at is not None else None,
        project_path=str(project_path) if project_path is not None else None,
        confinement_profile=str(row[12]) if has_company and row[12] is not None else None,
    )


def read_session_active_agent(db_path: str, session_id: str) -> str | None:
    """Return the recorded active agent through a dependency-light session read."""
    if not Path(db_path).is_file():
        return None
    try:
        with sqlite3.connect(db_path, timeout=0.2) as connection:
            row = connection.execute(_ACTIVE_AGENT_QUERY, (session_id,)).fetchone()
    except sqlite3.Error:
        return None
    if row is None or not row[0]:
        return None
    return str(row[0])

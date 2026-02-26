"""Session access control for web interface identity-based requests."""

from __future__ import annotations

from fastapi import HTTPException, Request

from teleclaude.core.db import db


async def check_session_access(
    request: Request,
    session_id: str,
    *,
    require_owner: bool = False,
) -> None:
    """Verify the requester has access to a session.

    Only enforced when identity headers are present (web interface).
    TUI/tool clients without headers bypass all checks.

    Args:
        request: FastAPI request (for identity headers).
        session_id: Session to check access for.
        require_owner: If True, only the session owner or admin may proceed.

    Raises:
        HTTPException 403 if access denied.
        HTTPException 404 if session not found.
    """
    email = request.headers.get("x-web-user-email")
    role = request.headers.get("x-web-user-role")

    # No identity headers = TUI/tool client, always allowed
    if not email:
        return

    # Admin always allowed
    if role == "admin":
        return

    from teleclaude.api.auth import _get_cached_session

    session = _get_cached_session(session_id)
    if session is None:
        session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Owner check (for delete)
    if require_owner:
        if session.human_email != email:
            raise HTTPException(status_code=403, detail="Forbidden: not session owner")
        return

    # Standard access: own session or shared + member
    if session.human_email == email:
        return
    if role == "member" and getattr(session, "visibility", "private") == "shared":
        return

    raise HTTPException(status_code=403, detail="Forbidden: no access to this session")

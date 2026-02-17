"""Session-scoped file serving endpoint.

GET /data/{session_id}?file=<relative_path> serves files from the session workspace.
"""

import mimetypes

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.session_utils import get_session_output_dir

logger = get_logger(__name__)

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/{session_id}")
async def serve_session_file(
    session_id: str,
    file: str = Query(..., min_length=1, description="Relative path within session workspace"),
) -> FileResponse:
    """Serve a file from the session workspace directory."""
    # Validate session exists
    session = await db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Reject path traversal
    if ".." in file.split("/"):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    workspace = get_session_output_dir(session_id)
    resolved = (workspace / file).resolve()

    # Ensure resolved path is within workspace
    if not str(resolved).startswith(str(workspace.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"

    return FileResponse(
        path=str(resolved),
        media_type=content_type,
        filename=resolved.name,
        headers={"Content-Disposition": f'attachment; filename="{resolved.name}"'},
    )

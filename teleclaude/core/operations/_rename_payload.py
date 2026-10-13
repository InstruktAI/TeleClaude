"""Payload of a todo-rename operation: its validated fields and target agreement."""

from __future__ import annotations

import json

from fastapi import HTTPException

from teleclaude.core.db_models import Operation

_OLD_SLUG_FIELD = "old_slug"
_NEW_SLUG_FIELD = "new_slug"
_CWD_FIELD = "cwd"
_TARGET_CONFLICT_STATUS = 409
_TARGET_CONFLICT_DETAIL = "todo rename operation already targets a different slug"
_PAYLOAD_INVALID_JSON = "todo rename operation payload is invalid JSON"
_PAYLOAD_OBJECT_REQUIRED = "todo rename operation payload must be an object"
_PAYLOAD_FIELDS_REQUIRED = "todo rename operation payload must include old_slug, new_slug, and cwd"


def rename_payload(operation: Operation) -> dict[str, str]:
    """Return the rename operation's old slug, new slug and checkout, validated."""
    try:
        payload = json.loads(operation.payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError(_PAYLOAD_INVALID_JSON) from exc
    if not isinstance(payload, dict):
        raise ValueError(_PAYLOAD_OBJECT_REQUIRED)
    old_slug = payload.get(_OLD_SLUG_FIELD)
    new_slug = payload.get(_NEW_SLUG_FIELD)
    cwd = payload.get(_CWD_FIELD)
    if not isinstance(old_slug, str) or not isinstance(new_slug, str) or not isinstance(cwd, str):
        raise ValueError(_PAYLOAD_FIELDS_REQUIRED)
    return {_OLD_SLUG_FIELD: old_slug, _NEW_SLUG_FIELD: new_slug, _CWD_FIELD: cwd}


def ensure_rename_target_matches(operation: Operation, new_slug: str) -> None:
    """Refuse a reattach whose requested slug differs from the operation's recorded target."""
    if rename_payload(operation)[_NEW_SLUG_FIELD] != new_slug:
        raise HTTPException(status_code=_TARGET_CONFLICT_STATUS, detail=_TARGET_CONFLICT_DETAIL)

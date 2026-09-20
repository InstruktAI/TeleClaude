"""Own the serialized predecessor-transcript chain on a session."""

from __future__ import annotations

import json


def append_transcript_once(transcript_files: str | None, transcript_path: str | None) -> str:
    """Append a non-empty transcript path once and return the serialized chain."""
    try:
        raw_chain = json.loads(transcript_files or "[]")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("session transcript history is malformed") from exc
    if not isinstance(raw_chain, list) or not all(isinstance(path, str) for path in raw_chain):
        raise ValueError("session transcript history must be a list of paths")
    chain = raw_chain
    if transcript_path and transcript_path not in chain:
        chain.append(transcript_path)
    return json.dumps(chain)

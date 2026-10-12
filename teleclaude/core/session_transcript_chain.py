"""Own the serialized predecessor-transcript chain on a session."""

from __future__ import annotations

import json

from teleclaude.core.models import SessionField


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


def native_log_binding_updates(
    *,
    current_log_file: str | None,
    current_chain: str | None,
    new_log_file: str | None,
) -> dict[str, str]:
    """Return the stored-field updates for binding a session to a native transcript file.

    A changed file appends the file it replaces to the predecessor chain once, so every native
    transcript the session has used stays on its lineage. An unchanged or absent file updates nothing.
    """
    if not new_log_file or new_log_file == current_log_file:
        return {}
    updates = {SessionField.NATIVE_LOG_FILE.value: new_log_file}
    previous_log_file = (current_log_file or "").strip()
    if previous_log_file:
        updates[SessionField.TRANSCRIPT_FILES.value] = append_transcript_once(current_chain, previous_log_file)
    return updates


def build_message_chain(transcript_files: str | None, native_log_file: str | None) -> list[str]:
    """Build transcript chain from stored session fields."""
    chain: list[str] = []
    if transcript_files:
        try:
            stored = json.loads(transcript_files)
            if isinstance(stored, list):
                chain = [str(path) for path in stored if path]
        except (json.JSONDecodeError, TypeError):
            pass
    if native_log_file and native_log_file not in chain:
        chain.append(native_log_file)
    return chain

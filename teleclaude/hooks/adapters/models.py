"""Typed payloads for hook normalization."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class NormalizedHookPayload:
    """Normalized hook payload with internal field names."""

    session_id: Optional[str] = None
    transcript_path: Optional[str] = None
    prompt: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict[str, str]:
        """Serialize to dict, dropping None values."""
        data = asdict(self)
        return {k: str(v) for k, v in data.items() if v is not None}

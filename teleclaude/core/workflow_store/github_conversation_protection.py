"""Remove secrets and personal data from a conversation turn before anything about it leaves the computer.

This is a uniform data-protection transform at the publication boundary, applied to every turn alike. It never
decides whether a turn is published or anything about what the turn means: a turn is either protected or, when
protection cannot complete, withheld whole.

Detection comes from established libraries (`teleclaude.core.workflow_store.github_conversation_detectors`). The
platform's own secrets are masked first, from their resolved values. detect-secrets then replaces credential-like
strings, run locally with verification off so no candidate leaves the computer and without its hexadecimal
high-entropy plugin, because commit SHAs and digests fill this conversation. Presidio's analyzer, with its English
small model, then replaces personal data with the entity's label.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.errors import ConfigLoadError
from teleclaude.config.secret_masking import resolved_secret_values

logger = get_logger(__name__)

_WITHHELD_EVENT = "conversation_turn_withheld"


class WithheldReason(StrEnum):
    """Why protection could not complete; carries no content."""

    SECRETS_UNKNOWN = "secrets_unknown"
    DETECTION_FAILED = "detection_failed"


@dataclass(frozen=True)
class ProtectedTexts:
    """The texts of one turn with secrets and personal data replaced, in the order they were given."""

    texts: tuple[str, ...]


@dataclass(frozen=True)
class Withheld:
    """A turn whose protection did not complete; none of its content may leave the computer."""

    reason: WithheldReason


type ProtectionResult = ProtectedTexts | Withheld


def protect_texts(texts: Sequence[str], project_root: Path) -> ProtectionResult:
    """Protect every text of one turn, or withhold the whole turn when protection cannot complete.

    Blocking and CPU-bound: callers run it off the event loop. ``project_root`` selects the configuration whose
    declared secrets are masked.
    """
    try:
        secrets = resolved_secret_values(project_root)
    except (ConfigLoadError, OSError) as error:
        logger.warning(_WITHHELD_EVENT, reason=WithheldReason.SECRETS_UNKNOWN, error_type=type(error).__name__)
        return Withheld(WithheldReason.SECRETS_UNKNOWN)
    try:
        # The libraries cost seconds to import and are needed only once a turn is protected, not when the daemon starts.
        from teleclaude.core.workflow_store.github_conversation_detectors import (  # noqa: PLC0415 - deferred: loads detect-secrets, Presidio and spaCy on the first protected turn.
            protect_text,
        )

        protected = tuple(protect_text(text, secrets) for text in texts)
    except Exception as error:  # supervision boundary: any failure withholds the turn, content-free
        logger.warning(_WITHHELD_EVENT, reason=WithheldReason.DETECTION_FAILED, error_type=type(error).__name__)
        return Withheld(WithheldReason.DETECTION_FAILED)
    return ProtectedTexts(protected)

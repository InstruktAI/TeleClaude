"""Deliver the values a stored document's pending migrations move elsewhere, before a writer saves it."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from teleclaude.config.migrations import _steps
from teleclaude.config.migrations._chain import (
    CURRENT_VERSION,
    Destination,
    DocumentNewerThanInstallation,
    document_version,
    require_registry_subject,
)
from teleclaude.config_subjects import SubjectRef


def carry_pending(
    stored_document: Mapping[str, object], subject: SubjectRef, *, delivered: Callable[[Destination], None]
) -> None:
    """Deliver each moved value that remains in a stored document, in step order."""
    require_registry_subject(subject)
    version = document_version(stored_document)
    if version > CURRENT_VERSION:
        raise DocumentNewerThanInstallation(
            f"Configuration document version {version} is newer than installation version {CURRENT_VERSION}"
        )
    for step in _steps.STEPS[version:]:
        destination = getattr(step, "MOVES", None)
        if destination is None or subject.kind not in step.KINDS:
            continue
        pending = cast(object | None, step.pending(stored_document, subject))
        if pending is None:
            continue
        step.deliver(pending, subject)
        delivered(cast(Destination, destination))

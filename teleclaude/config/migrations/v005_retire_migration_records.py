"""Retire state files replaced by the versioned configuration list."""

from __future__ import annotations

from collections.abc import MutableMapping
from pathlib import Path
from typing import Final

from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.core.migration_signal import MigrationStore, signal_migration_started
from teleclaude.paths import STATE_DIR

VERSION: Final = 5
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
_RETIRED_PATHS: Final = (
    STATE_DIR / "config_advancement.json",
    STATE_DIR / "person_claim_migration.json",
    STATE_DIR / "person_claim_migration.lock",
)


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """This retirement does not change a configuration document."""


def retire(_subject: SubjectRef) -> None:
    """Remove every obsolete migration record when a computer migration run executes."""
    for path in _RETIRED_PATHS:
        if Path(path).exists():
            signal_migration_started(MigrationStore.CONFIGURATION)
            Path(path).unlink(missing_ok=True)

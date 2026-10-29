"""The daemon's stores split from the core database: one write-isolation unit each.

Each store is its own SQLite file beside the core database, with its own schema file, its own numbered
migrations and its own ``schema_migrations`` ledger. The registry here is the one declaration of what a
store is; engine creation, bootstrap and compaction loop over it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType

from teleclaude.core.migration_signal import MigrationStore

_SCHEMAS_DIR = Path(__file__).parent / "store_schemas"
_MIGRATIONS_DIR = Path(__file__).parent / "store_migrations"


class DaemonStore(StrEnum):
    """The stores split from the core database."""

    OUTPUT = "output"
    OPERATIONS = "operations"
    REMINDERS = "reminders"


@dataclass(frozen=True)
class StoreDeclaration:
    """What one store is: its file, its schema, its migration history and its migration signal."""

    file_name: str
    schema_file: Path
    migrations_dir: Path
    migration_store: MigrationStore


STORES: Mapping[DaemonStore, StoreDeclaration] = MappingProxyType(
    {
        DaemonStore.OUTPUT: StoreDeclaration(
            file_name="output.db",
            schema_file=_SCHEMAS_DIR / "output.sql",
            migrations_dir=_MIGRATIONS_DIR / "output",
            migration_store=MigrationStore.OUTPUT,
        ),
        DaemonStore.OPERATIONS: StoreDeclaration(
            file_name="operations.db",
            schema_file=_SCHEMAS_DIR / "operations.sql",
            migrations_dir=_MIGRATIONS_DIR / "operations",
            migration_store=MigrationStore.OPERATIONS,
        ),
        DaemonStore.REMINDERS: StoreDeclaration(
            file_name="reminders.db",
            schema_file=_SCHEMAS_DIR / "reminders.sql",
            migrations_dir=_MIGRATIONS_DIR / "reminders",
            migration_store=MigrationStore.REMINDERS,
        ),
    }
)


def store_db_path(store: DaemonStore, base_dir: str | Path) -> Path:
    """Return a store's database file beside the core database in ``base_dir``."""
    return Path(base_dir).expanduser() / STORES[store].file_name

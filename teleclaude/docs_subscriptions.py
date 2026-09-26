"""Publishes the platform's declared procedure event subscriptions and their digest."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import yaml

from teleclaude.paths import GLOBAL_DOCS_DIR

_INDEX_FILE_NAME = "index.yaml"
_COMPANY_SOURCE_PREFIX = "company:"
_PROCEDURE_TYPE = "procedure"
_COMPANY_SCOPE = "company"


@dataclass(frozen=True)
class SubscriptionEntry:
    """One live procedure's declared event subscriptions and its routing scope."""

    procedure_id: str
    event_types: tuple[str, ...]
    company: str | None


@dataclass(frozen=True)
class SubscriptionPublication:
    """The published subscription set and the deployed index digest it was read from."""

    digest: str
    entries: tuple[SubscriptionEntry, ...]


def published_procedure_subscriptions() -> SubscriptionPublication:
    """Read every live procedure's declared subscriptions from the deployed merged index.

    Reads the one file publication already replaces atomically, so its bytes
    are the version a caller re-derives from on a digest change. A
    ``scope: global`` entry publishes company ``None`` (every company); a
    ``scope: company`` entry publishes the company slug the tier merge wrote
    into ``source_project``. Pending (``delivered_by``) entries are excluded.
    """
    raw = (GLOBAL_DOCS_DIR / _INDEX_FILE_NAME).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    payload = yaml.safe_load(raw.decode("utf-8")) or {}
    snippets = payload.get("snippets", []) if isinstance(payload, dict) else []

    entries: list[SubscriptionEntry] = []
    for entry in snippets:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != _PROCEDURE_TYPE or entry.get("delivered_by"):
            continue
        subscriptions = entry.get("subscriptions")
        if not isinstance(subscriptions, list) or not subscriptions:
            continue
        procedure_id = entry.get("id")
        if not isinstance(procedure_id, str) or not procedure_id:
            continue
        company: str | None = None
        if entry.get("scope") == _COMPANY_SCOPE:
            source_project = entry.get("source_project")
            if not isinstance(source_project, str) or not source_project.startswith(_COMPANY_SOURCE_PREFIX):
                raise ValueError(
                    f"Malformed company-tier source_project for {procedure_id!r}: {source_project!r}. "
                    "A company-scoped subscription with no resolvable company would otherwise publish as "
                    "global (matching every company's events) — refusing rather than widening reach."
                )
            company = source_project[len(_COMPANY_SOURCE_PREFIX) :]
            if not company:
                raise ValueError(f"Empty company slug in source_project for {procedure_id!r}: {source_project!r}")
        entries.append(
            SubscriptionEntry(
                procedure_id=procedure_id,
                event_types=tuple(str(event_type) for event_type in subscriptions),
                company=company,
            )
        )
    return SubscriptionPublication(digest=digest, entries=tuple(entries))

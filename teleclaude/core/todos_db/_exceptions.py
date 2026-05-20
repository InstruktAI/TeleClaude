"""Typed exceptions for todo database contract refusals."""

from __future__ import annotations

from typing_extensions import TypedDict

from teleclaude.docs_reconcile import BlockingSnippet


class OperationErrorPayload(TypedDict):
    """Structured operation failure payload contract."""

    kind: str


class RemoveRefusalSnippetPayload(TypedDict):
    """Serialized snippet blocker payload for remove refusals."""

    path: str
    slug_role: str
    live_deliverer_count: int
    other_removed_deliverers: list[str]


class RemoveRefusalErrorPayload(OperationErrorPayload):
    """Structured remove-refusal operation payload."""

    blocking_snippets: list[RemoveRefusalSnippetPayload]


class OperationFailure(Exception):
    """Base class for operation failures with structured API payloads."""

    error_kind: str

    def to_error_payload(self) -> OperationErrorPayload:
        """Return the machine-readable operation error payload."""
        raise NotImplementedError

    def summary(self) -> str:
        """Return a short human-readable error summary."""
        return f"{type(self).__name__}: {self}"


class RemoveRefused(OperationFailure):
    """Soft-remove refused because it would orphan snippet deliverers."""

    error_kind = "remove_refused_orphan"

    def __init__(self, *, slug: str, blocking_snippets: list[BlockingSnippet]) -> None:
        self.slug = slug
        self.blocking_snippets = blocking_snippets
        super().__init__(slug)

    def to_error_payload(self) -> RemoveRefusalErrorPayload:
        return {
            "kind": self.error_kind,
            "blocking_snippets": [
                {
                    "path": snippet.path,
                    "slug_role": snippet.slug_role,
                    "live_deliverer_count": snippet.live_deliverer_count,
                    "other_removed_deliverers": list(snippet.other_removed_deliverers),
                }
                for snippet in self.blocking_snippets
            ],
        }

    def summary(self) -> str:
        count = len(self.blocking_snippets)
        return f"RemoveRefused: {count} snippet(s) would be orphaned"

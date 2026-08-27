"""Rendering for receipt-backed todo removal refusals."""

from __future__ import annotations

import sys


def render_remove_refusal(status: dict[object, object], slug: str) -> bool:
    """Render a structured removal refusal and report whether it was recognized."""
    error_payload = status.get("error_payload")
    if not isinstance(error_payload, dict):
        return False
    if error_payload.get("kind") == "remove_refused_live_work":
        print("Remove refused; live work holds this todo:", file=sys.stderr)
        claim_holder = error_payload.get("claim_holder")
        if isinstance(claim_holder, str):
            print(f"- claim holder session={claim_holder}", file=sys.stderr)
        for field, label in (("session_ids", "bound session"), ("operation_ids", "bound operation")):
            identifiers = error_payload.get(field)
            if isinstance(identifiers, list):
                for identifier in identifiers:
                    if isinstance(identifier, str):
                        print(f"- {label}={identifier}", file=sys.stderr)
        print(f"Refused: {slug} has live work; rerun with --force only to override it.", file=sys.stderr)
        return True
    if error_payload.get("kind") != "remove_refused_orphan":
        return False
    raw_blocking = error_payload.get("blocking_snippets")
    if not isinstance(raw_blocking, list):
        return False
    print("Remove refused; blocking snippets:", file=sys.stderr)
    rendered_count = 0
    for raw_snippet in raw_blocking:
        if not isinstance(raw_snippet, dict):
            continue
        path = raw_snippet.get("path")
        slug_role = raw_snippet.get("slug_role")
        live_count = raw_snippet.get("live_deliverer_count")
        if not isinstance(path, str) or not isinstance(slug_role, str) or not isinstance(live_count, int):
            continue
        print(f"- path={path} slug_role={slug_role} live_deliverer_count={live_count}", file=sys.stderr)
        rendered_count += 1
    print(f"Refused: {slug} would orphan {rendered_count} snippet(s); see structured error above.", file=sys.stderr)
    return True

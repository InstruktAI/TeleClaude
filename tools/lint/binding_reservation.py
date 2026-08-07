#!/usr/bin/env python3
"""Structural reservation-collision check for feature-spec scenario bindings.

Prepare-time binding reservation (project/spec/feature/workflow/prepare-state-machine
UC-WPS14) claims every scenario a plan will bind on ``main`` before the build-time
``@pytest.mark.spec`` act: a newly authored scenario carries the claim as its own
``<!-- planned:<slug> -->`` block; an existing live-and-unbound scenario is claimed by
wrapping its ``#### UC-…`` block in a ``<!-- planned-change:<slug> -->`` that restates
it unchanged. This tool reads the feature specs, maps every scenario to the slug
whose pending marker encloses it (unclaimed when outside any marker), and reports
any requested binding already reserved by a different in-flight slug.

Usage:
    uv run python tools/lint/binding_reservation.py --slug <slug> \\
        --binding <spec_id>:<scenario_id> [--binding <spec_id>:<scenario_id> ...]

Run with the docs tree relative to the current working directory (matches
``tools/lint/spec_coverage.py``'s ``_DOCS_ROOT`` convention) — invoke from the repo
root, or from a fixture root that contains its own ``docs/`` tree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Runs from a caller's cwd (e.g. a fixture root in tests), so the repo root — where
# the `tools` package lives — is not reliably on sys.path without this.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.doc_body import PLANNED_BLOCK_RE, PLANNED_CHANGE_BLOCK_RE  # noqa: E402
from tools.lint.spec_coverage import _DEF_LINE, _UC_IN_HEADER, collect_scenarios  # noqa: E402


def _owning_slug(text: str, position: int) -> str | None:
    """Return the slug whose pending marker encloses ``position``, or None if unclaimed.

    Markers never nest (validated at ``telec sync``), so at most one marker of either
    kind can contain a given position.
    """
    for regex in (PLANNED_BLOCK_RE, PLANNED_CHANGE_BLOCK_RE):
        for match in regex.finditer(text):
            if match.start() <= position < match.end():
                return match.group("slug")
    return None


def _scenario_position(text: str, scenario_id: str) -> int | None:
    for match in _DEF_LINE.finditer(text):
        uc = _UC_IN_HEADER.search(match.group(1))
        if uc and uc.group(0) == scenario_id:
            return match.start()
    return None


def collect_reservations() -> dict[tuple[str, str], str | None]:
    """Map every bindable ``(spec_id, scenario_id)`` to its owning slug, or None if unclaimed."""
    reservations: dict[tuple[str, str], str | None] = {}
    file_cache: dict[str, str] = {}
    for scenario in collect_scenarios():
        if scenario.scenario_id is None:
            continue
        text = file_cache.get(scenario.spec_file)
        if text is None:
            text = Path(scenario.spec_file).read_text(encoding="utf-8")
            file_cache[scenario.spec_file] = text
        position = _scenario_position(text, scenario.scenario_id)
        owning_slug = _owning_slug(text, position) if position is not None else None
        reservations[(scenario.spec_id, scenario.scenario_id)] = owning_slug
    return reservations


def _parse_binding(raw: str) -> tuple[str, str]:
    spec_id, sep, scenario_id = raw.partition(":")
    if not sep:
        raise argparse.ArgumentTypeError(f"binding must be '<spec_id>:<scenario_id>', got: {raw!r}")
    return spec_id, scenario_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", required=True, help="The requesting todo's slug.")
    parser.add_argument(
        "--binding",
        action="append",
        default=[],
        metavar="SPEC_ID:SCENARIO_ID",
        help="A (spec_id, scenario_id) binding the plan declares. Repeatable.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    reservations = collect_reservations()
    bindings = [_parse_binding(raw) for raw in args.binding]

    # An absent key means "no such scenario", which `.get()` renders as None — the same
    # value an unclaimed scenario has. Reject unknown bindings before the collision test
    # so a mistyped or wrong-namespace identifier cannot read as a clean pass.
    if unknown := [binding for binding in bindings if binding not in reservations]:
        for spec_id, scenario_id in unknown:
            print(f"UNKNOWN: {spec_id} :: {scenario_id} is not a known scenario", file=sys.stderr)
        return 2

    collisions = [
        (spec_id, scenario_id, owning_slug)
        for spec_id, scenario_id in bindings
        if (owning_slug := reservations.get((spec_id, scenario_id))) is not None and owning_slug != args.slug
    ]

    if not collisions:
        print("OK: no reservation collisions.")
        return 0

    for spec_id, scenario_id, owning_slug in collisions:
        print(
            f"RESERVED: {spec_id} :: {scenario_id} is already reserved by '{owning_slug}' (requested by '{args.slug}')"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

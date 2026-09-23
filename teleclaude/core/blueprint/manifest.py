"""The Blueprint freshness manifest — the signal consumers use to detect staleness.

The manifest sits beside ``graph.json`` and records the ``origin/main`` commit the
graph was built from, when it was generated, and whether generation succeeded. A
consumer compares ``baseline_sha`` to the current main commit and treats a mismatch,
a missing manifest, or a non-``ok`` status as stale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class BlueprintStatus(StrEnum):
    """Outcome of a Blueprint generation attempt."""

    OK = "ok"
    ERROR = "error"


class FreshnessState(StrEnum):
    """How the Blueprint on disk relates to the current main commit.

    ``BEHIND`` means the graph was generated successfully from a known baseline
    that is not the current main, so the gap between the two is a nameable
    commit range. ``UNESTABLISHED`` means that range cannot be named: no
    manifest, a failed generation (whose manifest records the attempted
    baseline, not the graph's), or a main commit that cannot be resolved.
    """

    FRESH = "fresh"
    BEHIND = "behind"
    UNESTABLISHED = "unestablished"


_REASON_MANIFEST_MISSING = "blueprint manifest missing — generate it via a successful integrate"
_REASON_GENERATION_STATUS = "blueprint generation status is '{status}'"
_REASON_MAIN_UNRESOLVED = "current main commit could not be resolved"
_REASON_BEHIND = "blueprint baseline {baseline} is behind main {main}"
_SHORT_SHA_LENGTH = 12


@dataclass(frozen=True)
class BlueprintManifest:
    """Freshness metadata for a generated Blueprint graph."""

    baseline_sha: str
    generated_at: str
    status: BlueprintStatus

    def to_dict(self) -> dict[str, str]:
        return {
            "baseline_sha": self.baseline_sha,
            "generated_at": self.generated_at,
            "status": self.status.value,
        }


@dataclass(frozen=True)
class Freshness:
    """How the Blueprint relates to main, and the reason when it is not fresh."""

    state: FreshnessState
    reason: str


def write_manifest(path: Path, manifest: BlueprintManifest) -> None:
    """Write the manifest as JSON, creating the blueprint directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n")


def read_manifest(path: Path) -> BlueprintManifest | None:
    """Read the manifest, returning ``None`` when it is absent or malformed."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    baseline = raw.get("baseline_sha")
    generated = raw.get("generated_at")
    status_raw = raw.get("status")
    if not (isinstance(baseline, str) and isinstance(generated, str) and isinstance(status_raw, str)):
        return None
    try:
        status = BlueprintStatus(status_raw)
    except ValueError:
        return None
    return BlueprintManifest(baseline_sha=baseline, generated_at=generated, status=status)


def evaluate_freshness(manifest: BlueprintManifest | None, *, current_main_sha: str | None) -> Freshness:
    """Decide whether the Blueprint is fresh against the current main baseline."""
    if manifest is None:
        return Freshness(FreshnessState.UNESTABLISHED, _REASON_MANIFEST_MISSING)
    if manifest.status is not BlueprintStatus.OK:
        return Freshness(
            FreshnessState.UNESTABLISHED,
            _REASON_GENERATION_STATUS.format(status=manifest.status.value),
        )
    if current_main_sha is None:
        return Freshness(FreshnessState.UNESTABLISHED, _REASON_MAIN_UNRESOLVED)
    if manifest.baseline_sha != current_main_sha:
        return Freshness(
            FreshnessState.BEHIND,
            _REASON_BEHIND.format(
                baseline=manifest.baseline_sha[:_SHORT_SHA_LENGTH],
                main=current_main_sha[:_SHORT_SHA_LENGTH],
            ),
        )
    return Freshness(FreshnessState.FRESH, "")

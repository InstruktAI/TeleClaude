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
    """Whether the Blueprint is usable, and the fallback reason when it is not."""

    is_fresh: bool
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
        return Freshness(False, "blueprint manifest missing — generate it via a successful integrate")
    if manifest.status is not BlueprintStatus.OK:
        return Freshness(False, f"blueprint generation status is '{manifest.status.value}'")
    if current_main_sha is None:
        return Freshness(False, "current main commit could not be resolved")
    if manifest.baseline_sha != current_main_sha:
        return Freshness(
            False,
            f"blueprint baseline {manifest.baseline_sha[:12]} is behind main {current_main_sha[:12]}",
        )
    return Freshness(True, "")

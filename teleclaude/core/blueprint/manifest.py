"""Read and validate the freshness manifest inside one published Blueprint generation.

The manifest records the committed revision the graph describes. A
consumer pins the current-generation pointer once, then reads both files from that
immutable directory so a pointer switch cannot pair generations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.core.blueprint._paths import PinnedBlueprintGeneration, pin_current_generation
from teleclaude.core.blueprint.affected import load_graph


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


def read_pinned_manifest(generation: PinnedBlueprintGeneration) -> BlueprintManifest | None:
    """Read the manifest under the same generation pointer a consumer already pinned."""
    return read_manifest(generation.manifest)


def read_published_generation(start: str | Path) -> tuple[PinnedBlueprintGeneration, BlueprintManifest] | None:
    """Pin and validate one complete published graph/manifest pair."""
    generation = pin_current_generation(start)
    if generation is None:
        return None
    manifest = read_pinned_manifest(generation)
    if manifest is None or manifest.status is not BlueprintStatus.OK or load_graph(generation.graph) is None:
        return None
    return generation, manifest

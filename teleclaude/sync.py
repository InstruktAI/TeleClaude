"""Publish a recorded commit through the internal documentation pipeline."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.capabilities import Capabilities, resolve_capabilities
from teleclaude.docs_index import build_all_indexes, build_tier_indexes, reroot_index_document
from teleclaude.docs_lock import DocsLeaseTimeoutError, DocsLockOperation, docs_lease
from teleclaude.docs_publishers import DocsPublisherResolutionError, git_common_root, publisher_resolution
from teleclaude.install.distribution import committed_retired_outputs, distribute_committed, distribute_committed_tiers
from teleclaude.paths import TELECLAUDE_HOME
from teleclaude.resource_validation import (
    _error,
    clear_errors,
    get_errors,
    validate_all_artifacts,
    validate_all_snippets,
    validate_jobs_config,
)

_GIT_EXECUTABLE = "git"
_GIT_VERIFY_ARGS = ("rev-parse", "--verify", "--quiet")
_GIT_HEAD_ARGS = ("rev-parse", "HEAD")
_GIT_MERGE_BASE_ANCESTOR_ARGS = ("merge-base", "--is-ancestor")
_GIT_COMMIT_VERIFY_SUFFIX = "^{commit}"
_GIT_WORKTREE_ADD_ARGS = ("worktree", "add", "--detach")
_GIT_WORKTREE_REMOVE_ARGS = ("worktree", "remove", "--force")
_COMMIT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_SNAPSHOT_DIRECTORY_PREFIX = "teleclaude-publication-"
_SNAPSHOT_SOURCE_DIRECTORY = "source"
_INVALID_COMMIT_ID = "Publication rejected an invalid recorded commit id."
_CANONICAL_OUTPUTS_WRITTEN = "Canonical checkout outputs updated from the recorded commit."
_PUBLICATION_NEXT_SUFFIX = ".publication-next"
_STATE_DIRECTORY = ".teleclaude"
_PUBLICATION_DIRECTORY = "publication"
_PUBLISHED_GENERATION_FILENAME = "published_generation"
_UNFINISHED_PUBLICATION_FILENAME = "unfinished_publication"
_PUBLICATION_SUPERSEDED = (
    "Publication superseded: a newer generation is already published; deployed output is unchanged."
)
_PUBLICATION_BLOCKED_BY_UNFINISHED = (
    "Publication blocked: an unfinished publication of {unfinished} must complete first."
)
_PUBLICATION_GENERATION_UNSEEDED = (
    "Publication refused: no published generation is recorded; publish the current tip to seed it."
)
_PUBLICATION_UNRESOLVABLE_STATE = "Publication refused: could not resolve ancestry between {candidate} and {other}."


class PublicationOutcome(StrEnum):
    """The terminal disposition of one recorded-commit publication attempt."""

    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class PublicationReason(StrEnum):
    """The closed vocabulary of reasons behind a `PublicationOutcome`."""

    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    BLOCKED_BY_UNFINISHED = "blocked_by_unfinished"
    GENERATION_UNSEEDED = "generation_unseeded"
    UNRESOLVABLE_STATE = "unresolvable_state"
    STATE_UNREADABLE = "state_unreadable"
    INVALID_RECORDED_COMMIT = "invalid_recorded_commit"
    VALIDATION_FAILED = "validation_failed"
    LEASE_UNAVAILABLE = "lease_unavailable"
    PUBLICATION_ERROR = "publication_error"


@dataclass(frozen=True)
class PublicationResult:
    """The outcome of a publication attempt plus the generation facts it decided against."""

    outcome: PublicationOutcome
    reason: PublicationReason
    published_generation: str | None
    unfinished_publication: str | None


class _UnresolvableAncestryError(Exception):
    """Raised when git cannot resolve an ancestry comparison between two commit ids."""

    def __init__(self, candidate: str, other: str) -> None:
        super().__init__(candidate, other)
        self.candidate = candidate
        self.other = other


def publish_recorded_commit(project_root: Path, after_sha: str) -> PublicationResult:
    """Publish one validated recorded commit, deciding supersession before any output write."""
    if _COMMIT_ID_PATTERN.fullmatch(after_sha) is None:
        print(_INVALID_COMMIT_ID, file=sys.stderr)
        return _rejected(PublicationReason.INVALID_RECORDED_COMMIT)
    canonical_root = git_common_root(project_root)
    try:
        resolved = subprocess.run(
            [_GIT_EXECUTABLE, *_GIT_VERIFY_ARGS, after_sha + _GIT_COMMIT_VERIFY_SUFFIX],
            cwd=canonical_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return _rejected(PublicationReason.INVALID_RECORDED_COMMIT)
    if resolved.returncode != 0 or resolved.stdout.strip() != after_sha:
        print(_INVALID_COMMIT_ID, file=sys.stderr)
        return _rejected(PublicationReason.INVALID_RECORDED_COMMIT)

    published_generation: str | None = None
    unfinished_publication: str | None = None
    try:
        with docs_lease(DocsLockOperation.SYNCHRONIZATION):
            try:
                published_generation, unfinished_publication = _read_publication_state(canonical_root)
            except OSError as exc:
                print(str(exc), file=sys.stderr)
                return _rejected(PublicationReason.STATE_UNREADABLE)
            try:
                terminal = _decide_supersession(canonical_root, after_sha, published_generation, unfinished_publication)
            except _UnresolvableAncestryError as exc:
                print(
                    _PUBLICATION_UNRESOLVABLE_STATE.format(candidate=exc.candidate, other=exc.other),
                    file=sys.stderr,
                )
                return PublicationResult(
                    PublicationOutcome.FAILED,
                    PublicationReason.UNRESOLVABLE_STATE,
                    published_generation,
                    unfinished_publication,
                )
            if terminal is not None:
                return PublicationResult(terminal[0], terminal[1], published_generation, unfinished_publication)
            return _execute_publication(canonical_root, after_sha, published_generation, unfinished_publication)
    except DocsLeaseTimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return PublicationResult(PublicationOutcome.FAILED, PublicationReason.LEASE_UNAVAILABLE, None, None)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return PublicationResult(
            PublicationOutcome.FAILED, PublicationReason.PUBLICATION_ERROR, published_generation, unfinished_publication
        )


def _rejected(reason: PublicationReason) -> PublicationResult:
    """Build a failed result for a reason whose exit precedes any state read."""
    return PublicationResult(PublicationOutcome.FAILED, reason, None, None)


def _decide_supersession(
    canonical_root: Path,
    after_sha: str,
    published_generation: str | None,
    unfinished_publication: str | None,
) -> tuple[PublicationOutcome, PublicationReason] | None:
    """Apply the superseded, blocked, and unseeded rules in order.

    Returns the terminal outcome and reason, or ``None`` when publication should proceed.
    """
    if published_generation is not None and _is_strict_ancestor(canonical_root, after_sha, published_generation):
        print(_PUBLICATION_SUPERSEDED)
        return PublicationOutcome.SUPERSEDED, PublicationReason.SUPERSEDED

    unfinished_is_published = (
        published_generation is not None
        and unfinished_publication is not None
        and _is_ancestor(canonical_root, unfinished_publication, published_generation)
    )
    if (
        unfinished_publication is not None
        and not unfinished_is_published
        and _is_strict_ancestor(canonical_root, after_sha, unfinished_publication)
    ):
        print(_PUBLICATION_BLOCKED_BY_UNFINISHED.format(unfinished=unfinished_publication))
        return PublicationOutcome.FAILED, PublicationReason.BLOCKED_BY_UNFINISHED

    if published_generation is None:
        head = _canonical_head(canonical_root)
        if after_sha != head and after_sha != unfinished_publication:
            print(_PUBLICATION_GENERATION_UNSEEDED)
            return PublicationOutcome.FAILED, PublicationReason.GENERATION_UNSEEDED

    return None


def _execute_publication(
    canonical_root: Path,
    after_sha: str,
    published_generation: str | None,
    unfinished_publication: str | None,
) -> PublicationResult:
    """Validate, claim, install, and distribute one recorded commit."""
    directory = _publication_directory(canonical_root)
    published_path = directory / _PUBLISHED_GENERATION_FILENAME
    unfinished_path = directory / _UNFINISHED_PUBLICATION_FILENAME

    def validation_failed() -> PublicationResult:
        return PublicationResult(
            PublicationOutcome.FAILED, PublicationReason.VALIDATION_FAILED, published_generation, unfinished_publication
        )

    def published() -> PublicationResult:
        _write_publication_id(published_path, after_sha)
        _remove_unfinished_publication(unfinished_path)
        return PublicationResult(
            PublicationOutcome.PUBLISHED, PublicationReason.PUBLISHED, published_generation, unfinished_publication
        )

    with _recorded_snapshot(canonical_root, after_sha) as snapshot_root:
        capabilities = resolve_capabilities(snapshot_root)
        if not capabilities.is_target:
            if _is_platform_home(canonical_root):
                # This validates every participating tier's snippet sources, installs
                # both catalogs of each tier (docs/global and docs/local) at its home in
                # the canonical home checkout, then composes only the published half
                # into the deployed corpus.
                tier_findings = _collect_tier_source_findings(snapshot_root)
                if tier_findings:
                    return validation_failed()
                _write_publication_id(unfinished_path, after_sha)
                written_tiers = build_tier_indexes(snapshot_root)
                tier_index_outputs = _reroot_written_outputs(written_tiers, snapshot_root, canonical_root)
                _install_canonical_files(snapshot_root, canonical_root, tier_index_outputs)
                distribute_committed_tiers(snapshot_root)
                return published()
            return PublicationResult(
                PublicationOutcome.PUBLISHED, PublicationReason.PUBLISHED, published_generation, unfinished_publication
            )
        findings = _collect_source_findings(snapshot_root, capabilities)
        if findings:
            return validation_failed()
        _write_publication_id(unfinished_path, after_sha)
        written = build_all_indexes(snapshot_root) if capabilities.docs else []
        index_outputs = _reroot_written_outputs(written, snapshot_root, canonical_root)
        _install_canonical_files(snapshot_root, canonical_root, index_outputs)
        distribution_outputs = distribute_committed(
            snapshot_root,
            canonical_root,
            agents_enabled=capabilities.agents,
            docs_enabled=capabilities.docs,
        )
        retired_outputs = committed_retired_outputs(snapshot_root) if capabilities.docs else []
        if distribution_outputs or retired_outputs:
            _install_canonical_files(
                snapshot_root,
                canonical_root,
                [
                    *((source, source.read_bytes()) for source in distribution_outputs),
                    *((retired, None) for retired in retired_outputs),
                ],
            )
        return published()


def _is_platform_home(canonical_root: Path) -> bool:
    """Return whether the published repository is the machine's platform home."""
    return canonical_root.expanduser().resolve() == TELECLAUDE_HOME.expanduser().resolve()


def _reroot_written_outputs(
    written: list[Path], snapshot_root: Path, canonical_root: Path
) -> list[tuple[Path, bytes | None]]:
    """Pair each snapshot-written index file with its canonical-rooted bytes."""
    return [
        (
            source,
            reroot_index_document(source.read_text(encoding="utf-8"), snapshot_root, canonical_root).encode("utf-8")
            if source.is_file()
            else None,
        )
        for source in written
    ]


@contextmanager
def _recorded_snapshot(canonical_root: Path, after_sha: str) -> Iterator[Path]:
    """Materialize a recorded source tree with access to the checkout's Python environment."""
    with tempfile.TemporaryDirectory(prefix=_SNAPSHOT_DIRECTORY_PREFIX) as temp_dir:
        snapshot_root = Path(temp_dir) / _SNAPSHOT_SOURCE_DIRECTORY
        subprocess.run(
            [_GIT_EXECUTABLE, *_GIT_WORKTREE_ADD_ARGS, str(snapshot_root), after_sha],
            cwd=canonical_root,
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            canonical_venv = canonical_root / ".venv"
            if canonical_venv.exists():
                (snapshot_root / ".venv").symlink_to(canonical_venv, target_is_directory=True)
            yield snapshot_root
        finally:
            subprocess.run(
                [_GIT_EXECUTABLE, *_GIT_WORKTREE_REMOVE_ARGS, str(snapshot_root)],
                cwd=canonical_root,
                check=False,
                capture_output=True,
                text=True,
            )


def _canonical_head(canonical_root: Path) -> str | None:
    """Read canonical HEAD as a full object id."""
    result = subprocess.run(
        [_GIT_EXECUTABLE, *_GIT_HEAD_ARGS],
        cwd=canonical_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _is_ancestor(canonical_root: Path, candidate: str, other: str) -> bool:
    """Return whether candidate is an ancestor of other, or equal to it."""
    result = subprocess.run(
        [_GIT_EXECUTABLE, *_GIT_MERGE_BASE_ANCESTOR_ARGS, candidate, other],
        cwd=canonical_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode in (0, 1):
        return result.returncode == 0
    raise _UnresolvableAncestryError(candidate, other)


def _is_strict_ancestor(canonical_root: Path, candidate: str, other: str) -> bool:
    """Return whether candidate is a strict (non-equal) ancestor of other."""
    return candidate != other and _is_ancestor(canonical_root, candidate, other)


def _publication_directory(canonical_root: Path) -> Path:
    """Return the gitignored directory holding this checkout's publication state."""
    return canonical_root / _STATE_DIRECTORY / _PUBLICATION_DIRECTORY


def _read_publication_state(canonical_root: Path) -> tuple[str | None, str | None]:
    """Read the published generation and the unfinished publication, or None each when absent."""
    directory = _publication_directory(canonical_root)
    return (
        _read_publication_id(directory / _PUBLISHED_GENERATION_FILENAME),
        _read_publication_id(directory / _UNFINISHED_PUBLICATION_FILENAME),
    )


def _read_publication_id(path: Path) -> str | None:
    """Read one full commit id from a publication-state file, or None when it is absent."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def _write_publication_id(path: Path, commit_id: str) -> None:
    """Atomically replace one publication-state file with a full commit id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + _PUBLICATION_NEXT_SUFFIX)
    temporary.write_text(commit_id, encoding="utf-8")
    os.replace(temporary, path)


def _remove_unfinished_publication(path: Path) -> None:
    """Clear the unfinished-publication claim after a completed publication."""
    path.unlink(missing_ok=True)


def _install_canonical_files(
    snapshot_root: Path,
    canonical_root: Path,
    outputs: list[tuple[Path, bytes | None]],
) -> None:
    """Atomically install every provided snapshot output onto the canonical checkout."""
    staged: list[tuple[Path, Path | None]] = []
    for source, payload in outputs:
        destination = canonical_root / source.relative_to(snapshot_root)
        previous_payload = destination.read_bytes() if destination.is_file() else None
        if payload is not None:
            if payload == previous_payload:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + _PUBLICATION_NEXT_SUFFIX)
            temporary.write_bytes(payload)
            staged.append((destination, temporary))
        elif previous_payload is not None:
            staged.append((destination, None))
    for destination, temporary in staged:
        if temporary is None:
            destination.unlink(missing_ok=True)
        else:
            os.replace(temporary, destination)
    print(_CANONICAL_OUTPUTS_WRITTEN)


def _group_findings(findings: list[dict[str, str]]) -> dict[str, dict[str, list[str]]]:
    """Group validation findings by code and reason."""
    grouped: dict[str, dict[str, list[str]]] = {}
    for finding in findings:
        path = finding.get("path", "")
        if not path:
            continue
        code = finding["code"]
        reason = finding.get("reason", "")
        grouped.setdefault(code, {}).setdefault(reason, []).append(path)
    return grouped


def _collect_findings_via(
    project_root: Path,
    validate_in_scope: Callable[[], list[str]],
    *,
    extra: Callable[[], list[str]] | None = None,
) -> list[str]:
    """Clear prior findings, run a validation call, print and return every finding.

    ``validate_in_scope`` runs inside ``publisher_resolution`` and returns any
    error strings it collects directly; findings routed through the
    ``_error``/``get_errors`` mechanism are read afterward. ``extra``, when
    given, runs outside ``publisher_resolution`` before findings are read —
    the ordinary source validator's jobs-config check needs this; the tier
    validator has no equivalent step.
    """
    clear_errors()
    errors: list[str] = []
    try:
        with publisher_resolution(project_root):
            errors.extend(validate_in_scope())
    except DocsPublisherResolutionError as exc:
        _error("snippet_global_source_resolution_failed", path=str(project_root), reason=str(exc))
    if extra is not None:
        errors.extend(extra())
    findings = get_errors()
    if findings:
        _print_findings(findings, quiet=False)
        errors.extend(_format_finding(finding) for finding in findings)
    for error in errors:
        print(error)
    return errors


def _collect_source_findings(project_root: Path, capabilities: Capabilities) -> list[str]:
    """Run the snippet, artifact, and jobs-config validators; print and return findings."""

    def validate_in_scope() -> list[str]:
        if capabilities.docs:
            validate_all_snippets(project_root)
        return validate_all_artifacts(project_root) if capabilities.agents else []

    return _collect_findings_via(project_root, validate_in_scope, extra=lambda: validate_jobs_config(project_root))


def _collect_tier_source_findings(platform_home_snapshot: Path) -> list[str]:
    """Run tier snippet-source validation against the platform-home snapshot.

    The home is not a registered target and carries no project-shaped snippet
    root of its own, so the ordinary walk this call also reaches is a no-op;
    only the declared, participating tier roots under it are validated.
    """

    def validate_in_scope() -> list[str]:
        validate_all_snippets(platform_home_snapshot, tier_home=platform_home_snapshot)
        return []

    return _collect_findings_via(platform_home_snapshot, validate_in_scope)


def _format_finding(finding: dict[str, str]) -> str:
    """Format one validation finding without dropping diagnostic fields."""
    extras = ", ".join(f"{key}={value}" for key, value in finding.items() if key not in {"code", "path"})
    if extras:
        return f"{finding['code']}: {finding['path']} ({extras})"
    return f"{finding['code']}: {finding['path']}"


def _print_findings(findings: list[dict[str, str]], *, quiet: bool) -> None:
    """Print validation findings grouped by code and reason."""
    if not findings:
        return
    print(f"Validation findings: {len(findings)}")
    if quiet:
        return
    for code, reason_groups in _group_findings(findings).items():
        no_reason = reason_groups.get("", [])
        if no_reason:
            print(f"{code}:")
            for path in no_reason:
                print(f"- {path}")
        for reason, paths in reason_groups.items():
            if not reason:
                continue
            print(f"{code}/{reason}:")
            for path in paths:
                print(f"- {path}")

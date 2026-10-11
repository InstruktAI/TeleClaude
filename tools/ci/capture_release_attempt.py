"""Capture the serialized release source and the newest completed baseline."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

import httpx
from pydantic import ValidationError

from teleclaude.git import GitCommandError, Repo
from tools.ci.gha import append_output
from tools.release.attempt import (
    AttemptIdentity,
    PublishedRelease,
    ReleaseDecisionMode,
    capture_attempt,
    load_release_provenance,
    normalize_stable_version,
    select_completed_release,
    stable_version_is_newer,
)
from tools.release.github_artifacts import (
    ExpectedWorkflowAttempt,
    GitHubArtifactClient,
    GitHubArtifactError,
    WorkflowEvent,
)
from tools.release.project_metadata import normalized_tree_digest

_OUTPUT_ARGUMENT = "--output-directory"
_REPOSITORY_ENVIRONMENT = "GITHUB_REPOSITORY"
_RUN_ENVIRONMENT = "GITHUB_RUN_ID"
_RUN_ATTEMPT_ENVIRONMENT = "GITHUB_RUN_ATTEMPT"
_EVENT_ENVIRONMENT = "GITHUB_EVENT_NAME"
_REF_ENVIRONMENT = "GITHUB_REF"
_TOKEN_ENVIRONMENT = "GH_TOKEN"
_OPERATION_ENVIRONMENT = "RELEASE_OPERATION"
_VERSION_ENVIRONMENT = "RELEASE_VERSION"
_WORKFLOW_PATH = ".github/workflows/release.yaml"
_MAIN_REF = "refs/heads/main"
_REMOTE_MAIN_REF = "refs/remotes/origin/main"
_REMOTE_NAME = "origin"
_REMOTE_TAG_PREFIX = "refs/tags/"
_GIT_CONFIG_COUNT = "GIT_CONFIG_COUNT"
_GIT_CONFIG_KEY = "GIT_CONFIG_KEY_0"
_GIT_CONFIG_VALUE = "GIT_CONFIG_VALUE_0"
_GIT_PROMPT = "GIT_TERMINAL_PROMPT"
_GITHUB_HTTP_CONFIG = "http.https://github.com/.extraheader"
_UTF8 = "utf-8"
_JSON_INDENT = 2
_NEWLINE = "\n"
_EMPTY = ""
_STATUS_FILENAME = "capture-state.json"
_ATTEMPT_FILENAME = "attempt.json"
_PROVENANCE_FILENAME = "release-provenance.json"
_STATUS_OUTPUT = "capture_status"
_SOURCE_OUTPUT = "source_sha"
_BASELINE_OUTPUT = "baseline_tag"
_BASELINE_SHA_OUTPUT = "baseline_sha"
_LATEST_RELEASE_OUTPUT = "latest_completed_tag"
_DECISION_MODE_OUTPUT = "decision_mode"
_REQUESTED_VERSION_OUTPUT = "requested_version"
_READY = "ready"
_AUTOMATIC = "automatic"
_BASELINE_UNAVAILABLE = "baseline_unavailable"
_SCHEDULED_OPERATION = "scheduled"
_NO_CHANGE = "no_change"
_INVALID_INPUT = "The release run identity or operation is invalid."
_CHECKOUT_DIRTY = "Source capture requires a clean workflow checkout."
_ATTEMPT_OUTPUT_EXISTS = "Release capture output requires a new directory."
_REPOSITORY_MISMATCH = "The release workflow repository identity does not match its checkout."
_VERSION_NOT_NEWER = "The supplied release version must be newer than the completed release baseline."
_VERSION_TAG_CONFLICT = "The supplied release version already has a Git tag."
_ALLOWED_OPERATIONS = frozenset({"scheduled", "dry-run", "release"})
_EXPECTED_FILES = ("attempt.json", "capture-state.json")


def capture_release(
    repository_root: Path,
    output_directory: Path,
    repository: str,
    run_id: str,
    run_attempt: int,
    event: WorkflowEvent,
    ref: str,
    operation: str,
    token: str,
    *,
    requested_version: str | None = None,
    github_transport: httpx.BaseTransport | None = None,
) -> tuple[str, AttemptIdentity | None]:
    """Read live GitHub release state after concurrency admission and capture source S."""
    if operation not in _ALLOWED_OPERATIONS or not run_id.isdigit() or run_attempt < 1 or not token:
        raise ValueError(_INVALID_INPUT)
    if operation == _SCHEDULED_OPERATION and requested_version is not None:
        raise ValueError(_INVALID_INPUT)
    manual_version = normalize_stable_version(requested_version) if requested_version is not None else None
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError(_ATTEMPT_OUTPUT_EXISTS)
    if ref != _MAIN_REF:
        raise ValueError(_INVALID_INPUT)
    repo = Repo(repository_root)
    if repo.is_dirty(untracked_files=True):
        raise ValueError(_CHECKOUT_DIRTY)
    git_environment = _git_environment(token)
    repo.git.fetch(_REMOTE_NAME, _MAIN_REF + ":" + _REMOTE_MAIN_REF, env=git_environment)
    expected = ExpectedWorkflowAttempt(
        repository=repository,
        workflow_path=_WORKFLOW_PATH,
        event=event,
        ref=ref,
        run_id=int(run_id),
        run_attempt=run_attempt,
    )
    with GitHubArtifactClient(token, transport=github_transport) as client:
        client.get_workflow_attempt(expected)
        releases = [
            PublishedRelease(
                release_id=item.id,
                tag_name=item.tag_name,
                is_draft=item.draft,
                is_prerelease=item.prerelease,
                published_at=item.published_at,
            )
            for item in client.list_releases(repository)
        ]
        baseline = _latest_completed_release(releases)
        latest_completed_tag = baseline.tag_name if baseline is not None else None
        if baseline is not None:
            repo.git.fetch(
                _REMOTE_NAME,
                _REMOTE_TAG_PREFIX + baseline.tag_name + ":" + _REMOTE_TAG_PREFIX + baseline.tag_name,
                env=git_environment,
            )
        has_supported_baseline = baseline is not None and _has_current_provenance(repo, baseline.tag_name)
        if manual_version is not None:
            if baseline is not None and not has_supported_baseline:
                raise ValueError(_INVALID_INPUT)
            if baseline is not None and not stable_version_is_newer(manual_version, baseline.tag_name):
                raise ValueError(_VERSION_NOT_NEWER)
            if _remote_tag_exists(repo, manual_version, git_environment):
                raise ValueError(_VERSION_TAG_CONFLICT)
            attempt = capture_attempt(
                repo,
                repository=repository,
                workflow_run_id=run_id,
                workflow_run_attempt=run_attempt,
                baseline_tag=baseline.tag_name if baseline is not None else None,
                decision_mode=ReleaseDecisionMode.MANUAL,
                requested_version=manual_version,
            )
            status = _READY
        elif baseline is None or not has_supported_baseline:
            output_directory.mkdir(parents=True)
            _write_state(output_directory, _BASELINE_UNAVAILABLE, None, latest_completed_tag)
            append_output(_STATUS_OUTPUT, _BASELINE_UNAVAILABLE)
            append_output(_DECISION_MODE_OUTPUT, _AUTOMATIC)
            append_output(_BASELINE_SHA_OUTPUT, _EMPTY)
            append_output(_LATEST_RELEASE_OUTPUT, latest_completed_tag or _EMPTY)
            return _BASELINE_UNAVAILABLE, None
        else:
            attempt = capture_attempt(
                repo,
                repository=repository,
                workflow_run_id=run_id,
                workflow_run_attempt=run_attempt,
                baseline_tag=baseline.tag_name,
            )
            status = (
                _NO_CHANGE
                if normalized_tree_digest(repo, attempt.source_sha)
                == normalized_tree_digest(repo, attempt.baseline_sha or _EMPTY)
                else _READY
            )
    repo.git.checkout("--detach", attempt.source_sha)
    output_directory.mkdir(parents=True)
    (output_directory / _ATTEMPT_FILENAME).write_text(
        attempt.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )
    _write_state(output_directory, status, attempt, latest_completed_tag)
    append_output(_STATUS_OUTPUT, status)
    append_output(_DECISION_MODE_OUTPUT, attempt.decision_mode.value)
    append_output(_SOURCE_OUTPUT, attempt.source_sha)
    append_output(_BASELINE_OUTPUT, attempt.baseline_tag or _EMPTY)
    append_output(_BASELINE_SHA_OUTPUT, attempt.baseline_sha or _EMPTY)
    append_output(_REQUESTED_VERSION_OUTPUT, attempt.requested_version or _EMPTY)
    append_output(_LATEST_RELEASE_OUTPUT, latest_completed_tag or _EMPTY)
    return status, attempt


def _latest_completed_release(releases: list[PublishedRelease]) -> PublishedRelease | None:
    """Select a published semantic release, representing an empty history as readiness."""
    try:
        return select_completed_release(releases)
    except ValueError:
        return None


def _remote_tag_exists(repo: Repo, tag: str, environment: Mapping[str, str]) -> bool:
    """Refuse a new manual decision when its target tag already exists remotely."""
    return bool(str(repo.git.ls_remote(_REMOTE_NAME, _REMOTE_TAG_PREFIX + tag, env=environment)).strip())


def _has_current_provenance(repo: Repo, tag: str) -> bool:
    """Require a completed release to carry readable current or migratable provenance."""
    try:
        value = str(repo.git.show(f"{tag}:{_PROVENANCE_FILENAME}")).encode(_UTF8)
        load_release_provenance(value, tag)
    except (GitCommandError, json.JSONDecodeError, ValueError):
        return False
    return True


def _write_state(
    directory: Path,
    status: str,
    attempt: AttemptIdentity | None,
    latest_completed_tag: str | None,
) -> None:
    """Write the run's exact source/baseline admission state for downstream gates."""
    state = {
        "status": status,
        "attempt": attempt.model_dump(mode="json") if attempt is not None else None,
        "latest_completed_tag": latest_completed_tag,
    }
    (directory / _STATUS_FILENAME).write_text(
        json.dumps(state, ensure_ascii=True, indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )


def _git_environment(token: str) -> dict[str, str]:
    """Authenticate checkout-origin fetches without persisting a credential helper."""
    environment = os.environ.copy()
    credential = base64.b64encode(("x-access-token:" + token).encode(_UTF8)).decode("ascii")
    environment[_GIT_CONFIG_COUNT] = "1"
    environment[_GIT_CONFIG_KEY] = _GITHUB_HTTP_CONFIG
    environment[_GIT_CONFIG_VALUE] = "AUTHORIZATION: basic " + credential
    environment[_GIT_PROMPT] = "0"
    return environment


def main(argv: list[str] | None = None) -> int:
    """Capture an attempt only after workflow concurrency has admitted this run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_OUTPUT_ARGUMENT, type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        repository = os.environ.get(_REPOSITORY_ENVIRONMENT, _EMPTY)
        event_value = os.environ.get(_EVENT_ENVIRONMENT, _EMPTY)
        operation = os.environ.get(_OPERATION_ENVIRONMENT, _EMPTY)
        requested_version = os.environ.get(_VERSION_ENVIRONMENT) or None
        status, _attempt = capture_release(
            Path.cwd(),
            args.output_directory,
            repository,
            os.environ.get(_RUN_ENVIRONMENT, _EMPTY),
            int(os.environ.get(_RUN_ATTEMPT_ENVIRONMENT, "0")),
            WorkflowEvent(event_value),
            os.environ.get(_REF_ENVIRONMENT, _EMPTY),
            operation,
            os.environ.get(_TOKEN_ENVIRONMENT, _EMPTY),
            requested_version=requested_version,
        )
        print(status)
    except (OSError, ValueError, RuntimeError, GitHubArtifactError, ValidationError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Capture the serialized release source and the newest completed baseline."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from teleclaude.git import GitCommandError, Repo
from tools.ci.gha import append_output
from tools.release.attempt import (
    AttemptIdentity,
    PublishedRelease,
    capture_attempt,
    select_completed_release,
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
_WORKFLOW_PATH = ".github/workflows/release.yaml"
_MAIN_REF = "refs/heads/main"
_REMOTE_MAIN_REF = "refs/remotes/origin/main"
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
_SCHEMA_VERSION = "schema_version"
_PROVENANCE_SCHEMA_VERSION = 1
_STATUS_OUTPUT = "capture_status"
_SOURCE_OUTPUT = "source_sha"
_BASELINE_OUTPUT = "baseline_tag"
_LATEST_RELEASE_OUTPUT = "latest_completed_tag"
_READY = "ready"
_BOOTSTRAP = "bootstrap"
_BOOTSTRAP_READY = "bootstrap_ready"
_NO_CHANGE = "no_change"
_INVALID_INPUT = "The release run identity or operation is invalid."
_CHECKOUT_DIRTY = "Source capture requires a clean workflow checkout."
_ATTEMPT_OUTPUT_EXISTS = "Release capture output requires a new directory."
_REPOSITORY_MISMATCH = "The release workflow repository identity does not match its checkout."
_ALLOWED_OPERATIONS = frozenset({"scheduled", "dry-run", "release", "bootstrap"})
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
    github_transport: httpx.BaseTransport | None = None,
) -> tuple[str, AttemptIdentity | None]:
    """Read live GitHub release state after concurrency admission and capture source S."""
    if operation not in _ALLOWED_OPERATIONS or not run_id.isdigit() or run_attempt < 1 or not token:
        raise ValueError(_INVALID_INPUT)
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError(_ATTEMPT_OUTPUT_EXISTS)
    if ref != _MAIN_REF:
        raise ValueError(_INVALID_INPUT)
    repo = Repo(repository_root)
    if repo.is_dirty(untracked_files=True):
        raise ValueError(_CHECKOUT_DIRTY)
    git_environment = _git_environment(token)
    repo.git.fetch("origin", _MAIN_REF + ":" + _REMOTE_MAIN_REF, env=git_environment)
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
        if operation == "bootstrap":
            if baseline is not None and _has_current_provenance(repo, baseline.tag_name):
                raise ValueError(_INVALID_INPUT)
            attempt = capture_attempt(
                repo,
                repository=repository,
                workflow_run_id=run_id,
                workflow_run_attempt=run_attempt,
                baseline_tag=None,
                bootstrap=True,
            )
            status = _BOOTSTRAP
        elif baseline is None or not _has_current_provenance(repo, baseline.tag_name):
            output_directory.mkdir(parents=True)
            _write_state(output_directory, _BOOTSTRAP_READY, None, latest_completed_tag)
            append_output(_STATUS_OUTPUT, _BOOTSTRAP_READY)
            append_output(_LATEST_RELEASE_OUTPUT, latest_completed_tag or _EMPTY)
            return _BOOTSTRAP_READY, None
        else:
            git_env = git_environment
            repo.git.fetch(
                "origin",
                "refs/tags/" + baseline.tag_name + ":refs/tags/" + baseline.tag_name,
                env=git_env,
            )
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
    append_output(_SOURCE_OUTPUT, attempt.source_sha)
    append_output(_BASELINE_OUTPUT, attempt.baseline_tag or _EMPTY)
    append_output(_LATEST_RELEASE_OUTPUT, latest_completed_tag or _EMPTY)
    return status, attempt


def _latest_completed_release(releases: list[PublishedRelease]) -> PublishedRelease | None:
    """Select a published semantic release, representing an empty history as readiness."""
    try:
        return select_completed_release(releases)
    except ValueError:
        return None


def _has_current_provenance(repo: Repo, tag: str) -> bool:
    """Require the published candidate to establish the new source-provenance protocol."""
    try:
        value = json.loads(str(repo.git.show(f"{tag}:{_PROVENANCE_FILENAME}")))
    except (GitCommandError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and value.get(_SCHEMA_VERSION) == _PROVENANCE_SCHEMA_VERSION


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
        )
        print(status)
    except (OSError, ValueError, RuntimeError, GitHubArtifactError, ValidationError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

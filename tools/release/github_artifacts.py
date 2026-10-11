"""Trusted GitHub Actions metadata and bounded artifact transport for release inspection."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Self
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

_API_ROOT = "https://api.github.com"
_API_VERSION = "2026-03-10"
_ACCEPT_HEADER = "Accept"
_ACCEPT_VALUE = "application/vnd.github+json"
_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "
_API_VERSION_HEADER = "X-GitHub-Api-Version"
_USER_AGENT_HEADER = "User-Agent"
_USER_AGENT = "TeleClaude-release-inspector"
_PER_PAGE = 100
_MAX_ARTIFACT_PAGES = 50
_MAX_ARTIFACTS = _PER_PAGE * _MAX_ARTIFACT_PAGES
_MAX_RELEASE_RUN_PAGES = 10
_MAX_RELEASE_RUNS = _PER_PAGE * _MAX_RELEASE_RUN_PAGES
_MAX_RELEASE_PAGES = 20
_MAX_RELEASES = _PER_PAGE * _MAX_RELEASE_PAGES
_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_UNPACKED_BYTES = 1024 * 1024 * 1024
_MAX_ARCHIVE_FILES = 20_000
_MAX_RELEASE_BODY_BYTES = 256 * 1024
_ARCHIVE_CHUNK_BYTES = 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 30.0
_DOWNLOAD_TIMEOUT_SECONDS = 120.0
_SHA256_PREFIX = "sha256:"
_SHA256_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PATH_SEPARATOR = "/"
_RUN_ATTEMPT_SEPARATOR = "-"
_RUN_ATTEMPT_MARKER = "attempt"
_RELEASE_WORKFLOW_PATH = ".github/workflows/release.yaml"
_DEFAULT_RELEASE_REF = "refs/heads/main"
_ARTIFACTS_KEY = "artifacts"
_WORKFLOW_RUNS_ROUTE = "/repos/{repository}/actions/runs/{run_id}/attempts/{attempt}"
_RUN_ARTIFACTS_ROUTE = "/repos/{repository}/actions/runs/{run_id}/artifacts"
_WORKFLOW_RUN_LIST_ROUTE = "/repos/{repository}/actions/workflows/{workflow_file}/runs"
_REPOSITORY_ARTIFACTS_ROUTE = "/repos/{repository}/actions/artifacts"
_ARTIFACT_DOWNLOAD_ROUTE = "/repos/{repository}/actions/artifacts/{artifact_id}/zip"
_RELEASE_TAG_ROUTE = "/repos/{repository}/releases/tags/{tag}"
_RELEASE_CREATE_ROUTE = "/repos/{repository}/releases"
_RELEASE_LIST_ROUTE = "/repos/{repository}/releases"
_REQUEST_FAILED = "GitHub Actions metadata request failed."
_INVALID_RESPONSE = "GitHub Actions returned invalid release metadata."
_WORKFLOW_PROVENANCE_MISMATCH = "The artifact producer does not match the expected workflow attempt."
_ARTIFACT_IDENTITY_MISMATCH = "The artifact identity does not match the selected workflow attempt."
_ARTIFACT_UPLOAD_UNCONFIRMED = "The finalized artifact metadata does not match its uploaded identity."
_ARTIFACT_DIGEST_MISSING = "The selected artifact has no authenticated SHA-256 digest."
_ARTIFACT_SIZE_EXCEEDED = "The selected artifact exceeds the configured archive size bound."
_ARTIFACT_LIST_LIMIT = "GitHub artifact history exceeds the bounded lookup limit."
_ARTIFACT_SET_MISMATCH = "The artifact archive inventory does not match its declared contract."
_ARTIFACT_PATH_UNSAFE = "The artifact archive contains an unsafe path or link."
_ARTIFACT_CONTENT_LIMIT = "The artifact archive exceeds its bounded content limits."
_ARTIFACT_DOWNLOAD_FAILED = "The selected artifact could not be downloaded safely."
_DESTINATION_MUST_BE_NEW = "Artifact extraction requires a new controller-owned destination."
_HTTPS_SCHEME = "https"
_REDIRECT_STATUS = 302
_SUCCESS_STATUS = 200
_NOT_FOUND_STATUS = 404
_CREATED_STATUS = 201
_UTF8_ENCODING = "utf-8"
_ASCII_ENCODING = "ascii"
_EMPTY = ""
_DOT = "."
_PARENT = ".."
_STATUS_CODE = "status_code"
_WORKFLOW_FILE = "release.yaml"
_MAIN_BRANCH = "main"
_BRANCH_QUERY_KEY = "branch"
_EVENT_QUERY_KEY = "event"
_MAX_BODY_BYTES = "GitHub release notes exceed their configured limit."
_RELEASE_CONFLICT = "GitHub release metadata does not match the proved candidate."


class WorkflowEvent(StrEnum):
    """Events admitted to the release workflow's inspection protocol."""

    SCHEDULE = "schedule"
    WORKFLOW_DISPATCH = "workflow_dispatch"


class GitHubRecord(BaseModel):
    """GitHub response model base that reads only the fields this boundary owns."""

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class GitHubRepository(GitHubRecord):
    """Repository identity returned by the Actions API."""

    id: int
    full_name: str


class WorkflowAttempt(GitHubRecord):
    """Authenticated metadata for one concrete workflow run attempt."""

    id: int
    run_attempt: int
    path: str
    event: str
    ref: str
    head_sha: str
    workflow_id: int
    repository: GitHubRepository


class ArtifactWorkflow(GitHubRecord):
    """Workflow provenance embedded in GitHub artifact metadata."""

    id: int
    repository_id: int
    head_repository_id: int
    head_sha: str


class ArtifactMetadata(GitHubRecord):
    """One immutable GitHub Actions artifact and its API-provided digest."""

    id: int
    name: str
    size_in_bytes: int
    expired: bool
    digest: str | None
    created_at: datetime
    workflow_run: ArtifactWorkflow


class ArtifactPage(GitHubRecord):
    """Paginated repository-artifact response."""

    total_count: int
    artifacts: list[ArtifactMetadata]


class WorkflowRunSummary(GitHubRecord):
    """List-endpoint identity for one release workflow attempt."""

    id: int
    run_attempt: int
    path: str
    event: str
    ref: str
    head_sha: str


class WorkflowRunPage(GitHubRecord):
    """Paginated workflow-run response."""

    total_count: int
    workflow_runs: list[WorkflowRunSummary]


class ExpectedWorkflowAttempt(GitHubRecord):
    """Run identity supplied by trusted workflow context, after serialization."""

    repository: str
    workflow_path: str
    event: WorkflowEvent
    ref: str
    run_id: int
    run_attempt: int


class DownloadedArtifact(GitHubRecord):
    """Artifact whose remote identity, archive digest, and file inventory were checked."""

    artifact: ArtifactMetadata
    workflow: WorkflowAttempt
    extracted_directory: Path
    files: tuple[str, ...]


class GitHubRelease(GitHubRecord):
    """Published release identity returned by the GitHub Releases API."""

    id: int
    tag_name: str
    target_commitish: str
    draft: bool
    prerelease: bool
    html_url: str
    body: str | None


class GitHubReleaseSummary(GitHubRecord):
    """Fields needed to select the newest completed semantic publication."""

    id: int
    tag_name: str
    draft: bool
    prerelease: bool
    published_at: datetime | None


class GitHubArtifactError(RuntimeError):
    """A secret-safe artifact boundary failure."""


class GitHubArtifactProvenanceError(GitHubArtifactError):
    """The authenticated GitHub metadata does not identify the release workflow."""


class GitHubArtifactNotFound(GitHubArtifactError):
    """A referenced workflow or artifact is no longer retained by GitHub."""


class GitHubArtifactClient:
    """Read authenticated Actions provenance and download exact bounded artifacts."""

    def __init__(self, token: str, transport: httpx.BaseTransport | None = None) -> None:
        if not token:
            raise ValueError(_REQUEST_FAILED)
        self._token = token
        self._client = httpx.Client(
            follow_redirects=False,
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_SECONDS),
            transport=transport,
            trust_env=False,
        )

    def close(self) -> None:
        """Close the network client and its connection pool."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_workflow_attempt(self, expected: ExpectedWorkflowAttempt) -> WorkflowAttempt:
        """Fetch and verify repository, workflow, event, ref, run, and attempt identity."""
        attempt = self._fetch_workflow_attempt(expected.repository, expected.run_id, expected.run_attempt)
        self._verify_workflow_attempt(attempt, expected)
        return attempt

    def get_release_workflow_attempt(self, repository: str, run_id: int, run_attempt: int) -> WorkflowAttempt:
        """Fetch historical producer metadata and require the default-branch release workflow."""
        attempt = self._fetch_workflow_attempt(repository, run_id, run_attempt)
        workflow_path = attempt.path.split(_WORKFLOW_PATH_SUFFIX_SEPARATOR, maxsplit=1)[0]
        if (
            attempt.id != run_id
            or attempt.run_attempt != run_attempt
            or attempt.repository.full_name.casefold() != repository.casefold()
            or workflow_path != _RELEASE_WORKFLOW_PATH
            or attempt.ref != _DEFAULT_RELEASE_REF
            or attempt.event not in {WorkflowEvent.SCHEDULE.value, WorkflowEvent.WORKFLOW_DISPATCH.value}
        ):
            raise GitHubArtifactProvenanceError(_WORKFLOW_PROVENANCE_MISMATCH)
        return attempt

    def list_run_artifacts(self, expected: ExpectedWorkflowAttempt) -> list[ArtifactMetadata]:
        """List bounded artifacts for the expected run, then validate their shared producer."""
        workflow = self.get_workflow_attempt(expected)
        return self.list_artifacts_for_attempt(workflow)

    def list_artifacts_for_attempt(self, workflow: WorkflowAttempt) -> list[ArtifactMetadata]:
        """List and validate artifacts attached to an already verified attempt."""
        artifacts = self._list_artifacts(
            _RUN_ARTIFACTS_ROUTE.format(
                repository=quote(workflow.repository.full_name, safe=_PATH_SEPARATOR),
                run_id=workflow.id,
            )
        )
        for artifact in artifacts:
            self._verify_artifact_workflow(artifact, workflow)
        return artifacts

    def list_repository_artifacts(self, repository: str) -> list[ArtifactMetadata]:
        """List repository artifacts within the bounded retention-history window."""
        return self._list_artifacts(
            _REPOSITORY_ARTIFACTS_ROUTE.format(repository=quote(repository, safe=_PATH_SEPARATOR))
        )

    def list_release_workflow_attempts(self, repository: str) -> list[WorkflowAttempt]:
        """Enumerate default-branch schedule/manual attempts rather than unrelated repository artifacts."""
        attempts: list[WorkflowAttempt] = []
        for event in (WorkflowEvent.SCHEDULE, WorkflowEvent.WORKFLOW_DISPATCH):
            for summary in self._list_workflow_run_summaries(repository, event):
                workflow_path = summary.path.split(_WORKFLOW_PATH_SUFFIX_SEPARATOR, maxsplit=1)[0]
                if workflow_path != _RELEASE_WORKFLOW_PATH or summary.ref != _DEFAULT_RELEASE_REF:
                    continue
                expected = ExpectedWorkflowAttempt(
                    repository=repository,
                    workflow_path=_RELEASE_WORKFLOW_PATH,
                    event=event,
                    ref=_DEFAULT_RELEASE_REF,
                    run_id=summary.id,
                    run_attempt=summary.run_attempt,
                )
                attempts.append(self.get_workflow_attempt(expected))
        return attempts

    def verify_artifact_producer(self, artifact: ArtifactMetadata, workflow: WorkflowAttempt) -> None:
        """Verify the artifact's run, repository, and source revision against GitHub metadata."""
        self._verify_artifact_workflow(artifact, workflow)

    def confirm_uploaded_artifact(
        self,
        expected: ExpectedWorkflowAttempt,
        artifact_id: int,
        artifact_name: str,
        artifact_digest: str,
    ) -> ArtifactMetadata:
        """Reconcile action outputs with immutable current-attempt API metadata."""
        workflow = self.get_workflow_attempt(expected)
        artifacts = self.list_artifacts_for_attempt(workflow)
        matches = [artifact for artifact in artifacts if artifact.id == artifact_id]
        if len(matches) != 1:
            raise GitHubArtifactError(_ARTIFACT_UPLOAD_UNCONFIRMED)
        artifact = matches[0]
        if artifact.expired or artifact.name != artifact_name or artifact.digest != artifact_digest:
            raise GitHubArtifactError(_ARTIFACT_UPLOAD_UNCONFIRMED)
        return artifact

    def get_release_by_tag(self, repository: str, tag: str) -> GitHubRelease | None:
        """Read one release for retry reconciliation; an unpublished tag has no release."""
        route = _RELEASE_TAG_ROUTE.format(
            repository=quote(repository, safe=_PATH_SEPARATOR),
            tag=quote(tag, safe=_EMPTY),
        )
        try:
            response = self._client.get(_API_ROOT + route, headers=self._api_headers())
        except httpx.HTTPError:
            raise GitHubArtifactError(_REQUEST_FAILED) from None
        if response.status_code == _NOT_FOUND_STATUS:
            return None
        if response.status_code != _SUCCESS_STATUS:
            raise GitHubArtifactError(_REQUEST_FAILED)
        try:
            return GitHubRelease.model_validate_json(response.content)
        except ValidationError:
            raise GitHubArtifactError(_INVALID_RESPONSE) from None

    def list_releases(self, repository: str) -> list[GitHubReleaseSummary]:
        """Read a bounded published-release history for baseline selection."""
        route = _RELEASE_LIST_ROUTE.format(repository=quote(repository, safe=_PATH_SEPARATOR))
        result: list[GitHubReleaseSummary] = []
        for page_number in range(1, _MAX_RELEASE_PAGES + 1):
            try:
                response = self._client.get(
                    _API_ROOT + route,
                    headers=self._api_headers(),
                    params={"per_page": _PER_PAGE, "page": page_number},
                )
            except httpx.HTTPError:
                raise GitHubArtifactError(_REQUEST_FAILED) from None
            if response.status_code != _SUCCESS_STATUS:
                raise GitHubArtifactError(_REQUEST_FAILED)
            try:
                payload = json.loads(response.content)
                if not isinstance(payload, list):
                    raise ValueError(_INVALID_RESPONSE)
                page = [
                    GitHubReleaseSummary.model_validate_json(json.dumps(item))
                    for item in payload
                    if isinstance(item, dict)
                ]
                if len(page) != len(payload):
                    raise ValueError(_INVALID_RESPONSE)
            except (json.JSONDecodeError, ValidationError, ValueError):
                raise GitHubArtifactError(_INVALID_RESPONSE) from None
            result.extend(page)
            if len(result) >= _MAX_RELEASES or len(page) < _PER_PAGE:
                break
        if len(result) >= _MAX_RELEASES:
            raise GitHubArtifactError(_ARTIFACT_LIST_LIMIT)
        return result

    def create_release(
        self,
        repository: str,
        tag: str,
        target_sha: str,
        body: str,
    ) -> GitHubRelease:
        """Create a published release only after the caller's proved refs are verified."""
        if len(body.encode(_UTF8_ENCODING)) > _MAX_RELEASE_BODY_BYTES:
            raise GitHubArtifactError(_MAX_BODY_BYTES)
        route = _RELEASE_CREATE_ROUTE.format(repository=quote(repository, safe=_PATH_SEPARATOR))
        try:
            response = self._client.post(
                _API_ROOT + route,
                headers=self._api_headers(),
                json={
                    "tag_name": tag,
                    "target_commitish": target_sha,
                    "name": tag,
                    "body": body,
                    "draft": False,
                    "prerelease": False,
                    "make_latest": "true",
                },
            )
        except httpx.HTTPError:
            raise GitHubArtifactError(_REQUEST_FAILED) from None
        if response.status_code != _CREATED_STATUS:
            raise GitHubArtifactError(_REQUEST_FAILED)
        try:
            release = GitHubRelease.model_validate_json(response.content)
        except ValidationError:
            raise GitHubArtifactError(_INVALID_RESPONSE) from None
        if release.tag_name != tag or release.draft or release.prerelease:
            raise GitHubArtifactError(_RELEASE_CONFLICT)
        return release

    def download_artifact(
        self,
        artifact: ArtifactMetadata,
        workflow: WorkflowAttempt,
        expected_name: str,
        destination: Path,
        expected_files: frozenset[str] | None,
    ) -> DownloadedArtifact:
        """Verify one exact artifact, archive digest, producer, safe extraction, and inventory."""
        self._verify_artifact_workflow(artifact, workflow)
        if artifact.expired or artifact.name != expected_name:
            raise GitHubArtifactError(_ARTIFACT_IDENTITY_MISMATCH)
        if artifact.size_in_bytes > _MAX_ARCHIVE_BYTES:
            raise GitHubArtifactError(_ARTIFACT_SIZE_EXCEEDED)
        if artifact.digest is None or _SHA256_PATTERN.fullmatch(artifact.digest) is None:
            raise GitHubArtifactError(_ARTIFACT_DIGEST_MISSING)
        if destination.exists() or destination.is_symlink():
            raise GitHubArtifactError(_DESTINATION_MUST_BE_NEW)
        destination.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True)
        archive_path = destination / _ARCHIVE_FILE
        self._download_archive(workflow.repository.full_name, artifact, archive_path)
        files = _extract_archive(archive_path, destination / _EXTRACTED_DIRECTORY, expected_files)
        archive_path.unlink()
        return DownloadedArtifact(
            artifact=artifact,
            workflow=workflow,
            extracted_directory=destination / _EXTRACTED_DIRECTORY,
            files=files,
        )

    def _api_json(self, route: str) -> bytes:
        """Request one authenticated JSON resource without following redirects."""
        try:
            response = self._client.get(_API_ROOT + route, headers=self._api_headers())
        except httpx.HTTPError:
            raise GitHubArtifactError(_REQUEST_FAILED) from None
        if response.status_code == _NOT_FOUND_STATUS:
            raise GitHubArtifactNotFound(_REQUEST_FAILED)
        if response.status_code != _SUCCESS_STATUS:
            raise GitHubArtifactError(_REQUEST_FAILED)
        return response.content

    def _fetch_workflow_attempt(self, repository: str, run_id: int, run_attempt: int) -> WorkflowAttempt:
        """Fetch one attempt record from the exact repository-owned Actions endpoint."""
        route = _WORKFLOW_RUNS_ROUTE.format(
            repository=quote(repository, safe=_PATH_SEPARATOR),
            run_id=run_id,
            attempt=run_attempt,
        )
        try:
            return WorkflowAttempt.model_validate_json(self._api_json(route))
        except ValidationError:
            raise GitHubArtifactError(_INVALID_RESPONSE) from None

    def _api_headers(self) -> dict[str, str]:
        """Build authentication headers used only for api.github.com."""
        return {
            _ACCEPT_HEADER: _ACCEPT_VALUE,
            _AUTHORIZATION_HEADER: _BEARER_PREFIX + self._token,
            _API_VERSION_HEADER: _API_VERSION,
            _USER_AGENT_HEADER: _USER_AGENT,
        }

    def _list_artifacts(self, route: str) -> list[ArtifactMetadata]:
        """Read all pages while enforcing an explicit maximum history size."""
        result: list[ArtifactMetadata] = []
        page_number = 1
        total_count: int | None = None
        while page_number <= _MAX_ARTIFACT_PAGES:
            separator = _QUERY_SEPARATOR if _QUERY_SEPARATOR not in route else _QUERY_CONTINUATION
            body = self._api_json(
                route
                + separator
                + _PAGE_SIZE_PARAMETER
                + _EQUALS
                + str(_PER_PAGE)
                + _AMPERSAND
                + _PAGE_PARAMETER
                + _EQUALS
                + str(page_number)
            )
            try:
                page = ArtifactPage.model_validate_json(body)
            except ValidationError:
                raise GitHubArtifactError(_INVALID_RESPONSE) from None
            if total_count is None:
                total_count = page.total_count
            result.extend(page.artifacts)
            if len(result) > _MAX_ARTIFACTS or len(result) >= total_count:
                break
            page_number += 1
            if len(page.artifacts) < _PER_PAGE:
                break
        if total_count is not None and total_count > _MAX_ARTIFACTS:
            raise GitHubArtifactError(_ARTIFACT_LIST_LIMIT)
        if total_count is not None and len(result) < total_count:
            raise GitHubArtifactError(_ARTIFACT_LIST_LIMIT)
        return result

    def _list_workflow_run_summaries(
        self,
        repository: str,
        event: WorkflowEvent,
    ) -> list[WorkflowRunSummary]:
        """Page release workflow runs with an explicit upper bound."""
        route = _WORKFLOW_RUN_LIST_ROUTE.format(
            repository=quote(repository, safe=_PATH_SEPARATOR),
            workflow_file=_WORKFLOW_FILE,
        )
        result: list[WorkflowRunSummary] = []
        total_count: int | None = None
        for page_number in range(1, _MAX_RELEASE_RUN_PAGES + 1):
            body = self._api_json(
                route
                + _QUERY_SEPARATOR
                + _BRANCH_QUERY_KEY
                + _EQUALS
                + _MAIN_BRANCH
                + _AMPERSAND
                + _EVENT_QUERY_KEY
                + _EQUALS
                + event.value
                + _AMPERSAND
                + _PAGE_SIZE_PARAMETER
                + _EQUALS
                + str(_PER_PAGE)
                + _AMPERSAND
                + _PAGE_PARAMETER
                + _EQUALS
                + str(page_number)
            )
            try:
                page = WorkflowRunPage.model_validate_json(body)
            except ValidationError:
                raise GitHubArtifactError(_INVALID_RESPONSE) from None
            if total_count is None:
                total_count = page.total_count
            result.extend(page.workflow_runs)
            if len(result) >= total_count or len(page.workflow_runs) < _PER_PAGE:
                break
        if total_count is not None and (total_count > _MAX_RELEASE_RUNS or len(result) < total_count):
            raise GitHubArtifactError(_ARTIFACT_LIST_LIMIT)
        return result

    def _verify_workflow_attempt(
        self,
        actual: WorkflowAttempt,
        expected: ExpectedWorkflowAttempt,
    ) -> None:
        """Fail closed when GitHub reports a different release workflow attempt."""
        workflow_path = actual.path.split(_WORKFLOW_PATH_SUFFIX_SEPARATOR, maxsplit=1)[0]
        if (
            actual.id != expected.run_id
            or actual.run_attempt != expected.run_attempt
            or actual.repository.full_name.casefold() != expected.repository.casefold()
            or expected.workflow_path != _RELEASE_WORKFLOW_PATH
            or workflow_path != _RELEASE_WORKFLOW_PATH
            or expected.ref != _DEFAULT_RELEASE_REF
            or actual.event != expected.event
            or expected.event not in {WorkflowEvent.SCHEDULE, WorkflowEvent.WORKFLOW_DISPATCH}
            or actual.ref != expected.ref
        ):
            raise GitHubArtifactProvenanceError(_WORKFLOW_PROVENANCE_MISMATCH)

    def _verify_artifact_workflow(
        self,
        artifact: ArtifactMetadata,
        workflow: WorkflowAttempt,
    ) -> None:
        """Bind artifact metadata to the exact repository, run, and source revision."""
        if (
            artifact.workflow_run.id != workflow.id
            or artifact.workflow_run.repository_id != workflow.repository.id
            or artifact.workflow_run.head_repository_id != workflow.repository.id
            or artifact.workflow_run.head_sha != workflow.head_sha
        ):
            raise GitHubArtifactProvenanceError(_WORKFLOW_PROVENANCE_MISMATCH)

    def _download_archive(self, repository: str, artifact: ArtifactMetadata, destination: Path) -> None:
        """Download the exact artifact without forwarding the API bearer token to storage."""
        route = _ARTIFACT_DOWNLOAD_ROUTE.format(
            repository=quote(repository, safe=_PATH_SEPARATOR),
            artifact_id=artifact.id,
        )
        try:
            redirect = self._client.get(_API_ROOT + route, headers=self._api_headers())
        except httpx.HTTPError:
            raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED) from None
        location = redirect.headers.get(_LOCATION_HEADER)
        if redirect.status_code != _REDIRECT_STATUS or location is None:
            raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED)
        signed_url = httpx.URL(location)
        if signed_url.scheme != _HTTPS_SCHEME or signed_url.userinfo:
            raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED)
        digest = hashlib.sha256()
        received = 0
        try:
            with self._client.stream(
                _GET_METHOD,
                signed_url,
                timeout=httpx.Timeout(_DOWNLOAD_TIMEOUT_SECONDS),
                headers={_USER_AGENT_HEADER: _USER_AGENT},
            ) as response:
                if response.status_code != _SUCCESS_STATUS:
                    raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED)
                with destination.open(_WRITE_BINARY_MODE) as archive:
                    for chunk in response.iter_bytes(_ARCHIVE_CHUNK_BYTES):
                        received += len(chunk)
                        if received > _MAX_ARCHIVE_BYTES:
                            raise GitHubArtifactError(_ARTIFACT_SIZE_EXCEEDED)
                        digest.update(chunk)
                        archive.write(chunk)
            destination.chmod(_PRIVATE_FILE_MODE)
        except httpx.HTTPError:
            raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED) from None
        if _SHA256_PREFIX + digest.hexdigest() != artifact.digest:
            destination.unlink(missing_ok=True)
            raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED)
        if received != artifact.size_in_bytes:
            destination.unlink(missing_ok=True)
            raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED)


def artifact_name_for_attempt(name: str, expected: ExpectedWorkflowAttempt) -> str:
    """Return the exact name suffix that binds an artifact to one workflow attempt."""
    suffix = _ARTIFACT_ATTEMPT_SEPARATOR.join((_RUN_ATTEMPT_MARKER, str(expected.run_id), str(expected.run_attempt)))
    if name.endswith(suffix):
        return name
    return name + _ARTIFACT_ATTEMPT_SEPARATOR + suffix


def _extract_archive(
    archive_path: Path,
    destination: Path,
    expected_files: frozenset[str] | None,
) -> tuple[str, ...]:
    """Safely extract only the bounded exact file inventory declared by the caller."""
    if destination.exists() or destination.is_symlink():
        raise GitHubArtifactError(_DESTINATION_MUST_BE_NEW)
    destination.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            files: dict[str, zipfile.ZipInfo] = {}
            total_bytes = 0
            for info in archive.infolist():
                relative_path = _safe_archive_path(info.filename)
                if info.is_dir():
                    continue
                mode = info.external_attr >> _MODE_SHIFT
                if stat.S_ISLNK(mode) or relative_path in files:
                    raise GitHubArtifactError(_ARTIFACT_PATH_UNSAFE)
                files[relative_path] = info
                total_bytes += info.file_size
                if total_bytes > _MAX_UNPACKED_BYTES or len(files) > _MAX_ARCHIVE_FILES:
                    raise GitHubArtifactError(_ARTIFACT_CONTENT_LIMIT)
            if expected_files is not None and frozenset(files) != expected_files:
                raise GitHubArtifactError(_ARTIFACT_SET_MISMATCH)
            for relative_path, info in files.items():
                target = destination.joinpath(*PurePosixPath(relative_path).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive.open(info) as source, target.open(_WRITE_BINARY_MODE) as output:
                    while block := source.read(_ARCHIVE_CHUNK_BYTES):
                        written += len(block)
                        output.write(block)
                if written != info.file_size:
                    raise GitHubArtifactError(_ARTIFACT_SET_MISMATCH)
                target.chmod(_PRIVATE_FILE_MODE)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        raise GitHubArtifactError(_ARTIFACT_DOWNLOAD_FAILED) from None
    return tuple(sorted(files))


def _safe_archive_path(path: str) -> str:
    """Reject absolute, traversing, and non-canonical archive paths."""
    pure_path = PurePosixPath(path)
    if (
        not path
        or pure_path.is_absolute()
        or _WINDOWS_PATH_SEPARATOR in path
        or any(part in {_EMPTY, _DOT, _PARENT} for part in pure_path.parts)
    ):
        raise GitHubArtifactError(_ARTIFACT_PATH_UNSAFE)
    return pure_path.as_posix()


_WORKFLOW_PATH_SUFFIX_SEPARATOR = "@"
_ARTIFACT_ATTEMPT_SEPARATOR = "-"
_ARCHIVE_FILE = "artifact.zip"
_EXTRACTED_DIRECTORY = "files"
_QUERY_SEPARATOR = "?"
_QUERY_CONTINUATION = "&"
_PAGE_SIZE_PARAMETER = "per_page"
_PAGE_PARAMETER = "page"
_EQUALS = "="
_AMPERSAND = "&"
_LOCATION_HEADER = "Location"
_GET_METHOD = "GET"
_WRITE_BINARY_MODE = "wb"
_PRIVATE_FILE_MODE = 0o600
_PRIVATE_DIRECTORY_MODE = 0o700
_MODE_SHIFT = 16
_WINDOWS_PATH_SEPARATOR = "\\"

"""Controller-only adapters for release auth, provider results, and installer proof."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from teleclaude.git import Repo
from tools.ci.gha import append_output, repo_root
from tools.ci.publish_release import publish_proved_candidate
from tools.ci.read_inspector_report import InspectorSelection, select_inspector_report
from tools.release.attempt import (
    CandidateIdentity,
    ProofIdentity,
    ProviderAttempt,
    ProviderFailure,
    ProviderName,
    ProviderOutcome,
    PublicationReceipt,
    PublicationState,
    load_attempt_identity,
)
from tools.release.claude_inspector import run_claude_inspection
from tools.release.codex_auth import (
    CODEX_AUTH_FILENAME,
    ArtifactReference,
    AuthUseLease,
    artifact_reference_for_upload,
    find_existing_seed_operation,
    next_auth_generation,
    restore_latest_auth_state,
    write_begin_checkpoint,
    write_seeded_auth_state,
    write_settled_auth_state,
)
from tools.release.codex_inspector import run_codex_inspection
from tools.release.github_artifacts import (
    ArtifactMetadata,
    ExpectedWorkflowAttempt,
    GitHubArtifactClient,
    GitHubArtifactError,
    WorkflowAttempt,
    WorkflowEvent,
)
from tools.release.isolated_inspection import (
    InspectorBoundaryError,
    InspectorRole,
    create_controller_root,
    create_principal_directory,
    create_principal_layout,
    read_principal_file,
    remove_controller_root,
    remove_principal_tree,
)

_UTF8 = "utf-8"
_JSON_INDENT = 2
_NEWLINE = "\n"
_EMPTY = ""
_RUNNER_TEMP = "RUNNER_TEMP"
_GITHUB_REPOSITORY = "GITHUB_REPOSITORY"
_GITHUB_RUN_ID = "GITHUB_RUN_ID"
_GITHUB_RUN_ATTEMPT = "GITHUB_RUN_ATTEMPT"
_GITHUB_EVENT_NAME = "GITHUB_EVENT_NAME"
_GITHUB_REF = "GITHUB_REF"
_GITHUB_OUTPUT = "GITHUB_OUTPUT"
_GH_TOKEN = "GH_TOKEN"
_AGE_IDENTITY = "CODEX_AUTH_AGE_IDENTITY"
_SEED_CIPHERTEXT = "CODEX_AUTH_SEED_CIPHERTEXT"
_CLAUDE_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
_SEED_OPERATION = "RELEASE_SEED_OPERATION_ID"
_BOOTSTRAP_NOTES = "BOOTSTRAP_NOTES"
_REPOSITORY_WORKFLOW_PATH = ".github/workflows/release.yaml"
_MAIN_REF = "refs/heads/main"
_STATE_FILENAME = "release-controller-state.json"
_CODEX_ATTEMPT_FILENAME = "codex-attempt.json"
_CODEX_REPORT_FILENAME = "codex-report.json"
_CLAUDE_ATTEMPT_FILENAME = "claude-attempt.json"
_CLAUDE_REPORT_FILENAME = "claude-report.json"
_SELECTION_FILENAME = "selection.json"
_SELECTED_REPORT_FILENAME = "selected-report.json"
_SEED_PREFIX = "codex-seed-operation-"
_PUBLISHING_PREFIX = "release-publication-"
_CANDIDATE_PREFIX = "release-candidate-"
_PROOF_PREFIX = "release-proof-"
_RECEIPT_FILENAME = "publication-receipt.json"
_CANDIDATE_FILENAME = "candidate-identity.json"
_PROOF_FILENAME = "proof-identity.json"
_BUNDLE_FILENAME = "candidate.bundle"
_CANDIDATE_CHECK_FILENAME = "candidate-check.json"
_PROOF_LOG_FILENAME = "proof-log.txt"
_SEED_CIPHERTEXT_FILENAME = "seed.age"
_SEED_ID_FILENAME = "seed-operation.json"
_SEED_ARTIFACT_NAME_KEY = "artifact_name"
_DEFAULT_FAILURE = "A release stage failed before it produced a complete result."
_SETUP_FAILURE = "The provider controller could not establish its declared boundary."
_AUTH_FAILURE = "Codex authentication could not be restored or settled."
_INVALID_SEED = "The explicit encrypted Codex seed is unavailable or invalid."
_INVALID_ARTIFACT = "A finalized Actions artifact does not match its uploaded identity."
_SUCCESS = "success"
_READY = "ready"
_FALSE = "false"
_TRUE = "true"
_PROCESS_TIMEOUT = 0o600
_MAX_PROOF_LOG_BYTES = 32 * 1024 * 1024
_MAX_PROOF_LOG_FILE_BYTES = 8 * 1024 * 1024
_RELEASE_CONTROLLER_ROOT = "teleclaude-release-controller"
_CODEX_STATE_DIRECTORY = "codex"
_CLAUDE_STATE_DIRECTORY = "claude"
_CODEX_AUTH_HOME = "codex-home"
_CLAUDE_CONFIG_HOME = "claude-config"
_BOOTSTRAP_NOTES_FILE = "bootstrap-notes.md"
_ARTIFACT_MANIFEST_FILENAME = "artifact-manifest.json"
_ARTIFACT_MANIFEST_SCHEMA = 1
_ARTIFACT_MANIFEST_HASH_OUTPUT = "artifact_manifest_sha256"


class CodexControllerState(BaseModel):
    """Typed secret-free paths and provenance needed across Codex workflow steps."""

    model_config = ConfigDict(extra="forbid", strict=True)

    attempt_path: Path
    controller_root: Path
    evidence_directory: Path
    principal_home: Path
    principal_temp: Path
    principal_state: Path
    codex_home: Path
    result_directory: Path
    begin_directory: Path
    begin_name: str
    lease: AuthUseLease
    workflow: WorkflowAttempt
    repository: str
    run_id: int
    run_attempt: int
    recipient_fingerprint: str
    begin_reference: ArtifactReference | None = None
    settled_directory: Path | None = None
    settled_name: str | None = None
    settled_generation: int | None = None
    provider_attempt: ProviderAttempt | None = None
    auth_settlement_failed: bool = False


class ArtifactFile(BaseModel):
    """One file bound by a controller-generated artifact manifest."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    path: str
    size: int
    sha256: str


class ArtifactManifest(BaseModel):
    """Exact file inventory for an artifact with an unbounded repository-shaped tree."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: int
    files: list[ArtifactFile]


def _expected_workflow(repository: str, run_id: str, run_attempt: int, event: WorkflowEvent) -> ExpectedWorkflowAttempt:
    """Build the current run identity that the GitHub API must confirm."""
    return ExpectedWorkflowAttempt(
        repository=repository,
        workflow_path=_REPOSITORY_WORKFLOW_PATH,
        event=event,
        ref=_MAIN_REF,
        run_id=int(run_id),
        run_attempt=run_attempt,
    )


def prepare_codex(attempt_path: Path, evidence_directory: Path, state_directory: Path, result_directory: Path) -> bool:
    """Restore the current managed login and upload its begin checkpoint before Codex starts."""
    repository = os.environ.get(_GITHUB_REPOSITORY, _EMPTY)
    run_id = os.environ.get(_GITHUB_RUN_ID, _EMPTY)
    run_attempt = int(os.environ.get(_GITHUB_RUN_ATTEMPT, "0"))
    token = os.environ.get(_GH_TOKEN, _EMPTY)
    identity = os.environ.get(_AGE_IDENTITY, _EMPTY)
    controller_root = Path(os.environ.get(_RUNNER_TEMP, "/tmp")) / _RELEASE_CONTROLLER_ROOT
    state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_root = result_directory.parent
    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if not token or not identity or not run_id.isdigit() or run_attempt < 1:
            raise ValueError(_AUTH_FAILURE)
        create_controller_root(controller_root)
        principal_home, principal_temp, principal_state = create_principal_layout(InspectorRole.CODEX, controller_root)
        codex_home = create_principal_directory(
            InspectorRole.CODEX, controller_root, principal_state / _CODEX_AUTH_HOME
        )
        load_attempt_identity(attempt_path)
        expected = _expected_workflow(
            repository,
            run_id,
            run_attempt,
            WorkflowEvent(os.environ.get(_GITHUB_EVENT_NAME, _EMPTY)),
        )
        with GitHubArtifactClient(token) as client:
            workflow = client.get_workflow_attempt(expected)
            restored = restore_latest_auth_state(client, repository, identity, controller_root, codex_home)
            begin_directory = output_root / "codex-begun"
            lease = write_begin_checkpoint(workflow, repository, restored.artifact, begin_directory)
        state = CodexControllerState(
            attempt_path=attempt_path.resolve(),
            controller_root=controller_root,
            evidence_directory=evidence_directory.resolve(),
            principal_home=principal_home,
            principal_temp=principal_temp,
            principal_state=principal_state,
            codex_home=codex_home,
            result_directory=result_directory,
            begin_directory=begin_directory,
            begin_name=lease.artifact_name,
            lease=lease,
            workflow=workflow,
            repository=repository,
            run_id=int(run_id),
            run_attempt=run_attempt,
            recipient_fingerprint=lease.envelope.age_recipient_sha256 or _EMPTY,
        )
        (state_directory / _STATE_FILENAME).write_text(
            state.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
            encoding=_UTF8,
        )
        append_output("codex_begin_name", lease.artifact_name)
        append_output("codex_prepared", _TRUE)
        return True
    except (OSError, RuntimeError, ValueError, ValidationError, GitHubArtifactError):
        _write_attempt_failure(result_directory / _CODEX_ATTEMPT_FILENAME, ProviderFailure.AUTH_SETTLEMENT)
        append_output("codex_begin_name", _EMPTY)
        append_output("codex_prepared", _FALSE)
        return False


def confirm_codex_begin(state_directory: Path) -> bool:
    """Confirm the uploaded begin checkpoint before permitting any Codex process."""
    state = _read_state(state_directory)
    try:
        artifact_id = int(os.environ.get("UPLOADED_ARTIFACT_ID", "0"))
        artifact_digest = os.environ.get("UPLOADED_ARTIFACT_DIGEST", _EMPTY)
        with GitHubArtifactClient(os.environ[_GH_TOKEN]) as client:
            artifact = client.confirm_uploaded_artifact(
                _expected_workflow(
                    state.repository,
                    str(state.run_id),
                    state.run_attempt,
                    WorkflowEvent(os.environ[_GITHUB_EVENT_NAME]),
                ),
                artifact_id,
                state.begin_name,
                artifact_digest,
            )
        lease = state.lease
        reference = artifact_reference_for_upload(
            artifact,
            lease.envelope.generation,
            state.run_id,
            state.run_attempt,
            state.recipient_fingerprint,
        )
        state.begin_reference = reference
        _write_state(state_directory, state)
        append_output("codex_begin_confirmed", _TRUE)
        return True
    except (KeyError, OSError, RuntimeError, ValueError, ValidationError, GitHubArtifactError):
        append_output("codex_begin_confirmed", _FALSE)
        _write_attempt_failure(state.result_directory / _CODEX_ATTEMPT_FILENAME, ProviderFailure.AUTH_SETTLEMENT)
        return False


def run_codex(state_directory: Path, report_output_directory: Path) -> bool:
    """Run the isolated Codex client and encrypt its post-run cache before fallback."""
    state = _read_state(state_directory)
    result_directory = state.result_directory
    try:
        if state.begin_reference is None:
            raise ValueError(_AUTH_FAILURE)
        executable_text = shutil.which("codex")
        if executable_text is None:
            raise FileNotFoundError(_SETUP_FAILURE)
        lease = state.lease
        result = run_codex_inspection(
            Path(executable_text),
            state.evidence_directory,
            state.controller_root,
            state.principal_home,
            state.principal_temp,
            state.codex_home,
            result_directory,
            _read_principal_auth(state),
            900,
        )
        append_output("codex_boundary_closed", _TRUE)
        state.provider_attempt = result.attempt
        _write_attempt(result_directory / _CODEX_ATTEMPT_FILENAME, result.attempt)
        if result.report is not None:
            report_output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            (report_output_directory / _CODEX_REPORT_FILENAME).write_text(
                result.report.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
                encoding=_UTF8,
            )
        auth_after = _read_principal_auth(state)
        settled_directory = result_directory.parent / "codex-settled"
        settled_envelope, settled_name = write_settled_auth_state(
            lease,
            state.begin_reference,
            auth_after,
            os.environ[_AGE_IDENTITY],
            state.controller_root,
            settled_directory,
        )
        state.settled_directory = settled_directory
        state.settled_name = settled_name
        state.settled_generation = settled_envelope.generation
        state.auth_settlement_failed = False
        append_output("codex_settled_name", settled_name)
        append_output("codex_settlement_artifact", _TRUE)
        _write_state(state_directory, state)
        return True
    except InspectorBoundaryError:
        append_output("codex_boundary_closed", _FALSE)
        state.auth_settlement_failed = True
        _write_state(state_directory, state)
        raise
    except (OSError, RuntimeError, ValueError, ValidationError, GitHubArtifactError, KeyError):
        prior = state.provider_attempt
        if prior is None:
            _write_attempt_failure(result_directory / _CODEX_ATTEMPT_FILENAME, ProviderFailure.EXECUTION)
        else:
            attempt = prior.model_copy(update={"auth_settlement_failed": True})
            _write_attempt(result_directory / _CODEX_ATTEMPT_FILENAME, attempt)
        state.auth_settlement_failed = True
        _write_state(state_directory, state)
        append_output("codex_settled_name", _EMPTY)
        append_output("codex_settlement_artifact", _FALSE)
        return False


def confirm_codex_settled(result_directory: Path, state_directory: Path) -> bool:
    """Mark Codex eligible only after Actions finalizes and the API confirms state bytes."""
    attempt_path = result_directory / _CODEX_ATTEMPT_FILENAME
    state = _read_state(state_directory)
    try:
        if not state.settled_name:
            raise ValueError(_AUTH_FAILURE)
        artifact_id = int(os.environ.get("UPLOADED_ARTIFACT_ID", "0"))
        artifact_digest = os.environ.get("UPLOADED_ARTIFACT_DIGEST", _EMPTY)
        with GitHubArtifactClient(os.environ[_GH_TOKEN]) as client:
            client.confirm_uploaded_artifact(
                _expected_workflow(
                    state.repository,
                    str(state.run_id),
                    state.run_attempt,
                    WorkflowEvent(os.environ[_GITHUB_EVENT_NAME]),
                ),
                artifact_id,
                state.settled_name,
                artifact_digest,
            )
        attempt = ProviderAttempt.model_validate_json(attempt_path.read_bytes())
        settled = attempt.model_copy(update={"auth_settled": True, "auth_settlement_failed": False})
        _write_attempt(attempt_path, settled)
        success = settled.outcome is ProviderOutcome.SUCCEEDED and settled.failure is None
    except (OSError, RuntimeError, ValueError, ValidationError, GitHubArtifactError, KeyError):
        success = False
        try:
            attempt = ProviderAttempt.model_validate_json(attempt_path.read_bytes())
            if attempt.outcome is ProviderOutcome.SUCCEEDED:
                attempt = attempt.model_copy(
                    update={"outcome": ProviderOutcome.FAILED, "failure": ProviderFailure.AUTH_SETTLEMENT}
                )
            attempt = attempt.model_copy(update={"auth_settlement_failed": True, "auth_settled": False})
            _write_attempt(attempt_path, attempt)
        except (OSError, ValidationError):
            _write_attempt_failure(attempt_path, ProviderFailure.AUTH_SETTLEMENT)
    append_output("codex_success", _TRUE if success else _FALSE)
    return success


def run_claude(evidence_directory: Path, output_directory: Path) -> bool:
    """Run one native restricted Claude fallback over the same immutable evidence."""
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    controller_root = Path(os.environ[_RUNNER_TEMP]) / _RELEASE_CONTROLLER_ROOT
    try:
        executable_text = shutil.which("claude")
        oauth_token = os.environ.get(_CLAUDE_TOKEN, _EMPTY)
        if executable_text is None or not oauth_token:
            raise ValueError(_SETUP_FAILURE)
        if not controller_root.exists():
            create_controller_root(controller_root)
        principal_home, principal_temp, principal_state = create_principal_layout(InspectorRole.CLAUDE, controller_root)
        claude_config = create_principal_directory(
            InspectorRole.CLAUDE,
            controller_root,
            principal_state / _CLAUDE_CONFIG_HOME,
        )
        result_directory = output_directory / "claude-result"
        result = run_claude_inspection(
            Path(executable_text),
            evidence_directory,
            controller_root,
            principal_home,
            principal_temp,
            claude_config,
            result_directory,
            oauth_token,
            900,
        )
        _write_attempt(output_directory / _CLAUDE_ATTEMPT_FILENAME, result.attempt)
        if result.report is not None:
            (output_directory / _CLAUDE_REPORT_FILENAME).write_text(
                result.report.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
                encoding=_UTF8,
            )
        append_output("claude_success", _TRUE if result.attempt.outcome is ProviderOutcome.SUCCEEDED else _FALSE)
        return result.attempt.outcome is ProviderOutcome.SUCCEEDED
    except InspectorBoundaryError:
        raise
    except (OSError, RuntimeError, ValueError):
        _write_attempt_failure(
            output_directory / _CLAUDE_ATTEMPT_FILENAME, ProviderFailure.EXECUTION, ProviderName.CLAUDE
        )
        append_output("claude_success", _FALSE)
        return False


def finish_inspection(
    codex_attempt_path: Path,
    codex_report_path: Path | None,
    claude_attempt_path: Path | None,
    claude_report_path: Path | None,
    output_directory: Path,
) -> InspectorSelection:
    """Select exactly one complete report and retain the unsuccessful primary result."""
    selection = select_inspector_report(codex_attempt_path, codex_report_path, claude_attempt_path, claude_report_path)
    output_directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError(_INVALID_SEED)
    output_directory.mkdir(mode=0o700)
    (output_directory / _SELECTION_FILENAME).write_text(
        selection.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )
    (output_directory / _SELECTED_REPORT_FILENAME).write_text(
        selection.selected_report.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )
    append_output("selected_provider", selection.selected_provider)
    append_output("selected_classification", selection.selected_report.classification)
    codex_failure = (
        selection.codex_attempt.failure.value
        if selection.codex_attempt.failure is not None
        else selection.codex_selection_failure.value
        if selection.codex_selection_failure is not None
        else _EMPTY
    )
    append_output("codex_failure", codex_failure)
    return selection


def seed_codex_auth(output_directory: Path, reseed: bool) -> tuple[str, bool]:
    """Create one explicit encrypted auth seed/reseed artifact under stream serialization."""
    repository = os.environ.get(_GITHUB_REPOSITORY, _EMPTY)
    run_id = os.environ.get(_GITHUB_RUN_ID, _EMPTY)
    run_attempt = int(os.environ.get(_GITHUB_RUN_ATTEMPT, "0"))
    token = os.environ.get(_GH_TOKEN, _EMPTY)
    identity = os.environ.get(_AGE_IDENTITY, _EMPTY)
    operation_id = os.environ.get(_SEED_OPERATION, _EMPTY)
    ciphertext_text = os.environ.get(_SEED_CIPHERTEXT, _EMPTY)
    if not token or not identity or not operation_id or not ciphertext_text or not run_id.isdigit() or run_attempt < 1:
        raise ValueError(_INVALID_SEED)
    try:
        ciphertext = base64.b64decode(ciphertext_text, validate=True)
    except ValueError:
        raise ValueError(_INVALID_SEED) from None
    output_directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_directory.exists() or output_directory.is_symlink():
        raise ValueError(_INVALID_SEED)
    controller_root = Path(os.environ[_RUNNER_TEMP]) / _RELEASE_CONTROLLER_ROOT
    create_controller_root(controller_root)
    with GitHubArtifactClient(token) as client:
        expected = _expected_workflow(
            repository,
            run_id,
            run_attempt,
            WorkflowEvent(os.environ.get(_GITHUB_EVENT_NAME, _EMPTY)),
        )
        workflow = client.get_workflow_attempt(expected)
        existing = find_existing_seed_operation(client, repository, operation_id, ciphertext, identity, controller_root)
        if existing is not None:
            append_output("seed_artifact_name", existing.name)
            append_output("seed_already_complete", _TRUE)
            return existing.name, True
        generation = next_auth_generation(client, repository)
        if not reseed and generation != 1:
            raise RuntimeError(_INVALID_SEED)
        envelope, artifact_name = write_seeded_auth_state(
            ciphertext,
            identity,
            operation_id,
            generation,
            workflow,
            repository,
            None,
            reseed,
            controller_root,
            output_directory,
        )
    (output_directory.parent / _SEED_ID_FILENAME).write_text(
        json.dumps(
            {
                "operation_id": operation_id,
                "generation": envelope.generation,
                _SEED_ARTIFACT_NAME_KEY: artifact_name,
            },
            ensure_ascii=True,
            indent=_JSON_INDENT,
        )
        + _NEWLINE,
        encoding=_UTF8,
    )
    append_output("seed_artifact_name", artifact_name)
    append_output("seed_already_complete", _FALSE)
    return artifact_name, False


def confirm_seed(output_directory: Path, artifact_id: int, digest: str) -> None:
    """Require the explicit seed artifact's upload result to match current-run API metadata."""
    seed_record = json.loads((output_directory.parent / _SEED_ID_FILENAME).read_bytes())
    run_id = os.environ[_GITHUB_RUN_ID]
    run_attempt = int(os.environ[_GITHUB_RUN_ATTEMPT])
    event = WorkflowEvent(os.environ[_GITHUB_EVENT_NAME])
    with GitHubArtifactClient(os.environ[_GH_TOKEN]) as client:
        expected = _expected_workflow(os.environ[_GITHUB_REPOSITORY], run_id, run_attempt, event)
        client.confirm_uploaded_artifact(expected, artifact_id, seed_record[_SEED_ARTIFACT_NAME_KEY], digest)


def confirm_uploaded_artifact(name: str, artifact_id: int, digest: str) -> None:
    """Confirm one current-run artifact output against authenticated Actions metadata."""
    run_id = os.environ[_GITHUB_RUN_ID]
    run_attempt = int(os.environ[_GITHUB_RUN_ATTEMPT])
    event = WorkflowEvent(os.environ[_GITHUB_EVENT_NAME])
    with GitHubArtifactClient(os.environ[_GH_TOKEN]) as client:
        expected = _expected_workflow(os.environ[_GITHUB_REPOSITORY], run_id, run_attempt, event)
        client.confirm_uploaded_artifact(expected, artifact_id, name, digest)


def write_bootstrap_notes(output_path: Path) -> None:
    """Materialize authorized current-state notes from the workflow input."""
    notes = os.environ.get(_BOOTSTRAP_NOTES, _EMPTY).strip()
    if not notes:
        raise ValueError(_INVALID_SEED)
    output_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output_path.write_text(notes + _NEWLINE, encoding=_UTF8)


def recover_publication(repository_root: Path, output_directory: Path, token: str) -> bool:
    """Settle the oldest retained partial publication before allowing a new source capture."""
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    pending: list[tuple[int, int, WorkflowAttempt, PublicationReceipt, list[ArtifactMetadata]]] = []
    with GitHubArtifactClient(token) as client:
        for workflow in client.list_release_workflow_attempts(os.environ[_GITHUB_REPOSITORY]):
            artifacts = client.list_artifacts_for_attempt(workflow)
            for artifact in artifacts:
                if not artifact.name.startswith(_PUBLISHING_PREFIX):
                    continue
                suffix = artifact.name.removeprefix(_PUBLISHING_PREFIX)
                try:
                    run_text, attempt_text = suffix.split("-", maxsplit=1)
                    run_id = int(run_text)
                    run_attempt = int(attempt_text)
                except (ValueError, TypeError):
                    continue
                if run_id != workflow.id:
                    continue
                producer = client.get_release_workflow_attempt(os.environ[_GITHUB_REPOSITORY], run_id, run_attempt)
                with tempfile.TemporaryDirectory(dir=output_directory) as download_root:
                    downloaded = client.download_artifact(
                        artifact,
                        producer,
                        artifact.name,
                        Path(download_root) / "receipt",
                        frozenset({_RECEIPT_FILENAME}),
                    )
                    receipt = PublicationReceipt.model_validate_json(
                        (downloaded.extracted_directory / _RECEIPT_FILENAME).read_bytes()
                    )
                if receipt.state is PublicationState.PUBLISHING:
                    pending.append((run_id, run_attempt, producer, receipt, artifacts))
    if not pending:
        append_output("recovered_publication", _FALSE)
        return False
    for run_id, run_attempt, producer, receipt, artifacts in sorted(pending, key=lambda item: (item[0], item[1])):
        artifact_map = {artifact.name: artifact for artifact in artifacts}
        candidate_name = _CANDIDATE_PREFIX + str(run_id) + "-" + str(run_attempt)
        proof_name = _PROOF_PREFIX + str(run_id) + "-" + str(run_attempt)
        if candidate_name not in artifact_map or proof_name not in artifact_map:
            raise GitHubArtifactError(_INVALID_ARTIFACT)
        with GitHubArtifactClient(token) as client, tempfile.TemporaryDirectory(dir=output_directory) as download_root:
            candidate_download = client.download_artifact(
                artifact_map[candidate_name],
                producer,
                candidate_name,
                Path(download_root) / "candidate",
                frozenset({_CANDIDATE_FILENAME, _BUNDLE_FILENAME, _CANDIDATE_CHECK_FILENAME}),
            )
            proof_download = client.download_artifact(
                artifact_map[proof_name],
                producer,
                proof_name,
                Path(download_root) / "proof",
                frozenset({_PROOF_FILENAME, _PROOF_LOG_FILENAME}),
            )
            candidate = CandidateIdentity.model_validate_json(
                (candidate_download.extracted_directory / _CANDIDATE_FILENAME).read_bytes()
            )
            proof = ProofIdentity.model_validate_json(
                (proof_download.extracted_directory / _PROOF_FILENAME).read_bytes()
            )
            if candidate != receipt.candidate or proof != receipt.proof:
                raise GitHubArtifactError(_INVALID_ARTIFACT)
            recovery_receipt_path = output_directory / ("recovered-" + str(run_id) + "-" + str(run_attempt) + ".json")
            publish_proved_candidate(
                repository_root,
                candidate,
                proof,
                candidate_download.extracted_directory / _BUNDLE_FILENAME,
                recovery_receipt_path,
                token,
            )
        append_output("recovered_tag", receipt.tag)
    append_output("recovered_publication", _TRUE)
    return True


def prepare_proof_checkout(repository_root: Path, candidate_path: Path, bundle_path: Path) -> None:
    """Import R while preserving S as the local main ref consumed by the Tart harness."""
    candidate = CandidateIdentity.model_validate_json(candidate_path.read_bytes())
    if candidate.bundle_sha256 is None or _sha256_file(bundle_path) != candidate.bundle_sha256:
        raise ValueError(_INVALID_ARTIFACT)
    repo = Repo(repository_root)
    _run_git(repository_root, "bundle", "verify", str(bundle_path))
    _run_git(repository_root, "fetch", "--no-tags", str(bundle_path), "HEAD:refs/release/candidate")
    commit = repo.commit("refs/release/candidate")
    if commit.hexsha != candidate.candidate_sha or commit.tree.hexsha != candidate.candidate_tree_sha:
        raise ValueError(_INVALID_ARTIFACT)
    if len(commit.parents) != 1 or commit.parents[0].hexsha != candidate.attempt.source_sha:
        raise ValueError(_INVALID_ARTIFACT)
    repo.git.update_ref("refs/heads/main", candidate.attempt.source_sha)
    repo.git.checkout("--detach", candidate.candidate_sha)


def record_candidate_check(candidate_path: Path, lint_log: Path, output_path: Path, lint_succeeded: bool) -> None:
    """Bind the native lint result to the final candidate without changing it."""
    candidate = CandidateIdentity.model_validate_json(candidate_path.read_bytes())
    digest = _sha256_file(lint_log)
    record = {
        "candidate_sha": candidate.candidate_sha,
        "candidate_tree_sha": candidate.candidate_tree_sha,
        "lint_succeeded": lint_succeeded,
        "lint_log_sha256": digest,
    }
    output_path.write_text(json.dumps(record, ensure_ascii=True, indent=_JSON_INDENT) + _NEWLINE, encoding=_UTF8)
    if not lint_succeeded:
        raise RuntimeError(_DEFAULT_FAILURE)


def record_proof(
    candidate_path: Path,
    candidate_check_path: Path,
    harness_output_directory: Path,
    harness_exit_code: int,
    output_directory: Path,
) -> ProofIdentity:
    """Write exact candidate-bound installer proof plus bounded text evidence."""
    candidate = CandidateIdentity.model_validate_json(candidate_path.read_bytes())
    check = json.loads(candidate_check_path.read_bytes())
    if (
        check.get("candidate_sha") != candidate.candidate_sha
        or check.get("candidate_tree_sha") != candidate.candidate_tree_sha
        or check.get("lint_succeeded") is not True
    ):
        raise ValueError(_INVALID_ARTIFACT)
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    log_path = output_directory / _PROOF_LOG_FILENAME
    _collect_harness_logs(harness_output_directory, log_path)
    evidence_digest = _sha256_file(log_path)
    proof = ProofIdentity(
        candidate_sha=candidate.candidate_sha,
        candidate_tree_sha=candidate.candidate_tree_sha,
        lint_succeeded=True,
        installer_succeeded=harness_exit_code == 0,
        evidence_sha256=evidence_digest,
    )
    (output_directory / _PROOF_FILENAME).write_text(
        proof.model_dump_json(indent=_JSON_INDENT) + _NEWLINE,
        encoding=_UTF8,
    )
    append_output("proof_succeeded", _TRUE if proof.installer_succeeded else _FALSE)
    append_output("proof_evidence_sha256", evidence_digest)
    if not proof.installer_succeeded:
        raise RuntimeError(_DEFAULT_FAILURE)
    return proof


def cleanup_inspectors(controller_root: Path) -> None:
    """Remove per-provider files only after both isolated process boundaries are closed."""
    for role in (InspectorRole.CODEX, InspectorRole.CLAUDE):
        target = controller_root / role.value
        if target.exists() and not target.is_symlink():
            remove_principal_tree(role, controller_root, target)
    if controller_root.exists():
        remove_controller_root(controller_root)


def _read_principal_auth(state: CodexControllerState) -> bytes:
    return read_principal_file(InspectorRole.CODEX, state.codex_home / CODEX_AUTH_FILENAME)


def _write_attempt(path: Path, attempt: ProviderAttempt) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(attempt.model_dump_json(indent=_JSON_INDENT) + _NEWLINE, encoding=_UTF8)


def _write_attempt_failure(
    path: Path,
    failure: ProviderFailure,
    provider: ProviderName = ProviderName.CODEX,
) -> None:
    _write_attempt(
        path,
        ProviderAttempt(
            provider=provider,
            outcome=ProviderOutcome.FAILED,
            failure=failure,
            report_sha256=None,
            auth_settled=False,
            auth_settlement_failed=provider is ProviderName.CODEX,
            exit_code=None,
            timed_out=False,
            diagnostic_path=None,
        ),
    )


def ensure_provider_attempt(path: Path, provider: ProviderName) -> None:
    """Retain a typed setup/execution failure when a controller step exited unexpectedly."""
    if path.exists() or path.is_symlink():
        ProviderAttempt.model_validate_json(path.read_bytes())
        return
    failure = ProviderFailure.AUTH_SETTLEMENT if provider is ProviderName.CODEX else ProviderFailure.EXECUTION
    _write_attempt_failure(path, failure, provider)


def _read_state(directory: Path) -> CodexControllerState:
    return CodexControllerState.model_validate_json((directory / _STATE_FILENAME).read_bytes())


def _write_state(directory: Path, state: CodexControllerState) -> None:
    (directory / _STATE_FILENAME).write_text(state.model_dump_json(indent=_JSON_INDENT) + _NEWLINE, encoding=_UTF8)


def _run_git(root: Path, *arguments: str) -> str:
    """Run bounded local Git operations without invoking a shell."""
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, check=True, timeout=120)
    return result.stdout.strip()


def _sha256_file(path: Path) -> str:
    """Hash one bounded artifact without retaining its complete bytes in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as content:
        for chunk in iter(lambda: content.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_harness_logs(source: Path, destination: Path) -> None:
    """Collect only bounded text logs, excluding VM disks and every binary artifact."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError(_INVALID_ARTIFACT)
    files: list[tuple[str, Path]] = []
    total = 0
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(_INVALID_ARTIFACT)
        if not path.is_file():
            continue
        if path.suffix not in {".log", ".txt"} and path.name != "steps.log":
            continue
        if path.stat().st_size > _MAX_PROOF_LOG_FILE_BYTES:
            raise ValueError(_INVALID_ARTIFACT)
        total += path.stat().st_size
        if total > _MAX_PROOF_LOG_BYTES:
            raise ValueError(_INVALID_ARTIFACT)
        files.append((path.relative_to(source).as_posix(), path))
    with destination.open("wb") as output:
        for relative, path in files:
            output.write(("===== " + relative + " =====\n").encode(_UTF8))
            output.write(path.read_bytes())
            output.write(b"\n")


def write_artifact_manifest(root: Path) -> str:
    """Bind every regular file in a controller artifact tree before upload."""
    if not root.is_dir() or root.is_symlink():
        raise ValueError(_INVALID_ARTIFACT)
    entries: list[ArtifactFile] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(_INVALID_ARTIFACT)
        if not path.is_file() or path.name == _ARTIFACT_MANIFEST_FILENAME:
            continue
        entries.append(
            ArtifactFile(
                path=path.relative_to(root).as_posix(),
                size=path.stat().st_size,
                sha256=_sha256_file(path),
            )
        )
    manifest = ArtifactManifest(schema_version=_ARTIFACT_MANIFEST_SCHEMA, files=entries)
    path = root / _ARTIFACT_MANIFEST_FILENAME
    path.write_text(manifest.model_dump_json(indent=_JSON_INDENT) + _NEWLINE, encoding=_UTF8)
    digest = _sha256_file(path)
    append_output(_ARTIFACT_MANIFEST_HASH_OUTPUT, digest)
    return digest


def verify_artifact_manifest(root: Path, expected_manifest_sha256: str) -> None:
    """Verify the transported manifest itself, exact inventory, sizes, and file digests."""
    manifest_path = root / _ARTIFACT_MANIFEST_FILENAME
    if _sha256_file(manifest_path) != expected_manifest_sha256:
        raise ValueError(_INVALID_ARTIFACT)
    try:
        manifest = ArtifactManifest.model_validate_json(manifest_path.read_bytes())
    except (OSError, ValidationError):
        raise ValueError(_INVALID_ARTIFACT) from None
    if manifest.schema_version != _ARTIFACT_MANIFEST_SCHEMA:
        raise ValueError(_INVALID_ARTIFACT)
    expected = {entry.path: entry for entry in manifest.files}
    actual: dict[str, Path] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(_INVALID_ARTIFACT)
        if path.is_file() and path != manifest_path:
            actual[path.relative_to(root).as_posix()] = path
    if set(actual) != set(expected):
        raise ValueError(_INVALID_ARTIFACT)
    for name, path in actual.items():
        entry = expected[name]
        if path.stat().st_size != entry.size or _sha256_file(path) != entry.sha256:
            raise ValueError(_INVALID_ARTIFACT)


def download_current_artifact(
    name: str,
    artifact_id: int,
    digest: str,
    destination: Path,
    manifest_sha256: str,
    *,
    github_transport: httpx.BaseTransport | None = None,
) -> Path:
    """Download a current-run artifact through its authenticated API identity and manifest."""
    repository = os.environ[_GITHUB_REPOSITORY]
    run_id = os.environ[_GITHUB_RUN_ID]
    run_attempt = int(os.environ[_GITHUB_RUN_ATTEMPT])
    expected = _expected_workflow(repository, run_id, run_attempt, WorkflowEvent(os.environ[_GITHUB_EVENT_NAME]))
    with GitHubArtifactClient(os.environ[_GH_TOKEN], transport=github_transport) as client:
        workflow = client.get_workflow_attempt(expected)
        artifact = client.confirm_uploaded_artifact(expected, artifact_id, name, digest)
        downloaded = client.download_artifact(artifact, workflow, name, destination, None)
    verify_artifact_manifest(downloaded.extracted_directory, manifest_sha256)
    return downloaded.extracted_directory


def download_current_artifact_exact(
    name: str,
    artifact_id: int,
    digest: str,
    destination: Path,
    files: frozenset[str],
    *,
    github_transport: httpx.BaseTransport | None = None,
) -> Path:
    """Download one small fixed-inventory artifact after verifying its upload receipt."""
    repository = os.environ[_GITHUB_REPOSITORY]
    run_id = os.environ[_GITHUB_RUN_ID]
    run_attempt = int(os.environ[_GITHUB_RUN_ATTEMPT])
    expected = _expected_workflow(repository, run_id, run_attempt, WorkflowEvent(os.environ[_GITHUB_EVENT_NAME]))
    with GitHubArtifactClient(os.environ[_GH_TOKEN], transport=github_transport) as client:
        workflow = client.get_workflow_attempt(expected)
        artifact = client.confirm_uploaded_artifact(expected, artifact_id, name, digest)
        downloaded = client.download_artifact(artifact, workflow, name, destination, files)
    return downloaded.extracted_directory


def main(argv: list[str] | None = None) -> int:
    """Expose discrete workflow stages while keeping secrets in dedicated inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    codex_prepare = commands.add_parser("prepare-codex")
    codex_prepare.add_argument("--attempt", type=Path, required=True)
    codex_prepare.add_argument("--evidence", type=Path, required=True)
    codex_prepare.add_argument("--state-directory", type=Path, required=True)
    codex_prepare.add_argument("--result-directory", type=Path, required=True)
    confirm_begin = commands.add_parser("confirm-codex-begin")
    confirm_begin.add_argument("--state-directory", type=Path, required=True)
    codex_run = commands.add_parser("run-codex")
    codex_run.add_argument("--state-directory", type=Path, required=True)
    codex_run.add_argument("--report-output", type=Path, required=True)
    confirm_settled = commands.add_parser("confirm-codex-settled")
    confirm_settled.add_argument("--state-directory", type=Path, required=True)
    confirm_settled.add_argument("--result-directory", type=Path, required=True)
    claude_run = commands.add_parser("run-claude")
    claude_run.add_argument("--evidence", type=Path, required=True)
    claude_run.add_argument("--output-directory", type=Path, required=True)
    seed = commands.add_parser("seed-codex")
    seed.add_argument("--output-directory", type=Path, required=True)
    seed.add_argument("--reseed", action="store_true")
    confirm_seed_parser = commands.add_parser("confirm-seed")
    confirm_seed_parser.add_argument("--output-directory", type=Path, required=True)
    confirm_seed_parser.add_argument("--artifact-id", type=int, required=True)
    confirm_seed_parser.add_argument("--digest", required=True)
    ensure_attempt = commands.add_parser("ensure-provider-attempt")
    ensure_attempt.add_argument("--path", type=Path, required=True)
    ensure_attempt.add_argument("--provider", choices=[member.value for member in ProviderName], required=True)
    confirm_upload = commands.add_parser("confirm-upload")
    confirm_upload.add_argument("--name", required=True)
    confirm_upload.add_argument("--artifact-id", type=int, required=True)
    confirm_upload.add_argument("--digest", required=True)
    bootstrap_notes = commands.add_parser("write-bootstrap-notes")
    bootstrap_notes.add_argument("--output", type=Path, required=True)
    manifest = commands.add_parser("write-artifact-manifest")
    manifest.add_argument("--root", type=Path, required=True)
    download = commands.add_parser("download-artifact")
    download.add_argument("--name", required=True)
    download.add_argument("--artifact-id", type=int, required=True)
    download.add_argument("--digest", required=True)
    download.add_argument("--destination", type=Path, required=True)
    download.add_argument("--manifest-sha256", required=True)
    download_exact = commands.add_parser("download-artifact-exact")
    download_exact.add_argument("--name", required=True)
    download_exact.add_argument("--artifact-id", type=int, required=True)
    download_exact.add_argument("--digest", required=True)
    download_exact.add_argument("--destination", type=Path, required=True)
    download_exact.add_argument("--files", nargs="+", required=True)
    finish = commands.add_parser("select")
    finish.add_argument("--codex-attempt", type=Path, required=True)
    finish.add_argument("--codex-report", type=Path)
    finish.add_argument("--claude-attempt", type=Path)
    finish.add_argument("--claude-report", type=Path)
    finish.add_argument("--output-directory", type=Path, required=True)
    recover = commands.add_parser("recover-publication")
    recover.add_argument("--output-directory", type=Path, required=True)
    proof_checkout = commands.add_parser("prepare-proof-checkout")
    proof_checkout.add_argument("--candidate", type=Path, required=True)
    proof_checkout.add_argument("--bundle", type=Path, required=True)
    lint_record = commands.add_parser("record-candidate-check")
    lint_record.add_argument("--candidate", type=Path, required=True)
    lint_record.add_argument("--log", type=Path, required=True)
    lint_record.add_argument("--output", type=Path, required=True)
    lint_record.add_argument("--success", action="store_true")
    record_proof_parser = commands.add_parser("record-proof")
    record_proof_parser.add_argument("--candidate", type=Path, required=True)
    record_proof_parser.add_argument("--candidate-check", type=Path, required=True)
    record_proof_parser.add_argument("--harness-output", type=Path, required=True)
    record_proof_parser.add_argument("--harness-exit-code", type=int, required=True)
    record_proof_parser.add_argument("--output-directory", type=Path, required=True)
    cleanup = commands.add_parser("cleanup-inspectors")
    cleanup.add_argument("--controller-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        _stage_handler(args)()
    except (OSError, RuntimeError, ValueError, ValidationError, GitHubArtifactError, InspectorBoundaryError) as error:
        print(str(error) or _DEFAULT_FAILURE, file=sys.stderr)
        return 1
    return 0


def _stage_handler(args: argparse.Namespace) -> Callable[[], object]:
    """Resolve parsed command arguments to one small controller operation."""
    handlers: dict[str, Callable[[], object]] = {
        "prepare-codex": lambda: prepare_codex(
            args.attempt, args.evidence, args.state_directory, args.result_directory
        ),
        "confirm-codex-begin": lambda: confirm_codex_begin(args.state_directory),
        "run-codex": lambda: run_codex(args.state_directory, args.report_output),
        "confirm-codex-settled": lambda: confirm_codex_settled(args.result_directory, args.state_directory),
        "run-claude": lambda: run_claude(args.evidence, args.output_directory),
        "seed-codex": lambda: seed_codex_auth(args.output_directory, args.reseed),
        "confirm-seed": lambda: confirm_seed(args.output_directory, args.artifact_id, args.digest),
        "ensure-provider-attempt": lambda: ensure_provider_attempt(args.path, ProviderName(args.provider)),
        "confirm-upload": lambda: confirm_uploaded_artifact(args.name, args.artifact_id, args.digest),
        "write-bootstrap-notes": lambda: write_bootstrap_notes(args.output),
        "write-artifact-manifest": lambda: write_artifact_manifest(args.root),
        "download-artifact": lambda: _download_manifest_command(args),
        "download-artifact-exact": lambda: _download_exact_command(args),
        "select": lambda: finish_inspection(
            args.codex_attempt, args.codex_report, args.claude_attempt, args.claude_report, args.output_directory
        ),
        "recover-publication": lambda: recover_publication(repo_root(), args.output_directory, os.environ[_GH_TOKEN]),
        "prepare-proof-checkout": lambda: prepare_proof_checkout(Path.cwd(), args.candidate, args.bundle),
        "record-candidate-check": lambda: record_candidate_check(args.candidate, args.log, args.output, args.success),
        "record-proof": lambda: record_proof(
            args.candidate, args.candidate_check, args.harness_output, args.harness_exit_code, args.output_directory
        ),
        "cleanup-inspectors": lambda: cleanup_inspectors(args.controller_root),
    }
    return handlers[args.command]


def _download_manifest_command(args: argparse.Namespace) -> Path:
    """Run the manifest-verified artifact download command."""
    destination = download_current_artifact(
        args.name,
        args.artifact_id,
        args.digest,
        args.destination,
        args.manifest_sha256,
    )
    append_output("downloaded_artifact_directory", str(destination))
    return destination


def _download_exact_command(args: argparse.Namespace) -> Path:
    """Run a fixed-inventory artifact download command."""
    destination = download_current_artifact_exact(
        args.name,
        args.artifact_id,
        args.digest,
        args.destination,
        frozenset(args.files),
    )
    append_output("downloaded_artifact_directory", str(destination))
    return destination


if __name__ == "__main__":
    raise SystemExit(main())

"""Serialize, encrypt, restore, and settle one private Codex subscription-auth stream."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from tools.release.github_artifacts import (
    ArtifactMetadata,
    ExpectedWorkflowAttempt,
    GitHubArtifactClient,
    WorkflowAttempt,
    WorkflowEvent,
    artifact_name_for_attempt,
)
from tools.release.isolated_inspection import InspectorRole, install_principal_file

_CODEX_AUTH_HOME = "CODEX_HOME"
CODEX_AUTH_FILENAME = "auth.json"
_AUTH_ENVELOPE_FILENAME = "auth-envelope.json"
_AUTH_CIPHERTEXT_FILENAME = "auth-state.age"
_AUTH_STATE_PREFIX = "codex-auth-state"
_AUTH_BEGIN_PREFIX = "codex-auth-state-begun"
_AUTH_SETTLED_PREFIX = "codex-auth-state-settled"
_AUTH_SEEDED_PREFIX = "codex-auth-state-seeded"
_AGE_BINARY = "age"
_AGE_KEYGEN_BINARY = "age-keygen"
_AGE_ENCRYPT = "--encrypt"
_AGE_DECRYPT = "--decrypt"
_AGE_RECIPIENT_FLAG = "--recipient"
_AGE_IDENTITY_FLAG = "--identity"
_AGE_PUBLIC_FLAG = "-y"
_AGE_SECRET_ENVIRONMENT = "CODEX_AUTH_AGE_IDENTITY"
_CODEX_AUTH_MODE = "chatgpt"
_REFRESH_TOKEN_KEY = "refresh_token"
_AUTH_GENERATION_WIDTH = 8
_MAX_AUTH_BYTES = 4 * 1024 * 1024
_AGE_TIMEOUT_SECONDS = 30
_AGE_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "HOME": "/"}
_JSON_ENCODING = "utf-8"
_JSON_INDENT = 2
_JSON_MODE = "json"
_JSON_ENSURE_ASCII = True
_BACKSLASH_REPLACE = "backslashreplace"
_SHA256_PREFIX = "sha256:"
_AGE_RECIPIENT_PATTERN = re.compile(r"age1[a-z0-9]{20,200}\Z")
_ARTIFACT_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_AUTH_ARTIFACT_PATTERN = re.compile(
    r"codex-auth-state-(?P<phase>begun|settled|seeded)-g(?P<generation>[0-9]+)"
    r"(?:-seed-(?P<seed>[A-Za-z0-9_-]{1,64}))?-attempt-(?P<run>[0-9]+)-(?P<attempt>[0-9]+)\Z"
)
_SEED_OPERATION_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_MATCH_PHASE_GROUP = "phase"
_MATCH_GENERATION_GROUP = "generation"
_MATCH_SEED_GROUP = "seed"
_MATCH_RUN_GROUP = "run"
_MATCH_ATTEMPT_GROUP = "attempt"
_WORKFLOW_PATH_SUFFIX_SEPARATOR = "@"
_EMPTY = ""
_NAME_SEPARATOR = "-"
_GENERATION_MARKER = "g"
_SEED_MARKER = "seed"
_ATTEMPT_MARKER = "attempt"
_BEGUN_ARCHIVE_FILES = frozenset({_AUTH_ENVELOPE_FILENAME})
_SEALED_ARCHIVE_FILES = frozenset({_AUTH_ENVELOPE_FILENAME, _AUTH_CIPHERTEXT_FILENAME})
_SCHEMA_VERSION = 1
_AUTH_IDENTITY_REQUIRED = "The serialized Codex authentication state is unavailable."
_AUTH_STATE_UNCERTAIN = "A Codex-auth attempt began without a matching settled state."
_AUTH_STATE_CONFLICT = "The Codex-auth artifact history contains conflicting state identities."
_AUTH_STATE_ARTIFACT_MISSING = "A required Codex-auth artifact expired or is missing."
_AUTH_STATE_INVALID = "The encrypted Codex-auth state does not match its producer record."
_AUTH_INPUT_INVALID = "The Codex auth cache is not a refreshable ChatGPT-managed login."
_AGE_OPERATION_FAILED = "The age cryptographic operation failed."
_AGE_IDENTITY_INVALID = "The configured age identity has no valid public recipient."
_AGE_BINARY_UNAVAILABLE = "The pinned age tool is unavailable."
_AGE_ENVELOPE_MISMATCH = "The authenticated age envelope does not match its artifact."
_SEED_OPERATION_CONFLICT = "A seed operation id was reused with different auth material."
_SEED_OPERATION_ID_INVALID = "The seed operation id is malformed."
_BEGIN_POINTER_REQUIRED = "A settled Codex-auth state requires its begin checkpoint."
_CIPHERTEXT_DIGEST_REQUIRED = "A sealed Codex-auth state requires a ciphertext digest."
_SEED_METADATA_REQUIRED = "A seeded Codex-auth state requires an explicit seed identity."
_PREDECESSOR_MISMATCH = "The settled auth state does not follow its recorded predecessor."
_AUTH_PHASE = "phase"
_AUTH_GENERATION = "generation"
_AUTH_SCHEMA_VERSION = "schema_version"
_WORKFLOW_PRODUCER = "workflow_producer"
_PREDECESSOR = "predecessor"
_BEGIN_CHECKPOINT = "begin_checkpoint"
_SEED_OPERATION_ID = "seed_operation_id"
_SEED_FINGERPRINT = "seed_fingerprint"
_CIPHERTEXT_SHA256 = "ciphertext_sha256"
_RESEED = "reseed"
_DOWNLOAD_DIRECTORY = "download"
_AGE_IDENTITY_FILENAME = "codex-auth.agekey"
_PRIVATE_FILE_MODE = 0o600
_SENSITIVE_MODE_MASK = 0o077
_PRIVATE_ARTIFACT_DIRECTORY_MODE = 0o700
_PRIVATE_DIRECTORY_INVALID = "The controller age-identity directory is unavailable."


class AuthArtifactPhase(StrEnum):
    """Immutable checkpoint states for one serialized account-auth stream."""

    BEGUN = "begun"
    SETTLED = "settled"
    SEEDED = "seeded"


class AuthRecord(BaseModel):
    """Strict immutable state records stored beside encrypted auth material."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class AuthProducer(AuthRecord):
    """Workflow provenance bound to an auth-state transition."""

    repository: str
    workflow_path: str
    event: WorkflowEvent
    ref: str
    run_id: int
    run_attempt: int
    head_sha: str


class ArtifactReference(AuthRecord):
    """Remote identity of an immutable Actions artifact used in the auth chain."""

    artifact_id: int
    name: str
    digest: str
    generation: int
    run_id: int
    run_attempt: int
    age_recipient_sha256: str


class AuthEnvelope(AuthRecord):
    """Producer, generation, and predecessor metadata authenticated beside ciphertext."""

    schema_version: int
    phase: AuthArtifactPhase
    generation: int
    workflow_producer: AuthProducer
    predecessor: ArtifactReference | None
    begin_checkpoint: ArtifactReference | None
    seed_operation_id: str | None
    seed_fingerprint: str | None
    ciphertext_sha256: str | None
    age_recipient_sha256: str | None
    reseed: bool

    @model_validator(mode="after")
    def validate_phase_fields(self) -> Self:
        """Require each state phase to carry only its own structured proof fields."""
        if self.generation < 1:
            raise ValueError(_AUTH_STATE_INVALID)
        if self.phase is AuthArtifactPhase.BEGUN:
            if self.predecessor is None or self.begin_checkpoint is not None or self.ciphertext_sha256 is not None:
                raise ValueError(_PREDECESSOR_MISMATCH)
            if self.age_recipient_sha256 is None:
                raise ValueError(_AGE_IDENTITY_INVALID)
            if self.seed_operation_id is not None or self.seed_fingerprint is not None or self.reseed:
                raise ValueError(_AUTH_STATE_INVALID)
        elif self.phase is AuthArtifactPhase.SETTLED:
            if self.begin_checkpoint is None or self.predecessor is None:
                raise ValueError(_BEGIN_POINTER_REQUIRED)
            if self.ciphertext_sha256 is None or self.age_recipient_sha256 is None:
                raise ValueError(_CIPHERTEXT_DIGEST_REQUIRED)
            if self.seed_operation_id is not None or self.seed_fingerprint is not None or self.reseed:
                raise ValueError(_AUTH_STATE_INVALID)
        elif self.phase is AuthArtifactPhase.SEEDED:
            if (
                self.seed_operation_id is None
                or self.seed_fingerprint is None
                or self.ciphertext_sha256 is None
                or self.age_recipient_sha256 is None
            ):
                raise ValueError(_SEED_METADATA_REQUIRED)
            if self.begin_checkpoint is not None:
                raise ValueError(_AUTH_STATE_INVALID)
            if not self.reseed and (self.generation != 1 or self.predecessor is not None):
                raise ValueError(_AUTH_STATE_INVALID)
            if self.reseed and self.generation < 2:
                raise ValueError(_AUTH_STATE_INVALID)
        return self


class AuthArtifactCoordinates(AuthRecord):
    """Structured fields parsed from an auth artifact's deterministic name."""

    phase: AuthArtifactPhase
    generation: int
    seed_operation_id: str | None
    run_id: int
    run_attempt: int


class CodexAuthSnapshot(AuthRecord):
    """Minimum declared shape needed for Codex-managed ChatGPT refresh and recovery."""

    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)

    auth_mode: Literal["chatgpt"]
    tokens: dict[str, str | None]

    @model_validator(mode="after")
    def has_refresh_token(self) -> Self:
        """Require the credential component Codex needs to refresh the managed login."""
        if not self.tokens.get(_REFRESH_TOKEN_KEY):
            raise ValueError(_AUTH_INPUT_INVALID)
        return self


class RestoredAuthState(AuthRecord):
    """Current authenticated cache copied into the isolated Codex home."""

    envelope: AuthEnvelope
    artifact: ArtifactReference
    auth_file: Path


class AuthUseLease(AuthRecord):
    """Generation and checkpoint that must be settled after Codex exits."""

    envelope: AuthEnvelope
    artifact_directory: Path
    artifact_name: str


def auth_artifact_name(
    phase: AuthArtifactPhase,
    generation: int,
    workflow: WorkflowAttempt,
    repository: str,
    seed_operation_id: str | None = None,
) -> str:
    """Name an immutable auth artifact with its generation and exact workflow attempt."""
    if generation < 1:
        raise ValueError(_AUTH_STATE_INVALID)
    base_parts = [_AUTH_STATE_PREFIX, phase.value, _GENERATION_MARKER + str(generation).zfill(_AUTH_GENERATION_WIDTH)]
    if phase is AuthArtifactPhase.SEEDED:
        if seed_operation_id is None or _SEED_OPERATION_PATTERN.fullmatch(seed_operation_id) is None:
            raise ValueError(_SEED_OPERATION_ID_INVALID)
        base_parts.extend((_SEED_MARKER, seed_operation_id))
    elif seed_operation_id is not None:
        raise ValueError(_AUTH_STATE_INVALID)
    expected = _expected_from_workflow(repository, workflow)
    return artifact_name_for_attempt(_NAME_SEPARATOR.join(base_parts), expected)


def artifact_reference_for_upload(
    artifact: ArtifactMetadata,
    generation: int,
    run_id: int,
    run_attempt: int,
    age_recipient_sha256: str,
) -> ArtifactReference:
    """Bind a finalized begin-checkpoint upload to its authenticated API identity."""
    coordinates = _parse_auth_artifact_name(artifact.name)
    if (
        coordinates.generation != generation
        or coordinates.run_id != run_id
        or coordinates.run_attempt != run_attempt
        or coordinates.phase is not AuthArtifactPhase.BEGUN
        or artifact.digest is None
        or _ARTIFACT_DIGEST_PATTERN.fullmatch(artifact.digest) is None
        or _ARTIFACT_DIGEST_PATTERN.fullmatch(age_recipient_sha256) is None
    ):
        raise RuntimeError(_AUTH_STATE_INVALID)
    return ArtifactReference(
        artifact_id=artifact.id,
        name=artifact.name,
        digest=artifact.digest,
        generation=generation,
        run_id=run_id,
        run_attempt=run_attempt,
        age_recipient_sha256=age_recipient_sha256,
    )


def age_identity_fingerprint(identity_text: str, controller_directory: Path) -> str:
    """Return the stable public-recipient fingerprint used to reject stale encrypted state."""
    return _age_recipient_fingerprint(identity_text, controller_directory)


def write_begin_checkpoint(
    workflow: WorkflowAttempt,
    repository: str,
    predecessor: ArtifactReference,
    output_directory: Path,
) -> AuthUseLease:
    """Write and name the checkpoint that must precede any Codex auth refresh."""
    generation = predecessor.generation + 1
    envelope = AuthEnvelope(
        schema_version=_SCHEMA_VERSION,
        phase=AuthArtifactPhase.BEGUN,
        generation=generation,
        workflow_producer=_producer(repository, workflow),
        predecessor=predecessor,
        begin_checkpoint=None,
        seed_operation_id=None,
        seed_fingerprint=None,
        ciphertext_sha256=None,
        age_recipient_sha256=predecessor.age_recipient_sha256,
        reseed=False,
    )
    _write_new_artifact_directory(output_directory)
    _write_envelope(output_directory, envelope)
    return AuthUseLease(
        envelope=envelope,
        artifact_directory=output_directory,
        artifact_name=auth_artifact_name(AuthArtifactPhase.BEGUN, generation, workflow, repository),
    )


def write_settled_auth_state(
    lease: AuthUseLease,
    begin_reference: ArtifactReference,
    auth_json: bytes,
    identity_text: str,
    controller_directory: Path,
    output_directory: Path,
) -> tuple[AuthEnvelope, str]:
    """Validate, encrypt, and name the updated auth cache after inspector descendants exit."""
    if (
        begin_reference.generation != lease.envelope.generation
        or begin_reference.name != lease.artifact_name
        or begin_reference.run_id != lease.envelope.workflow_producer.run_id
        or begin_reference.run_attempt != lease.envelope.workflow_producer.run_attempt
        or begin_reference.age_recipient_sha256 != lease.envelope.age_recipient_sha256
    ):
        raise ValueError(_PREDECESSOR_MISMATCH)
    _validate_auth_cache(auth_json)
    _write_new_artifact_directory(output_directory)
    ciphertext, recipient_fingerprint = _encrypt_auth_cache(auth_json, identity_text, controller_directory)
    if lease.envelope.predecessor is None or lease.envelope.predecessor.age_recipient_sha256 != recipient_fingerprint:
        raise RuntimeError(_AGE_IDENTITY_INVALID)
    ciphertext_digest = _sha256(ciphertext)
    envelope = AuthEnvelope(
        schema_version=_SCHEMA_VERSION,
        phase=AuthArtifactPhase.SETTLED,
        generation=lease.envelope.generation,
        workflow_producer=lease.envelope.workflow_producer,
        predecessor=lease.envelope.predecessor,
        begin_checkpoint=begin_reference,
        seed_operation_id=None,
        seed_fingerprint=None,
        ciphertext_sha256=ciphertext_digest,
        age_recipient_sha256=recipient_fingerprint,
        reseed=False,
    )
    _write_envelope(output_directory, envelope)
    (output_directory / _AUTH_CIPHERTEXT_FILENAME).write_bytes(ciphertext)
    return envelope, _auth_artifact_name_for_producer(
        AuthArtifactPhase.SETTLED,
        envelope.generation,
        envelope.workflow_producer,
    )


def write_seeded_auth_state(
    seed_ciphertext: bytes,
    identity_text: str,
    seed_operation_id: str,
    generation: int,
    workflow: WorkflowAttempt,
    repository: str,
    predecessor: ArtifactReference | None,
    reseed: bool,
    controller_directory: Path,
    output_directory: Path,
) -> tuple[AuthEnvelope, str]:
    """Validate a pre-encrypted seed and materialize an explicit idempotent seed artifact."""
    if _SEED_OPERATION_PATTERN.fullmatch(seed_operation_id) is None:
        raise ValueError(_SEED_OPERATION_ID_INVALID)
    if not reseed and (predecessor is not None or generation != 1):
        raise ValueError(_AUTH_STATE_INVALID)
    if reseed and generation < 2:
        raise ValueError(_PREDECESSOR_MISMATCH)
    if predecessor is not None and generation != predecessor.generation + 1:
        raise ValueError(_PREDECESSOR_MISMATCH)
    plaintext = _decrypt_auth_cache(seed_ciphertext, identity_text, controller_directory)
    _validate_auth_cache(plaintext)
    recipient_fingerprint = _age_recipient_fingerprint(identity_text, controller_directory)
    _write_new_artifact_directory(output_directory)
    ciphertext_digest = _sha256(seed_ciphertext)
    envelope = AuthEnvelope(
        schema_version=_SCHEMA_VERSION,
        phase=AuthArtifactPhase.SEEDED,
        generation=generation,
        workflow_producer=_producer(repository, workflow),
        predecessor=predecessor,
        begin_checkpoint=None,
        seed_operation_id=seed_operation_id,
        seed_fingerprint=_sha256(plaintext),
        ciphertext_sha256=ciphertext_digest,
        age_recipient_sha256=recipient_fingerprint,
        reseed=reseed,
    )
    _write_envelope(output_directory, envelope)
    (output_directory / _AUTH_CIPHERTEXT_FILENAME).write_bytes(seed_ciphertext)
    return envelope, _auth_artifact_name_for_producer(
        AuthArtifactPhase.SEEDED,
        generation,
        _producer(repository, workflow),
        seed_operation_id,
    )


def restore_latest_auth_state(
    client: GitHubArtifactClient,
    repository: str,
    identity_text: str,
    controller_directory: Path,
    codex_home: Path,
) -> RestoredAuthState:
    """Restore only the newest complete authenticated cache; never fall back to an old seed."""
    valid_artifacts = _validated_auth_artifacts(client, repository)
    terminal_by_generation: dict[int, tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]] = {}
    begin_by_generation: dict[int, tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]] = {}
    for artifact, coordinates, workflow in valid_artifacts:
        group = begin_by_generation if coordinates.phase is AuthArtifactPhase.BEGUN else terminal_by_generation
        if coordinates.generation in group:
            raise RuntimeError(_AUTH_STATE_CONFLICT)
        group[coordinates.generation] = (artifact, coordinates, workflow)
    if not terminal_by_generation:
        raise RuntimeError(_AUTH_IDENTITY_REQUIRED)
    generation = max(terminal_by_generation)
    artifact, coordinates, workflow = terminal_by_generation[generation]
    if artifact.expired:
        raise RuntimeError(_AUTH_STATE_ARTIFACT_MISSING)
    expected_files = _SEALED_ARCHIVE_FILES
    expected_name = auth_artifact_name(
        coordinates.phase,
        generation,
        workflow,
        repository,
        coordinates.seed_operation_id,
    )
    if coordinates.phase not in {AuthArtifactPhase.SETTLED, AuthArtifactPhase.SEEDED}:
        raise RuntimeError(_AUTH_STATE_INVALID)
    with tempfile.TemporaryDirectory(dir=controller_directory) as download_temp:
        downloaded = client.download_artifact(
            artifact,
            workflow,
            expected_name,
            Path(download_temp) / _DOWNLOAD_DIRECTORY,
            expected_files,
        )
        envelope = _read_envelope(downloaded.extracted_directory)
        recipient_fingerprint = _age_recipient_fingerprint(identity_text, controller_directory)
        _verify_envelope(envelope, coordinates, workflow, repository, artifact, recipient_fingerprint)
        reseed_generation = _verify_selected_auth_chain(
            client,
            repository,
            envelope,
            begin_by_generation,
            terminal_by_generation,
            recipient_fingerprint,
            controller_directory,
            inspect_ancestry=bool(set(begin_by_generation) - set(terminal_by_generation)),
        )
        _verify_unsettled_history(
            envelope,
            begin_by_generation,
            terminal_by_generation,
            generation,
            reseed_generation=reseed_generation,
        )
        ciphertext = (downloaded.extracted_directory / _AUTH_CIPHERTEXT_FILENAME).read_bytes()
        if _sha256(ciphertext) != envelope.ciphertext_sha256:
            raise RuntimeError(_AGE_ENVELOPE_MISMATCH)
        plaintext = _decrypt_auth_cache(ciphertext, identity_text, controller_directory)
        _validate_auth_cache(plaintext)
        auth_path = codex_home / CODEX_AUTH_FILENAME
        install_principal_file(
            InspectorRole.CODEX,
            controller_directory,
            auth_path,
            plaintext,
            max_bytes=_MAX_AUTH_BYTES,
        )
    reference = _artifact_reference(artifact, coordinates, envelope)
    return RestoredAuthState(envelope=envelope, artifact=reference, auth_file=auth_path)


def next_auth_generation(client: GitHubArtifactClient, repository: str) -> int:
    """Choose the next generation for an explicit seed or reseed under serialization."""
    valid_artifacts = _validated_auth_artifacts(client, repository)
    return max((coordinates.generation for _, coordinates, _ in valid_artifacts), default=0) + 1


def find_existing_seed_operation(
    client: GitHubArtifactClient,
    repository: str,
    seed_operation_id: str,
    seed_ciphertext: bytes,
    identity_text: str,
    controller_directory: Path,
) -> ArtifactReference | None:
    """Resolve an exact prior seed write so a retry never starts a second generation."""
    if _SEED_OPERATION_PATTERN.fullmatch(seed_operation_id) is None:
        raise ValueError(_SEED_OPERATION_ID_INVALID)
    plaintext = _decrypt_auth_cache(seed_ciphertext, identity_text, controller_directory)
    _validate_auth_cache(plaintext)
    seed_fingerprint = _sha256(plaintext)
    candidates = [
        (artifact, coordinates, workflow)
        for artifact, coordinates, workflow in _validated_auth_artifacts(
            client,
            repository,
        )
        if coordinates.phase is AuthArtifactPhase.SEEDED and coordinates.seed_operation_id == seed_operation_id
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise RuntimeError(_AUTH_STATE_CONFLICT)
    artifact, coordinates, workflow = candidates[0]
    if artifact.expired:
        raise RuntimeError(_AUTH_STATE_ARTIFACT_MISSING)
    expected_name = auth_artifact_name(
        AuthArtifactPhase.SEEDED,
        coordinates.generation,
        workflow,
        repository,
        seed_operation_id,
    )
    with tempfile.TemporaryDirectory(dir=controller_directory) as download_temp:
        downloaded = client.download_artifact(
            artifact,
            workflow,
            expected_name,
            Path(download_temp) / _DOWNLOAD_DIRECTORY,
            _SEALED_ARCHIVE_FILES,
        )
        envelope = _read_envelope(downloaded.extracted_directory)
    recipient_fingerprint = _age_recipient_fingerprint(identity_text, controller_directory)
    _verify_envelope(envelope, coordinates, workflow, repository, artifact, recipient_fingerprint)
    if envelope.seed_operation_id != seed_operation_id or envelope.seed_fingerprint != seed_fingerprint:
        raise RuntimeError(_SEED_OPERATION_CONFLICT)
    return _artifact_reference(artifact, coordinates, envelope)


def _validated_auth_artifacts(
    client: GitHubArtifactClient,
    repository: str,
) -> list[tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]]:
    """Authenticate state artifacts only from release workflow runs and their exact attempts."""
    result: list[tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]] = []
    workflows: dict[tuple[int, int], WorkflowAttempt] = {}
    for current_attempt in client.list_release_workflow_attempts(repository):
        for artifact in client.list_artifacts_for_attempt(current_attempt):
            if not artifact.name.startswith(_AUTH_STATE_PREFIX + _NAME_SEPARATOR):
                continue
            coordinates = _parse_auth_artifact_name(artifact.name)
            if artifact.workflow_run.id != current_attempt.id or coordinates.run_id != current_attempt.id:
                raise RuntimeError(_AUTH_STATE_CONFLICT)
            run_key = (coordinates.run_id, coordinates.run_attempt)
            workflow = workflows.get(run_key)
            if workflow is None:
                workflow = client.get_release_workflow_attempt(
                    repository,
                    coordinates.run_id,
                    coordinates.run_attempt,
                )
                workflows[run_key] = workflow
            client.verify_artifact_producer(artifact, workflow)
            expected_name = auth_artifact_name(
                coordinates.phase,
                coordinates.generation,
                workflow,
                repository,
                coordinates.seed_operation_id,
            )
            if artifact.name != expected_name:
                raise RuntimeError(_AUTH_STATE_CONFLICT)
            result.append((artifact, coordinates, workflow))
    return result


def _parse_auth_artifact_name(name: str) -> AuthArtifactCoordinates:
    """Parse a deterministic state-artifact name without interpreting free-text content."""
    match = _AUTH_ARTIFACT_PATTERN.fullmatch(name)
    if match is None:
        raise RuntimeError(_AUTH_STATE_CONFLICT)
    return AuthArtifactCoordinates(
        phase=AuthArtifactPhase(match.group(_MATCH_PHASE_GROUP)),
        generation=int(match.group(_MATCH_GENERATION_GROUP)),
        seed_operation_id=match.group(_MATCH_SEED_GROUP),
        run_id=int(match.group(_MATCH_RUN_GROUP)),
        run_attempt=int(match.group(_MATCH_ATTEMPT_GROUP)),
    )


def _verify_begin_checkpoint(
    client: GitHubArtifactClient,
    repository: str,
    settled: AuthEnvelope,
    begin: tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt] | None,
) -> None:
    """Verify the settled state follows the exact previously uploaded begin artifact."""
    if begin is None or settled.begin_checkpoint is None:
        raise RuntimeError(_AUTH_STATE_UNCERTAIN)
    artifact, coordinates, workflow = begin
    expected_name = auth_artifact_name(AuthArtifactPhase.BEGUN, coordinates.generation, workflow, repository)
    with tempfile.TemporaryDirectory() as download_temp:
        downloaded = client.download_artifact(
            artifact,
            workflow,
            expected_name,
            Path(download_temp) / _DOWNLOAD_DIRECTORY,
            _BEGUN_ARCHIVE_FILES,
        )
        begin_envelope = _read_envelope(downloaded.extracted_directory)
    expected_reference = _artifact_reference(artifact, coordinates, begin_envelope)
    if settled.begin_checkpoint != expected_reference:
        raise RuntimeError(_AUTH_STATE_CONFLICT)
    if (
        begin_envelope.schema_version != _SCHEMA_VERSION
        or begin_envelope.phase is not AuthArtifactPhase.BEGUN
        or begin_envelope.generation != settled.generation
        or begin_envelope.workflow_producer != _producer(repository, workflow)
        or settled.workflow_producer != begin_envelope.workflow_producer
    ):
        raise RuntimeError(_AUTH_STATE_UNCERTAIN)
    if begin_envelope.predecessor != settled.predecessor:
        raise RuntimeError(_AUTH_STATE_UNCERTAIN)


def _verify_predecessor_state(
    client: GitHubArtifactClient,
    repository: str,
    envelope: AuthEnvelope,
    terminal: dict[int, tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]],
    recipient_fingerprint: str,
    controller_directory: Path,
) -> AuthEnvelope:
    """Require a settled candidate to follow the exact retained immediately prior state."""
    predecessor_generation = envelope.generation - 1
    predecessor = terminal.get(predecessor_generation)
    if envelope.predecessor is None or predecessor is None:
        raise RuntimeError(_AUTH_STATE_ARTIFACT_MISSING)
    artifact, coordinates, workflow = predecessor
    if artifact.expired:
        raise RuntimeError(_AUTH_STATE_ARTIFACT_MISSING)
    expected_name = auth_artifact_name(
        coordinates.phase,
        coordinates.generation,
        workflow,
        repository,
        coordinates.seed_operation_id,
    )
    with tempfile.TemporaryDirectory(dir=controller_directory) as download_temp:
        downloaded = client.download_artifact(
            artifact,
            workflow,
            expected_name,
            Path(download_temp) / _DOWNLOAD_DIRECTORY,
            _SEALED_ARCHIVE_FILES,
        )
        previous_envelope = _read_envelope(downloaded.extracted_directory)
        _verify_envelope(
            previous_envelope,
            coordinates,
            workflow,
            repository,
            artifact,
            recipient_fingerprint,
        )
        previous_ciphertext = (downloaded.extracted_directory / _AUTH_CIPHERTEXT_FILENAME).read_bytes()
    if _sha256(previous_ciphertext) != previous_envelope.ciphertext_sha256:
        raise RuntimeError(_AGE_ENVELOPE_MISMATCH)
    if _artifact_reference(artifact, coordinates, previous_envelope) != envelope.predecessor:
        raise RuntimeError(_PREDECESSOR_MISMATCH)
    return previous_envelope


def _verify_selected_auth_chain(
    client: GitHubArtifactClient,
    repository: str,
    envelope: AuthEnvelope,
    begun: dict[int, tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]],
    terminal: dict[int, tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]],
    recipient_fingerprint: str,
    controller_directory: Path,
    *,
    inspect_ancestry: bool,
) -> int | None:
    """Find recovery authority only through exact verified predecessor and begin records."""
    current = envelope
    while current.phase is AuthArtifactPhase.SETTLED:
        previous = _verify_predecessor_state(
            client, repository, current, terminal, recipient_fingerprint, controller_directory
        )
        _verify_begin_checkpoint(client, repository, current, begun.get(current.generation))
        current = previous
        if not inspect_ancestry:
            return None
    if current.phase is AuthArtifactPhase.SEEDED and current.reseed:
        return current.generation
    return None


def _verify_unsettled_history(
    envelope: AuthEnvelope,
    begun: dict[int, tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]],
    terminal: dict[int, tuple[ArtifactMetadata, AuthArtifactCoordinates, WorkflowAttempt]],
    generation: int,
    *,
    reseed_generation: int | None = None,
) -> None:
    """Reject unfinished use except history older than the selected chain's verified reseed."""
    unresolved = set(begun) - set(terminal)
    boundary = generation if envelope.phase is AuthArtifactPhase.SEEDED and envelope.reseed else reseed_generation
    if unresolved and (boundary is None or any(item >= boundary for item in unresolved)):
        raise RuntimeError(_AUTH_STATE_UNCERTAIN)
    if any(
        begun_generation in terminal and terminal[begun_generation][1].phase is not AuthArtifactPhase.SETTLED
        for begun_generation in begun
    ):
        raise RuntimeError(_AUTH_STATE_CONFLICT)


def _read_envelope(directory: Path) -> AuthEnvelope:
    """Strictly validate the envelope carried by one authenticated artifact."""
    try:
        return AuthEnvelope.model_validate_json((directory / _AUTH_ENVELOPE_FILENAME).read_bytes())
    except (OSError, ValidationError):
        raise RuntimeError(_AUTH_STATE_INVALID) from None


def _verify_envelope(
    envelope: AuthEnvelope,
    coordinates: AuthArtifactCoordinates,
    workflow: WorkflowAttempt,
    repository: str,
    artifact: ArtifactMetadata,
    recipient_fingerprint: str,
) -> None:
    """Match encrypted payload metadata to its remote artifact and workflow provenance."""
    if (
        envelope.schema_version != _SCHEMA_VERSION
        or envelope.generation != coordinates.generation
        or envelope.phase is not coordinates.phase
        or envelope.workflow_producer != _producer(repository, workflow)
        or envelope.phase is AuthArtifactPhase.BEGUN
        or envelope.ciphertext_sha256 is None
        or envelope.age_recipient_sha256 != recipient_fingerprint
        or artifact.name
        != auth_artifact_name(
            coordinates.phase,
            coordinates.generation,
            workflow,
            repository,
            coordinates.seed_operation_id,
        )
    ):
        raise RuntimeError(_AUTH_STATE_INVALID)


def _artifact_reference(
    artifact: ArtifactMetadata,
    coordinates: AuthArtifactCoordinates,
    envelope: AuthEnvelope,
) -> ArtifactReference:
    """Create a typed pointer to one remote GitHub artifact."""
    if artifact.digest is None:
        raise RuntimeError(_AUTH_STATE_ARTIFACT_MISSING)
    if envelope.age_recipient_sha256 is None:
        raise RuntimeError(_AUTH_STATE_INVALID)
    return ArtifactReference(
        artifact_id=artifact.id,
        name=artifact.name,
        digest=artifact.digest,
        generation=coordinates.generation,
        run_id=coordinates.run_id,
        run_attempt=coordinates.run_attempt,
        age_recipient_sha256=envelope.age_recipient_sha256,
    )


def _producer(repository: str, workflow: WorkflowAttempt) -> AuthProducer:
    """Copy the verified workflow identity into the encrypted-state chain."""
    try:
        event = WorkflowEvent(workflow.event)
    except ValueError:
        raise RuntimeError(_AUTH_STATE_INVALID) from None
    workflow_path = workflow.path.split(_WORKFLOW_PATH_SUFFIX_SEPARATOR, maxsplit=1)[0]
    return AuthProducer(
        repository=repository,
        workflow_path=workflow_path,
        event=event,
        ref=workflow.branch_ref,
        run_id=workflow.id,
        run_attempt=workflow.run_attempt,
        head_sha=workflow.head_sha,
    )


def _expected_from_workflow(repository: str, workflow: WorkflowAttempt) -> ExpectedWorkflowAttempt:
    """Create a strict expected-run record from verified API metadata."""
    return ExpectedWorkflowAttempt(
        repository=repository,
        workflow_path=workflow.path.split(_WORKFLOW_PATH_SUFFIX_SEPARATOR, maxsplit=1)[0],
        event=WorkflowEvent(workflow.event),
        ref=workflow.branch_ref,
        run_id=workflow.id,
        run_attempt=workflow.run_attempt,
    )


def _auth_artifact_name_for_producer(
    phase: AuthArtifactPhase,
    generation: int,
    producer: AuthProducer,
    seed_operation_id: str | None = None,
) -> str:
    """Name a state artifact from its already-verified workflow producer record."""
    expected = ExpectedWorkflowAttempt(
        repository=producer.repository,
        workflow_path=producer.workflow_path,
        event=producer.event,
        ref=producer.ref,
        run_id=producer.run_id,
        run_attempt=producer.run_attempt,
    )
    base_parts = [_AUTH_STATE_PREFIX, phase.value, _GENERATION_MARKER + str(generation).zfill(_AUTH_GENERATION_WIDTH)]
    if phase is AuthArtifactPhase.SEEDED:
        if seed_operation_id is None or _SEED_OPERATION_PATTERN.fullmatch(seed_operation_id) is None:
            raise ValueError(_SEED_OPERATION_ID_INVALID)
        base_parts.extend((_SEED_MARKER, seed_operation_id))
    elif seed_operation_id is not None:
        raise ValueError(_AUTH_STATE_INVALID)
    return artifact_name_for_attempt(_NAME_SEPARATOR.join(base_parts), expected)


def _write_new_artifact_directory(directory: Path) -> None:
    """Create one controller-owned directory for an immutable artifact upload."""
    if directory.exists() or directory.is_symlink():
        raise ValueError(_AUTH_STATE_CONFLICT)
    directory.mkdir(mode=_PRIVATE_ARTIFACT_DIRECTORY_MODE, parents=True)


def _write_envelope(directory: Path, envelope: AuthEnvelope) -> None:
    """Write compact structured envelope metadata without logging private state."""
    (directory / _AUTH_ENVELOPE_FILENAME).write_text(
        json.dumps(envelope.model_dump(mode=_JSON_MODE), ensure_ascii=_JSON_ENSURE_ASCII, indent=_JSON_INDENT),
        encoding=_JSON_ENCODING,
    )


def _validate_auth_cache(auth_json: bytes) -> CodexAuthSnapshot:
    """Require the refreshable ChatGPT-managed cache shape without echoing its contents."""
    if not auth_json or len(auth_json) > _MAX_AUTH_BYTES:
        raise ValueError(_AUTH_INPUT_INVALID)
    try:
        return CodexAuthSnapshot.model_validate_json(auth_json)
    except ValidationError:
        raise ValueError(_AUTH_INPUT_INVALID) from None


def auth_secret_values(auth_json: bytes) -> tuple[str, ...]:
    """Return credential values for exact-value diagnostic redaction in the controller."""
    snapshot = _validate_auth_cache(auth_json)
    return tuple(value for value in snapshot.tokens.values() if value is not None)


def _age_recipient(identity_text: str, controller_directory: Path) -> str:
    """Derive an age recipient through age-keygen, without implementing cryptography."""
    identity_path = _write_age_identity(identity_text, controller_directory)
    age_keygen = _resolve_age_binary(_AGE_KEYGEN_BINARY)
    try:
        result = subprocess.run(
            [age_keygen, _AGE_PUBLIC_FLAG, str(identity_path)],
            env=_AGE_ENVIRONMENT,
            capture_output=True,
            check=False,
            timeout=_AGE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(_AGE_OPERATION_FAILED) from None
    recipient = result.stdout.decode(_JSON_ENCODING, errors=_BACKSLASH_REPLACE).strip()
    if result.returncode != 0 or _AGE_RECIPIENT_PATTERN.fullmatch(recipient) is None:
        raise RuntimeError(_AGE_IDENTITY_INVALID)
    return recipient


def _encrypt_auth_cache(
    auth_json: bytes,
    identity_text: str,
    controller_directory: Path,
) -> tuple[bytes, str]:
    """Encrypt a validated auth cache to its derived public recipient."""
    recipient = _age_recipient(identity_text, controller_directory)
    age_binary = _resolve_age_binary(_AGE_BINARY)
    try:
        result = subprocess.run(
            [age_binary, _AGE_ENCRYPT, _AGE_RECIPIENT_FLAG, recipient],
            input=auth_json,
            env=_AGE_ENVIRONMENT,
            capture_output=True,
            check=False,
            timeout=_AGE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(_AGE_OPERATION_FAILED) from None
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(_AGE_OPERATION_FAILED)
    return result.stdout, _sha256(recipient.encode(_JSON_ENCODING))


def _decrypt_auth_cache(ciphertext: bytes, identity_text: str, controller_directory: Path) -> bytes:
    """Decrypt one artifact through age using the controller-only identity file."""
    identity_path = _write_age_identity(identity_text, controller_directory)
    age_binary = _resolve_age_binary(_AGE_BINARY)
    try:
        result = subprocess.run(
            [age_binary, _AGE_DECRYPT, _AGE_IDENTITY_FLAG, str(identity_path)],
            input=ciphertext,
            env=_AGE_ENVIRONMENT,
            capture_output=True,
            check=False,
            timeout=_AGE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError(_AGE_OPERATION_FAILED) from None
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(_AGE_OPERATION_FAILED)
    return result.stdout


def _write_age_identity(identity_text: str, controller_directory: Path) -> Path:
    """Write the stable age identity to a private controller-only staging file."""
    if not controller_directory.is_dir() or controller_directory.is_symlink():
        raise ValueError(_PRIVATE_DIRECTORY_INVALID)
    identity_path = controller_directory / _AGE_IDENTITY_FILENAME
    if identity_path.exists() or identity_path.is_symlink():
        if identity_path.is_symlink() or identity_path.read_text(encoding=_JSON_ENCODING) != identity_text:
            raise ValueError(_AGE_IDENTITY_INVALID)
        if identity_path.stat().st_mode & _SENSITIVE_MODE_MASK:
            raise ValueError(_PRIVATE_DIRECTORY_INVALID)
        return identity_path
    identity_path.write_text(identity_text, encoding=_JSON_ENCODING)
    identity_path.chmod(_PRIVATE_FILE_MODE)
    return identity_path


def _age_recipient_fingerprint(identity_text: str, controller_directory: Path) -> str:
    """Return a non-secret fingerprint that makes key rotation explicit to queued runs."""
    recipient = _age_recipient(identity_text, controller_directory)
    return _sha256(recipient.encode(_JSON_ENCODING))


def _resolve_age_binary(name: str) -> str:
    """Resolve the pinned age binary from the controller environment."""
    binary = shutil.which(name)
    if binary is None:
        raise FileNotFoundError(_AGE_BINARY_UNAVAILABLE)
    return binary


def _sha256(content: bytes) -> str:
    """Return the stable digest used to bind auth ciphertext to its envelope."""
    return _SHA256_PREFIX + hashlib.sha256(content).hexdigest()

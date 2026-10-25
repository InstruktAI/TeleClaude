"""Publish a proved candidate atomically while preserving advancing main."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import httpx
from git import Actor
from pydantic import ValidationError

from teleclaude.git import GitCommandError, Repo
from tools.ci.gha import append_output, repo_root
from tools.release.attempt import (
    CandidateIdentity,
    ProofIdentity,
    PublicationReceipt,
    PublicationState,
    ReleaseDecisionMode,
    load_candidate_identity,
    load_proof_identity,
    load_release_provenance,
    release_decision_digest,
    validate_runtime_acceptance_evidence,
)
from tools.release.changelog import compose_release_body, verify_commit_notes
from tools.release.github_artifacts import (
    RELEASE_BODY_LIMIT,
    GitHubArtifactClient,
    GitHubArtifactError,
    release_body_length,
)
from tools.release.project_metadata import (
    normalize_release_owned_file,
    normalized_tree_digest,
    read_locked_project_version,
    read_project_version,
    set_locked_project_version,
    set_project_version,
)

_GIT = "git"
_ORIGIN = "origin"
_MAIN = "refs/heads/main"
_REMOTE_MAIN = "refs/remotes/origin/main"
_CANDIDATE_REF_PREFIX = "refs/release/candidate/"
_RELEASE_FILES = (
    "CHANGELOG.md",
    "manifests/cli-surface.md",
    "manifests/events.md",
    "manifests/config.md",
    "release-provenance.json",
)
_BUNDLE_NAME = "candidate.bundle"
_CANDIDATE_NAME = "candidate-identity.json"
_PROOF_NAME = "proof-identity.json"
_RECEIPT_NAME = "publication-receipt.json"
_AUTHOR = Actor("github-actions[bot]", "github-actions[bot]@users.noreply.github.com")
_TOKEN_VARIABLE = "GH_TOKEN"
_REPOSITORY_VARIABLE = "GITHUB_REPOSITORY"
_RETRY_LIMIT = 5
_UTF8 = "utf-8"
_NEWLINE = "\n"
_JSON_INDENT = 2
_TAG_PATTERN = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
_SHA_PATTERN = re.compile(r"[0-9a-f]{40,64}\Z")
_EVIDENCE_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_EMPTY = ""
_ERROR = "The proved release could not be published safely."
_INPUT_INVALID = "The candidate, proof, or transfer artifact is incomplete or inconsistent."
_PROOF_REQUIRED = "Publication requires successful lint, full runtime acceptance, and installer proof for this exact candidate; rerun proof against the original candidate."
_TAG_CONFLICT = "The release tag already names a different candidate commit."
_ATOMIC_PUSH_FAILED = "Atomic publication failed without a concurrent main advancement to reconcile."
_RETRY_EXHAUSTED = "Main advanced repeatedly while publication was reconciled."
_TREE_MISMATCH = "The candidate bundle does not match its recorded commit and tree identity."
_PROVENANCE_MISMATCH = "The candidate history does not match its captured source and baseline."
_RECONCILIATION_MISMATCH = "Main reconciliation changed data outside release-owned metadata."
_RELEASE_CONFLICT = "An existing GitHub Release does not match this candidate and proof."
_OUTPUT_EXISTS = "The publication receipt path must be new."
_COMMAND_FAILED = "Publication command {command} failed with exit code {return_code}."
_RELEASE_NOTE_MISSING = "The candidate changelog has no section for its release tag."
_RELEASE_NOTES_MISMATCH = "The candidate changelog, notes artifact, and release decision do not match."
_RELEASE_MARKER = "<!-- teleclaude-release:v1"
_NO_BASELINE_LABEL = "none"
_GIT_CONFIG_COUNT = "GIT_CONFIG_COUNT"
_GIT_CONFIG_KEY = "GIT_CONFIG_KEY_0"
_GIT_CONFIG_VALUE = "GIT_CONFIG_VALUE_0"
_GIT_PROMPT = "GIT_TERMINAL_PROMPT"
_GITHUB_HTTP_CONFIG = "http.https://github.com/.extraheader"
_GITHUB_TOKEN_CREDENTIAL = "x-access-token:"
_BASIC_SCHEME = "AUTHORIZATION: basic "


def verify_candidate_bundle(
    repository_root: Path,
    candidate: CandidateIdentity,
    bundle_path: Path,
    github_token: str = _EMPTY,
) -> str:
    """Authenticate and import R from the exact incremental bundle recorded by its builder."""
    if (
        candidate.bundle_sha256 is None
        or hashlib.sha256(bundle_path.read_bytes()).hexdigest() != candidate.bundle_sha256
    ):
        raise ValueError(_INPUT_INVALID)
    if (
        _SHA_PATTERN.fullmatch(candidate.candidate_sha) is None
        or _SHA_PATTERN.fullmatch(candidate.candidate_tree_sha) is None
    ):
        raise ValueError(_INPUT_INVALID)
    root = repository_root.resolve()
    _git(root, "fetch", "--no-tags", _ORIGIN, _MAIN + ":" + _REMOTE_MAIN, github_token=github_token)
    baseline_tag = candidate.attempt.baseline_tag
    if baseline_tag is not None:
        _git(
            root,
            "fetch",
            "--no-tags",
            _ORIGIN,
            "refs/tags/" + baseline_tag + ":refs/tags/" + baseline_tag,
            github_token=github_token,
        )
    _run(root, [_GIT, "bundle", "verify", str(bundle_path)])
    candidate_ref = _candidate_ref(candidate)
    repo = Repo(root)
    existing_ref = _local_ref(root, candidate_ref)
    if existing_ref and existing_ref != candidate.candidate_sha:
        raise ValueError(_TREE_MISMATCH)
    if not existing_ref:
        _run(root, [_GIT, "fetch", "--no-tags", str(bundle_path), "HEAD:" + candidate_ref])
    commit = repo.commit(candidate_ref)
    if commit.hexsha != candidate.candidate_sha or commit.tree.hexsha != candidate.candidate_tree_sha:
        raise ValueError(_TREE_MISMATCH)
    attempt = candidate.attempt
    if len(commit.parents) != 1 or commit.parents[0].hexsha != attempt.source_sha:
        raise ValueError(_PROVENANCE_MISMATCH)
    if attempt.baseline_tag is None or attempt.baseline_sha is None:
        if attempt.decision_mode != ReleaseDecisionMode.MANUAL:
            raise ValueError(_PROVENANCE_MISMATCH)
    else:
        if repo.commit(attempt.baseline_tag).hexsha != attempt.baseline_sha:
            raise ValueError(_PROVENANCE_MISMATCH)
        try:
            repo.git.merge_base("--is-ancestor", attempt.baseline_sha, attempt.source_sha)
        except GitCommandError as exc:
            if exc.status != 1:
                raise
            raise ValueError(_PROVENANCE_MISMATCH) from None
    return candidate_ref


def build_reconciliation(repository_root: Path, candidate: CandidateIdentity, main_sha: str) -> str:
    """Build M with parents H,R and only R-owned release metadata on top of H."""
    root = repository_root.resolve()
    repo = Repo(root)
    source_sha = candidate.attempt.source_sha
    release_sha = candidate.candidate_sha
    if main_sha == source_sha:
        return release_sha
    try:
        repo.git.merge_base("--is-ancestor", release_sha, main_sha)
        return main_sha
    except GitCommandError as exc:
        if exc.status != 1:
            raise
    temp_parent = Path(tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix="release-main-reconcile-", dir=temp_parent) as temp_directory:
        worktree = Path(temp_directory) / "worktree"
        _run(root, [_GIT, "worktree", "add", "--detach", str(worktree), main_sha])
        try:
            h_repo = Repo(worktree)
            h_project = (worktree / "pyproject.toml").read_bytes()
            h_lock = (worktree / "uv.lock").read_bytes()
            updated_project = set_project_version(h_project, candidate.version.removeprefix("v"))
            updated_lock = set_locked_project_version(h_lock, candidate.version.removeprefix("v"))
            if read_project_version(
                _write_temp_payload(Path(temp_directory), "pyproject.toml", updated_project)
            ) != candidate.version.removeprefix("v"):
                raise ValueError(_RECONCILIATION_MISMATCH)
            if read_locked_project_version(
                _write_temp_payload(Path(temp_directory), "uv.lock", updated_lock)
            ) != candidate.version.removeprefix("v"):
                raise ValueError(_RECONCILIATION_MISMATCH)
            if normalize_release_owned_file("uv.lock", h_lock) != normalize_release_owned_file("uv.lock", updated_lock):
                raise ValueError(_RECONCILIATION_MISMATCH)
            (worktree / "pyproject.toml").write_bytes(updated_project)
            (worktree / "uv.lock").write_bytes(updated_lock)
            for path in _RELEASE_FILES:
                (worktree / path).parent.mkdir(parents=True, exist_ok=True)
                (worktree / path).write_bytes(_git_bytes(root, "show", f"{release_sha}:{path}"))
            changed = _git(worktree, "diff", "--name-only", "-z", main_sha).split("\0")
            allowed = {"pyproject.toml", "uv.lock", *_RELEASE_FILES}
            if not set(changed) - {_EMPTY} <= allowed:
                raise ValueError(_RECONCILIATION_MISMATCH)
            h_repo.index.add(["pyproject.toml", "uv.lock", *_RELEASE_FILES])
            tree_before = normalized_tree_digest(repo, main_sha)
            h_commit = repo.commit(main_sha)
            r_commit = repo.commit(release_sha)
            message = f"chore: reconcile release metadata for {candidate.version} [skip ci]"
            merge_commit = h_repo.index.commit(
                message,
                author=_AUTHOR,
                committer=_AUTHOR,
                parent_commits=[h_commit, r_commit],
            )
            committed_paths = set(
                _git(root, "diff", "--name-only", "-z", main_sha, merge_commit.hexsha).split("\0")
            ) - {_EMPTY}
            if not committed_paths or not committed_paths.issubset(allowed):
                raise ValueError(_RECONCILIATION_MISMATCH)
            if normalized_tree_digest(repo, merge_commit.hexsha) != tree_before:
                raise ValueError(_RECONCILIATION_MISMATCH)
            return merge_commit.hexsha
        finally:
            _run(root, [_GIT, "worktree", "remove", "--force", str(worktree)])


def publish_proved_candidate(
    repository_root: Path,
    candidate: CandidateIdentity,
    proof: ProofIdentity,
    bundle_path: Path,
    receipt_path: Path,
    github_token: str,
    candidate_check_data: bytes,
    runtime_report_data: bytes,
    *,
    commit_notes_path: Path | None = None,
    github_transport: httpx.BaseTransport | None = None,
) -> PublicationReceipt:
    """Reconcile refs atomically and create or recover the release for one proved R."""
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError(_OUTPUT_EXISTS)
    if not github_token:
        raise ValueError(_INPUT_INVALID)
    validate_runtime_acceptance_evidence(candidate, proof, candidate_check_data, runtime_report_data)
    _validate_proof(candidate, proof)
    repo = Repo(repository_root)
    verify_candidate_bundle(repository_root, candidate, bundle_path, github_token)
    body = _release_body(repository_root, candidate, proof, commit_notes_path)
    remote_tag_sha = _remote_ref(repository_root, "refs/tags/" + candidate.version, github_token)
    if remote_tag_sha is not None and remote_tag_sha != candidate.candidate_sha:
        raise ValueError(_TAG_CONFLICT)
    receipt = PublicationReceipt(
        candidate=candidate,
        proof=proof,
        state=PublicationState.PUBLISHING,
        tag=candidate.version,
        github_release_id=None,
    )
    _write_receipt(receipt_path, receipt)
    for _ in range(_RETRY_LIMIT):
        _git(
            repository_root,
            "fetch",
            "--no-tags",
            _ORIGIN,
            _MAIN + ":" + _REMOTE_MAIN,
            github_token=github_token,
        )
        main_sha = repo.commit(_REMOTE_MAIN).hexsha
        main_target = build_reconciliation(repository_root, candidate, main_sha)
        refspecs = [main_target + ":" + _MAIN]
        if remote_tag_sha is None:
            refspecs.append(candidate.candidate_sha + ":refs/tags/" + candidate.version)
        push = subprocess.run(
            [_GIT, "push", "--atomic", _ORIGIN, *refspecs],
            cwd=repository_root,
            capture_output=True,
            check=False,
            text=True,
            env=_git_environment(github_token),
        )
        if push.returncode == 0:
            break
        remote_tag_sha = _remote_ref(repository_root, "refs/tags/" + candidate.version, github_token)
        if remote_tag_sha is not None and remote_tag_sha != candidate.candidate_sha:
            raise ValueError(_TAG_CONFLICT)
        remote_main_sha = _remote_ref(repository_root, _MAIN, github_token)
        if remote_main_sha is not None and remote_main_sha != main_sha:
            continue
        raise RuntimeError(_ATOMIC_PUSH_FAILED)
    else:
        raise RuntimeError(_RETRY_EXHAUSTED)

    remote_tag_sha = _remote_ref(repository_root, "refs/tags/" + candidate.version, github_token)
    if remote_tag_sha != candidate.candidate_sha:
        raise ValueError(_TAG_CONFLICT)
    remote_main_sha = _remote_ref(repository_root, _MAIN, github_token)
    if remote_main_sha is None:
        raise RuntimeError(_ERROR)
    _git(
        repository_root,
        "fetch",
        "--no-tags",
        _ORIGIN,
        _MAIN + ":" + _REMOTE_MAIN,
        github_token=github_token,
    )
    remote_main_sha = repo.commit(_REMOTE_MAIN).hexsha
    repo.git.merge_base("--is-ancestor", candidate.candidate_sha, remote_main_sha)
    with GitHubArtifactClient(github_token, transport=github_transport) as github:
        existing = github.get_release_by_tag(candidate.attempt.repository, candidate.version)
        if existing is not None:
            if (
                existing.tag_name != candidate.version
                or existing.draft
                or existing.prerelease
                or _release_marker(candidate, proof) not in (existing.body or _EMPTY)
            ):
                raise ValueError(_RELEASE_CONFLICT)
            release = existing
        else:
            release = github.create_release(
                candidate.attempt.repository,
                candidate.version,
                candidate.candidate_sha,
                body,
            )
    receipt = receipt.model_copy(update={"state": PublicationState.PUBLISHED, "github_release_id": str(release.id)})
    _write_receipt(receipt_path, receipt)
    if os.environ.get("GITHUB_OUTPUT"):
        append_output("release_url", release.html_url)
        append_output("published_tag", candidate.version)
        append_output("candidate_sha", candidate.candidate_sha)
    print(release.html_url)
    return receipt


def _validate_proof(candidate: CandidateIdentity, proof: ProofIdentity) -> None:
    """Require both final gates to have passed for the exact commit and tree."""
    if (
        _TAG_PATTERN.fullmatch(candidate.version) is None
        or _SHA_PATTERN.fullmatch(candidate.candidate_sha) is None
        or _SHA_PATTERN.fullmatch(candidate.candidate_tree_sha) is None
        or not proof.lint_succeeded
        or not proof.installer_succeeded
        or not proof.runtime_acceptance_succeeded
        or proof.runtime_acceptance_report_sha256 is None
        or _EVIDENCE_PATTERN.fullmatch(proof.runtime_acceptance_report_sha256) is None
        or proof.candidate_sha != candidate.candidate_sha
        or proof.candidate_tree_sha != candidate.candidate_tree_sha
        or proof.evidence_sha256 is None
        or _EVIDENCE_PATTERN.fullmatch(proof.evidence_sha256) is None
    ):
        raise ValueError(_PROOF_REQUIRED)


def _candidate_ref(candidate: CandidateIdentity) -> str:
    """Build a stable private ref name from numeric workflow identifiers."""
    run_id = candidate.attempt.workflow_run_id
    attempt = candidate.attempt.workflow_run_attempt
    if not run_id.isdigit() or attempt < 1:
        raise ValueError(_INPUT_INVALID)
    return _CANDIDATE_REF_PREFIX + run_id + "-" + str(attempt)


def _remote_ref(repository_root: Path, reference: str, github_token: str = _EMPTY) -> str | None:
    """Read exactly one remote ref without relying on local tag or branch state."""
    output = _git(repository_root, "ls-remote", _ORIGIN, reference, github_token=github_token)
    rows = [line.split() for line in output.splitlines() if line.strip()]
    if not rows:
        return None
    if any(len(row) != 2 or row[1] not in {reference, reference + "^{}"} for row in rows):
        raise RuntimeError(_ERROR)
    peeled = [row[0] for row in rows if row[1] == reference + "^{}"]
    matching = [row[0] for row in rows if row[1] == reference]
    if len(peeled) > 1 or len(matching) != 1:
        raise RuntimeError(_ERROR)
    return peeled[0] if peeled else matching[0]


def _local_ref(repository_root: Path, reference: str) -> str:
    """Read one local ref, distinguishing absence from other Git failures."""
    result = subprocess.run(
        [_GIT, "rev-parse", "--verify", "--quiet", reference],
        cwd=repository_root,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    if result.returncode == 1:
        return _EMPTY
    raise RuntimeError(_ERROR)


def _release_body(
    repository_root: Path,
    candidate: CandidateIdentity,
    proof: ProofIdentity,
    commit_notes_path: Path | None,
) -> str:
    """Use the candidate's own notes and attach exact source, run, and proof references."""
    content = _git_bytes(repository_root, "show", f"{candidate.candidate_sha}:{_RELEASE_FILES[0]}").decode(_UTF8)
    lines = content.splitlines()
    headings = [index for index, line in enumerate(lines) if line.startswith("## [")]
    expected = "## [" + candidate.version.removeprefix("v") + "]"
    if not headings:
        raise ValueError(_RELEASE_NOTE_MISSING)
    if not lines[headings[0]].startswith(expected):
        raise ValueError(_RELEASE_NOTE_MISSING)
    end = next((index for index in headings[1:] if index > headings[0]), len(lines))
    section = _NEWLINE.join(lines[headings[0] : end]).rstrip("\n")
    if not section:
        raise ValueError(_RELEASE_NOTE_MISSING)
    if candidate.commit_notes_sha256 is not None:
        if commit_notes_path is None or not commit_notes_path.is_file():
            raise ValueError(_RELEASE_NOTES_MISMATCH)
        notes_data = commit_notes_path.read_bytes()
        if hashlib.sha256(notes_data).hexdigest() != candidate.commit_notes_sha256:
            raise ValueError(_RELEASE_NOTES_MISMATCH)
        try:
            verify_commit_notes(
                repository_root,
                candidate.attempt.source_sha,
                candidate.attempt.baseline_sha,
                commit_notes_path,
                require_head=False,
            )
            notes = notes_data.decode(_UTF8, errors="strict").rstrip("\n")
            provenance_data = _git_bytes(repository_root, "show", f"{candidate.candidate_sha}:{_RELEASE_FILES[-1]}")
            decision = load_release_provenance(provenance_data, candidate.version)
        except (UnicodeDecodeError, ValueError):
            raise ValueError(_RELEASE_NOTES_MISMATCH) from None
        if notes and section.count(notes) != 1:
            raise ValueError(_RELEASE_NOTES_MISMATCH)
        if (
            decision.mode != candidate.attempt.decision_mode
            or decision.source_sha != candidate.attempt.source_sha
            or decision.workflow_run_id != candidate.attempt.workflow_run_id
            or decision.workflow_run_attempt != candidate.attempt.workflow_run_attempt
            or decision.assessment_sha256 != candidate.assessment_sha256
            or decision.legacy_assessment_sha256 != candidate.legacy_assessment_sha256
            or decision.commit_notes_sha256 != candidate.commit_notes_sha256
            or candidate.decision_sha256
            != release_decision_digest(
                candidate.attempt,
                candidate.version,
                candidate.assessment_sha256,
                candidate.legacy_assessment_sha256,
            )
        ):
            raise ValueError(_RELEASE_NOTES_MISMATCH)
    attempt = candidate.attempt
    run_url = (
        "https://github.com/"
        + attempt.repository
        + "/actions/runs/"
        + attempt.workflow_run_id
        + "/attempts/"
        + str(attempt.workflow_run_attempt)
    )
    provenance = (
        "\n\n## Provenance\n\n"
        + "- Source: `"
        + attempt.source_sha
        + "`\n"
        + "- Baseline: `"
        + (attempt.baseline_tag or attempt.legacy_baseline_marker or _NO_BASELINE_LABEL)
        + "`\n"
        + "- Candidate: `"
        + candidate.candidate_sha
        + "`\n"
        + "- Proof evidence SHA-256: `"
        + str(proof.evidence_sha256)
        + "`\n"
        + "- Workflow attempt: ["
        + attempt.workflow_run_id
        + "]("
        + run_url
        + ")\n\n"
        + _release_marker(candidate, proof)
    )
    return compose_release_body(
        section,
        provenance,
        candidate.version,
        RELEASE_BODY_LIMIT,
        release_body_length,
    )


def _release_marker(candidate: CandidateIdentity, proof: ProofIdentity) -> str:
    """Create an exact machine identity for idempotent GitHub Release recovery."""
    marker = (
        _RELEASE_MARKER
        + " candidate="
        + candidate.candidate_sha
        + " candidate_tree="
        + candidate.candidate_tree_sha
        + " source="
        + candidate.attempt.source_sha
        + " baseline="
        + (candidate.attempt.baseline_tag or candidate.attempt.legacy_baseline_marker or _NO_BASELINE_LABEL)
        + " run="
        + candidate.attempt.workflow_run_id
        + " attempt="
        + str(candidate.attempt.workflow_run_attempt)
        + " proof="
        + str(proof.evidence_sha256)
    )
    if candidate.commit_notes_sha256 is not None:
        marker += " notes=" + candidate.commit_notes_sha256
    return marker + " -->"


def _write_receipt(path: Path, receipt: PublicationReceipt) -> None:
    """Create or atomically replace a local recoverable publication record."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(receipt.model_dump_json(indent=_JSON_INDENT) + _NEWLINE, encoding=_UTF8)
    temporary.replace(path)


def _write_temp_payload(parent: Path, name: str, content: bytes) -> Path:
    """Write one isolated validation payload in the reconciliation scratch root."""
    path = parent / name
    path.write_bytes(content)
    return path


def _run(root: Path, arguments: Sequence[str], *, github_token: str = _EMPTY) -> str:
    """Run one fixed Git operation and suppress credential-bearing transport diagnostics."""
    try:
        result = subprocess.run(
            arguments,
            cwd=root,
            capture_output=True,
            check=True,
            text=True,
            env=_git_environment(github_token),
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            _COMMAND_FAILED.format(command=Path(arguments[0]).name, return_code=error.returncode)
        ) from None
    except OSError:
        raise RuntimeError(_COMMAND_FAILED.format(command=Path(arguments[0]).name, return_code="unavailable")) from None
    return result.stdout.strip()


def _git(root: Path, *arguments: str, github_token: str = _EMPTY) -> str:
    """Run a read-only Git query without a shell."""
    return _run(root, [_GIT, *arguments], github_token=github_token)


def _git_environment(github_token: str) -> dict[str, str]:
    """Supply GitHub transport credentials through child-only config, never argv or disk."""
    environment = os.environ.copy()
    environment[_GIT_PROMPT] = "0"
    if github_token:
        credential = base64.b64encode((_GITHUB_TOKEN_CREDENTIAL + github_token).encode(_UTF8)).decode("ascii")
        environment[_GIT_CONFIG_COUNT] = "1"
        environment[_GIT_CONFIG_KEY] = _GITHUB_HTTP_CONFIG
        environment[_GIT_CONFIG_VALUE] = _BASIC_SCHEME + credential
    return environment


def _git_bytes(root: Path, *arguments: str) -> bytes:
    """Read a committed file without materializing another working-tree path."""
    try:
        result = subprocess.run([_GIT, *arguments], cwd=root, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError(_ERROR) from None
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    """Publish verified candidate artifacts supplied by the proof stage."""
    parser = argparse.ArgumentParser(description="Publish the exact proved candidate.")
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--candidate-check", type=Path, required=True)
    parser.add_argument("--runtime-report", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--commit-notes", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        candidate = load_candidate_identity(args.candidate.read_bytes())
        proof = load_proof_identity(args.proof.read_bytes())
        token = os.environ.get(_TOKEN_VARIABLE, _EMPTY)
        repository = os.environ.get(_REPOSITORY_VARIABLE, _EMPTY)
        if not token or repository != candidate.attempt.repository:
            raise ValueError(_INPUT_INVALID)
        publish_proved_candidate(
            repo_root(),
            candidate,
            proof,
            args.bundle,
            args.receipt,
            token,
            args.candidate_check.read_bytes(),
            args.runtime_report.read_bytes(),
            commit_notes_path=args.commit_notes,
        )
    except (OSError, ValidationError, ValueError, RuntimeError, GitHubArtifactError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

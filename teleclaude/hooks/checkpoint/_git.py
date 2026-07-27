"""Git diff analysis, file categorization, and shell parsing utilities."""

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.checkpoint_model import triggered_action_ids
from teleclaude.constants import CheckpointModel
from teleclaude.git import GitCommandError, Repo
from teleclaude.hooks.checkpoint._models import TranscriptObservability
from teleclaude.shell_path_parser import command_likely_mutates_files as _shared_command_likely_mutates_files
from teleclaude.shell_path_parser import extract_shell_command as _shared_extract_shell_command
from teleclaude.shell_path_parser import extract_shell_touched_paths as _shared_extract_shell_touched_paths
from teleclaude.shell_path_parser import looks_like_path_token as _shared_looks_like_path_token
from teleclaude.shell_path_parser import segment_tokens as _shared_segment_tokens
from teleclaude.shell_path_parser import split_shell_segments as _shared_split_shell_segments
from teleclaude.utils.transcript import TurnTimeline

logger = get_logger(__name__)

# Prose source files carry no maintenance action of their own; used only to detect
# "no code changes this turn" framing, independent of the action model.
_DOC_FILE_SUFFIXES = (".md", ".txt", ".rst")


class WorktreeStatus(StrEnum):
    """Certainty states for the checkpoint's working-tree observation."""

    CLEAN = "clean"
    DIRTY = "dirty"
    UNREADABLE = "unreadable"


__all__ = [
    "WorktreeStatus",
    "_canonical_tool_name",
    "_command_likely_mutates_files",
    "_current_branch",
    "_extract_apply_patch_paths",
    "_extract_shell_command",
    "_extract_shell_touched_paths",
    "_extract_turn_file_signals",
    "_get_uncommitted_files",
    "_git_diff_names",
    "_is_checkpoint_project_supported",
    "_is_docs_only",
    "_is_no_action_only",
    "_looks_like_path_token",
    "_normalize_repo_path",
    "_scope_git_files_to_current_turn",
    "_segment_tokens",
    "_split_shell_segments",
    "_transcript_observability",
    "_worktree_status",
]


def _canonical_tool_name(tool_name: str) -> str:
    """Normalize tool names across transcript adapters."""
    normalized = (tool_name or "").strip().lower()
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return normalized


def _is_checkpoint_project_supported(project_path: str) -> bool:
    """Return True for any onboarded project — one carrying a ``teleclaude.yml``.

    The checkpoint engine runs in every telec-onboarded repository, nudging the
    platform-universal base merged with the project's declared overlay. Onboarding
    is keyed on the project carrying a resolvable ``ProjectConfig`` (its
    ``teleclaude.yml``), not on TeleClaude package markers.
    """
    if not project_path:
        return False
    try:
        root = Path(project_path).expanduser().resolve()
    except Exception:
        return False
    return (root / "teleclaude.yml").exists()


def _get_uncommitted_files(project_path: str) -> list[str] | None:
    """Run git diff --name-only HEAD to get uncommitted changed files.

    Returns None if git is unavailable or the command fails (fail-open).
    """

    def _run_git_diff_name_only(repo: Repo) -> str:
        return repo.git.diff("--name-only", "HEAD")

    def _normalize_non_bare_repo(repo: Repo) -> bool:
        try:
            is_bare = repo.git.rev_parse("--is-bare-repository").strip().lower()
        except GitCommandError:
            return False
        if is_bare != "true":
            return True

        try:
            repo.git.config("--local", "core.bare", "false")
        except GitCommandError:
            logger.warning(
                "Checkpoint git self-heal failed: unable to set core.bare=false for %s",
                project_path,
            )
            return False
        logger.warning(
            "Checkpoint git self-heal applied: normalized core.bare=false for %s",
            project_path,
        )
        return True

    try:
        repo = Repo(project_path or ".", search_parent_directories=True)
        _normalize_non_bare_repo(repo)
        try:
            output = _run_git_diff_name_only(repo)
        except GitCommandError as exc:
            if "must be run in a work tree" in (exc.stderr or "").lower():
                if _normalize_non_bare_repo(repo):
                    output = _run_git_diff_name_only(repo)
                else:
                    return None
            else:
                return None
        files = [f.strip() for f in output.strip().splitlines() if f.strip()]
        return files
    except Exception:
        return None


def _worktree_status(project_path: str) -> WorktreeStatus:
    """Return the full porcelain status, preserving unreadable-state uncertainty."""
    try:
        repo = Repo(project_path or ".", search_parent_directories=True)
        status = repo.git.status("--porcelain", "--untracked-files=all")
    except Exception:
        return WorktreeStatus.UNREADABLE
    return WorktreeStatus.CLEAN if not status.strip() else WorktreeStatus.DIRTY


def _current_branch(project_path: str) -> str | None:
    """Return the current branch name, or None if git is unavailable.

    Returns None on any failure (fail-open — the caller decides how to treat
    uncertain branch state).
    """
    try:
        repo = Repo(project_path or ".", search_parent_directories=True)
        branch = repo.git.rev_parse("--abbrev-ref", "HEAD").strip()
        return branch or None
    except (GitCommandError, OSError, ValueError):
        return None


def _transcript_observability(transcript_path: str | None) -> TranscriptObservability:
    """Return lightweight transcript-path observability fields for logging."""
    if not transcript_path:
        return {
            "transcript_path": "",
            "transcript_exists": False,
            "transcript_size_bytes": 0,
        }
    try:
        path = Path(transcript_path).expanduser()
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        return {
            "transcript_path": str(path),
            "transcript_exists": exists,
            "transcript_size_bytes": size,
        }
    except Exception:
        return {
            "transcript_path": transcript_path,
            "transcript_exists": False,
            "transcript_size_bytes": 0,
        }


def _normalize_repo_path(path: str, project_path: str) -> str:
    """Normalize absolute/relative paths to project-relative POSIX form."""
    raw = (path or "").strip()
    if not raw:
        return ""
    try:
        candidate = Path(raw)
        if candidate.is_absolute() and project_path:
            try:
                candidate = candidate.relative_to(Path(project_path))
            except ValueError:
                return ""
        return candidate.as_posix().lstrip("./")
    except Exception:
        return ""


def _command_likely_mutates_files(command: str) -> bool:
    """Best-effort shell command classifier for file-mutating intent."""
    return _shared_command_likely_mutates_files(command)


def _extract_shell_command(input_data: Mapping[str, object]) -> str:
    """Extract command text from tool input payloads across adapters."""
    return _shared_extract_shell_command(input_data)


def _looks_like_path_token(token: str) -> bool:
    """Heuristic for shell tokens that are likely file paths."""
    return _shared_looks_like_path_token(token)


def _split_shell_segments(command: str) -> list[str]:
    """Split a shell command into sequential segments (`&&`, `||`, `;`, newline)."""
    return _shared_split_shell_segments(command)


def _segment_tokens(segment: str) -> list[str]:
    """Best-effort tokenization for a command segment."""
    return _shared_segment_tokens(segment)


def _extract_shell_touched_paths(command: str, project_path: str) -> set[str]:
    """Best-effort extraction of mutated file paths from shell commands."""
    return _shared_extract_shell_touched_paths(command, lambda path: _normalize_repo_path(path, project_path))


def _extract_apply_patch_paths(patch_text: str, project_path: str) -> set[str]:
    """Extract file paths from apply_patch payload text."""
    paths: set[str] = set()
    if not patch_text:
        return paths
    prefixes = (
        "*** Update File:",
        "*** Add File:",
        "*** Delete File:",
        "*** Move to:",
    )
    for line in patch_text.splitlines():
        stripped = line.strip()
        for prefix in prefixes:
            if not stripped.startswith(prefix):
                continue
            raw_path = stripped[len(prefix) :].strip()
            normalized = _normalize_repo_path(raw_path, project_path)
            if normalized:
                paths.add(normalized)
    return paths


def _extract_turn_file_signals(timeline: TurnTimeline, project_path: str) -> tuple[set[str], bool]:
    """Extract turn-local file touches and mutation intent."""
    touched_files: set[str] = set()
    saw_mutation_signal = False

    if not timeline.has_data:
        return touched_files, saw_mutation_signal

    for record in timeline.tool_calls:
        tool_name = _canonical_tool_name(record.tool_name)

        # Structured file mutators (explicit file_path semantics).
        if tool_name in {"edit", "write", "multiedit", "apply_patch", "notebookedit"}:
            saw_mutation_signal = True
            for key in ("file_path", "path", "filepath", "target_file"):
                value = record.input_data.get(key)
                if isinstance(value, str):
                    normalized = _normalize_repo_path(value, project_path)
                    if normalized:
                        touched_files.add(normalized)
            for key in ("file_paths", "paths"):
                value = record.input_data.get(key)
                if isinstance(value, list):
                    for entry in value:
                        if isinstance(entry, str):
                            normalized = _normalize_repo_path(entry, project_path)
                            if normalized:
                                touched_files.add(normalized)
            if tool_name == "apply_patch":
                for key in ("input", "patch", "raw_arguments", "command", "cmd"):
                    value = record.input_data.get(key)
                    if isinstance(value, str):
                        touched_files.update(_extract_apply_patch_paths(value, project_path))
            continue

        # Shell tools can mutate files but usually expose only freeform command text.
        if tool_name in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            command = _extract_shell_command(record.input_data)
            if _command_likely_mutates_files(command):
                saw_mutation_signal = True
                shell_touched = _extract_shell_touched_paths(command, project_path)
                if shell_touched:
                    touched_files.update(shell_touched)

    return touched_files, saw_mutation_signal


def _scope_git_files_to_current_turn(
    git_files: list[str],
    timeline: TurnTimeline,
    project_path: str,
) -> list[str]:
    """Reduce repo-wide dirty files to likely current-turn changes.

    Rationale:
    - `git diff --name-only HEAD` returns repo-wide dirty state.
    - Checkpoint obligations are turn-local.
    - Without scoping, stale files from previous turns trigger false positives.
    """
    if not git_files:
        return []
    if not timeline.has_data:
        # Fail-closed: if turn extraction failed, avoid attributing repo-wide dirty state
        # to the current stop event.
        return []

    touched_files, saw_mutation_signal = _extract_turn_file_signals(timeline, project_path)
    if touched_files:
        normalized_git: dict[str, str] = {}
        for filepath in git_files:
            normalized = _normalize_repo_path(filepath, project_path)
            if normalized:
                normalized_git[normalized] = filepath

        scoped = [normalized_git[path] for path in sorted(touched_files) if path in normalized_git]
        if scoped:
            return scoped

        # Explicit mutators seen but path mapping failed: prefer fail-closed to
        # avoid attributing repo-wide stale dirty files to this turn.
        if saw_mutation_signal:
            return []
        return []

    # No mutation signals in this turn: avoid stale dirty-file false positives.
    if not saw_mutation_signal:
        return []

    # Mutation by shell command detected, but no reliable file-path mapping.
    # Prefer fail-closed to avoid broad false positives.
    return []


# ---------------------------------------------------------------------------
# Action resolution
# ---------------------------------------------------------------------------


def _git_diff_names(project_path: str, range_expr: str) -> list[str]:
    """Return file paths changed in the given git range.

    Raises on failure so callers do not mistake an unreadable merge delta for
    "no changed files" and suppress required maintenance.
    """
    try:
        repo = Repo(project_path, search_parent_directories=True)
        output = repo.git.diff("--name-only", range_expr)
        return [line for line in output.splitlines() if line]
    except GitCommandError as exc:
        logger.warning(
            "git diff --name-only failed for maintenance range %r: %s",
            range_expr,
            exc.stderr or str(exc),
        )
        raise
    except Exception as exc:
        logger.warning(
            "Unexpected error computing maintenance delta for range %r: %s",
            range_expr,
            exc,
        )
        raise


def _is_docs_only(git_files: list[str]) -> bool:
    """Check if every changed file is a prose source file (.md/.txt/.rst)."""
    for filepath in git_files:
        if not filepath.endswith(_DOC_FILE_SUFFIXES):
            return False
    return True


def _is_no_action_only(git_files: list[str], model: CheckpointModel) -> bool:
    """Return True when no changed file owes any action under the merged model."""
    return not triggered_action_ids(git_files, model)

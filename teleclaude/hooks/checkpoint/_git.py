"""Git diff analysis, file categorization, and shell parsing utilities."""

import logging
import re
import shlex
import subprocess
from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path

from teleclaude.constants import (
    CHECKPOINT_FILE_CATEGORIES,
    CHECKPOINT_NO_ACTION_PATTERNS,
    FileCategory,
)
from teleclaude.hooks.checkpoint._models import TranscriptObservability
from teleclaude.utils.transcript import TurnTimeline

logger = logging.getLogger(__name__)


def _canonical_tool_name(tool_name: str) -> str:
    """Normalize tool names across transcript adapters."""
    normalized = (tool_name or "").strip().lower()
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1]
    return normalized


def _is_checkpoint_project_supported(project_path: str) -> bool:
    """Return True only for projects that carry TeleClaude checkpoint semantics."""
    if not project_path:
        return False
    try:
        root = Path(project_path).expanduser().resolve()
    except Exception:
        return False

    # Require clear TeleClaude markers so other repositories are excluded.
    # checkpoint module may be a flat file or a package.
    checkpoint_flat = root / "teleclaude" / "hooks" / "checkpoint.py"
    checkpoint_pkg = root / "teleclaude" / "hooks" / "checkpoint" / "__init__.py"
    has_checkpoint = checkpoint_flat.exists() or checkpoint_pkg.exists()
    has_next_work = (root / "agents" / "commands" / "next-work.md").exists()
    return has_checkpoint and has_next_work


def _get_uncommitted_files(project_path: str) -> list[str] | None:
    """Run git diff --name-only HEAD to get uncommitted changed files.

    Returns None if git is unavailable or the command fails (fail-open).
    """

    def _run_git_diff_name_only() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )

    def _normalize_non_bare_repo() -> bool:
        bare_probe = subprocess.run(
            ["git", "rev-parse", "--is-bare-repository"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )
        if bare_probe.returncode != 0:
            return False
        if bare_probe.stdout.strip().lower() != "true":
            return True

        normalize = subprocess.run(
            ["git", "config", "--local", "core.bare", "false"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )
        if normalize.returncode != 0:
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
        _normalize_non_bare_repo()
        result = _run_git_diff_name_only()
        if result.returncode != 0 and "must be run in a work tree" in (result.stderr or "").lower():
            if _normalize_non_bare_repo():
                result = _run_git_diff_name_only()
        if result.returncode != 0:
            return None
        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        return files
    except Exception:
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
    if not command:
        return False
    cmd = command.strip()
    if not cmd:
        return False

    patterns = (
        r"\bapply_patch\b",
        r"\bgit\s+(add|mv|rm|restore|checkout|apply)\b",
        r"\bsed\s+-i\b",
        r"\bperl\s+-pi\b",
        r"\btouch\b",
        r"\bmkdir\b",
        r"\bmv\b",
        r"\bcp\b",
        r"\brm\b",
        r"\btee\b",
    )
    if any(re.search(pattern, cmd) for pattern in patterns):
        return True

    # Redirection is a loose mutation signal; used only as fallback.
    if ">>" in cmd or " > " in cmd:
        return True
    return False


def _extract_shell_command(input_data: Mapping[str, object]) -> str:
    """Extract command text from tool input payloads across adapters."""
    command = input_data.get("command")
    if not isinstance(command, str) or not command.strip():
        command = input_data.get("cmd")
    if isinstance(command, str):
        return command.strip()
    return ""


def _looks_like_path_token(token: str) -> bool:
    """Heuristic for shell tokens that are likely file paths."""
    if not token:
        return False
    if token.startswith(("-", "$")):
        return False
    if token in {"|", ">", ">>", "2>", "1>", "&&", "||", ";"}:
        return False
    if token.startswith("s/") and token.count("/") >= 2:
        # Common sed replacement expression; not a file path.
        return False
    if token.startswith("{") or token.startswith("["):
        return False

    if token.startswith(("./", "../", "/")):
        return True
    if "/" in token:
        return True

    suffixes = (
        ".py",
        ".md",
        ".txt",
        ".rst",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".sh",
        ".sql",
        ".ini",
        ".cfg",
        ".lock",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".css",
    )
    return token.endswith(suffixes)


def _split_shell_segments(command: str) -> list[str]:
    """Split a shell command into sequential segments (`&&`, `||`, `;`, newline)."""
    if not command:
        return []
    parts = re.split(r"(?:&&|\|\||;|\n)", command)
    return [part.strip() for part in parts if part.strip()]


def _segment_tokens(segment: str) -> list[str]:
    """Best-effort tokenization for a command segment."""
    if not segment:
        return []
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _extract_shell_touched_paths(command: str, project_path: str) -> set[str]:
    """Best-effort extraction of mutated file paths from shell commands."""
    touched: set[str] = set()
    if not command:
        return touched

    for segment in _split_shell_segments(command):
        for token in _segment_tokens(segment):
            clean = token.strip().strip("\"'`").strip(",;:")
            if not _looks_like_path_token(clean):
                continue
            if ":" in clean and not clean.startswith(("./", "../", "/")):
                # Likely git rev/path syntax or host:port-like token.
                continue
            normalized = _normalize_repo_path(clean, project_path)
            if normalized:
                touched.add(normalized)
    return touched


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
            shell_touched = _extract_shell_touched_paths(command, project_path)
            if shell_touched:
                touched_files.update(shell_touched)
            if _command_likely_mutates_files(command):
                saw_mutation_signal = True

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
# File categorization (R2)
# ---------------------------------------------------------------------------


def _categorize_files(git_files: list[str]) -> list[FileCategory]:
    """Map changed files to matching file categories."""
    matched: list[FileCategory] = []
    seen_names: set[str] = set()
    tests_only_category = next((c for c in CHECKPOINT_FILE_CATEGORIES if c.name == "tests only"), None)
    meaningful_files = [filepath for filepath in git_files if not _is_docs_only([filepath])]
    tests_only_diff = bool(meaningful_files) and (
        tests_only_category is not None
        and all(_file_matches_category(filepath, tests_only_category) for filepath in meaningful_files)
    )

    for category in CHECKPOINT_FILE_CATEGORIES:
        if category.name == "tests only" and not tests_only_diff:
            continue
        for filepath in git_files:
            if _file_matches_category(filepath, category):
                if category.name not in seen_names:
                    matched.append(category)
                    seen_names.add(category.name)
                break

    return matched


def _file_matches_category(filepath: str, category: FileCategory) -> bool:
    """Check if a file path matches a category's include/exclude patterns."""
    included = any(fnmatch(filepath, pat) for pat in category.include_patterns)
    if not included:
        return False
    excluded = any(fnmatch(filepath, pat) for pat in category.exclude_patterns)
    return not excluded


def _is_docs_only(git_files: list[str]) -> bool:
    """Check if all changed files are non-code (docs, todos, markdown)."""
    for filepath in git_files:
        if not any(fnmatch(filepath, pat) for pat in CHECKPOINT_NO_ACTION_PATTERNS):
            return False
    return True

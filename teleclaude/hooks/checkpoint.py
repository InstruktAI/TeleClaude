"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses git diff for file-based signals and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

import logging
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Mapping, Optional, TypedDict

from teleclaude.constants import (
    CHECKPOINT_BLAST_RADIUS_THRESHOLD,
    CHECKPOINT_ERROR_ENRICHMENT,
    CHECKPOINT_FILE_CATEGORIES,
    CHECKPOINT_GENERIC_ERROR_MESSAGE,
    CHECKPOINT_LOG_CHECK_EVIDENCE,
    CHECKPOINT_MESSAGE,
    CHECKPOINT_NO_ACTION_PATTERNS,
    CHECKPOINT_PREFIX,
    CHECKPOINT_STATUS_EVIDENCE,
    CHECKPOINT_TEST_ERROR_COMMANDS,
    CHECKPOINT_TEST_ERROR_MESSAGE,
    CHECKPOINT_TEST_EVIDENCE,
    FileCategory,
)
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline, extract_tool_calls_current_turn

logger = logging.getLogger(__name__)


class TranscriptObservability(TypedDict):
    transcript_path: str
    transcript_exists: bool
    transcript_size_bytes: int


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
    required_markers = (
        root / "teleclaude" / "hooks" / "checkpoint.py",
        root / "agents" / "commands" / "next-work.md",
    )
    return all(marker.exists() for marker in required_markers)


@dataclass
class CheckpointContext:
    """Session context for checkpoint heuristics."""

    project_path: str = ""
    working_slug: Optional[str] = None
    agent_name: AgentName = AgentName.CLAUDE


@dataclass
class CheckpointResult:
    """Output of the heuristic engine."""

    categories: list[str] = field(default_factory=list)
    required_actions: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    is_all_clear: bool = False


# ---------------------------------------------------------------------------
# Git diff
# ---------------------------------------------------------------------------


def _get_uncommitted_files(project_path: str) -> Optional[list[str]]:
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


def _transcript_observability(transcript_path: Optional[str]) -> TranscriptObservability:
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
        if tool_name in {"edit", "write", "multiedit", "apply_patch"}:
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


# ---------------------------------------------------------------------------
# Evidence checking (R4)
# ---------------------------------------------------------------------------


def _has_evidence(timeline: TurnTimeline, substrings: list[str]) -> bool:
    """Check if any Bash tool call command contains any of the evidence substrings."""
    if not timeline.has_data or not substrings:
        return False
    for record in timeline.tool_calls:
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            continue
        if record.had_error:
            continue
        command = _extract_shell_command(record.input_data)
        if _command_has_evidence(command, substrings):
            return True
    return False


def _iter_shell_command_records(timeline: TurnTimeline) -> list[tuple[int, ToolCallRecord, str]]:
    """Return successful shell-like tool calls with extracted command text."""
    records: list[tuple[int, ToolCallRecord, str]] = []
    if not timeline.has_data:
        return records
    for idx, record in enumerate(timeline.tool_calls):
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            continue
        if record.had_error:
            continue
        command = _extract_shell_command(record.input_data)
        records.append((idx, record, command))
    return records


def _has_evidence_after_index(timeline: TurnTimeline, substrings: list[str], after_index: int) -> bool:
    """Check if evidence appears after a specific tool-call index in the timeline."""
    if not substrings:
        return False
    for idx, _record, command in _iter_shell_command_records(timeline):
        if idx <= after_index:
            continue
        if _command_has_evidence(command, substrings):
            return True
    return False


def _last_category_mutation_index(
    timeline: TurnTimeline,
    category: FileCategory,
    project_path: str,
) -> int | None:
    """Return the last timeline index that mutated a file in the given category."""
    if not timeline.has_data:
        return None

    last_index: int | None = None
    for idx, record in enumerate(timeline.tool_calls):
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"edit", "write", "multiedit", "apply_patch"}:
            continue

        touched: set[str] = set()
        for key in ("file_path", "path", "filepath", "target_file"):
            value = record.input_data.get(key)
            if isinstance(value, str):
                normalized = _normalize_repo_path(value, project_path)
                if normalized:
                    touched.add(normalized)
        for key in ("file_paths", "paths"):
            value = record.input_data.get(key)
            if isinstance(value, list):
                for entry in value:
                    if isinstance(entry, str):
                        normalized = _normalize_repo_path(entry, project_path)
                        if normalized:
                            touched.add(normalized)
        if tool_name == "apply_patch":
            for key in ("input", "patch", "raw_arguments", "command", "cmd"):
                value = record.input_data.get(key)
                if isinstance(value, str):
                    touched.update(_extract_apply_patch_paths(value, project_path))

        if any(_file_matches_category(path, category) for path in touched):
            last_index = idx

    return last_index


def _has_status_evidence(timeline: TurnTimeline) -> bool:
    """Check if make status was run after a restart."""
    if not timeline.has_data:
        return False
    saw_restart = False
    for record in timeline.tool_calls:
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            continue
        command = _extract_shell_command(record.input_data)
        if record.had_error:
            continue
        for segment in _split_shell_segments(command):
            if _segment_matches_evidence(segment, "make restart"):
                saw_restart = True
                continue
            if saw_restart and any(_segment_matches_evidence(segment, sub) for sub in CHECKPOINT_STATUS_EVIDENCE):
                return True
    return False


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


def _segment_matches_evidence(segment: str, evidence: str) -> bool:
    """Match evidence against executable intent, not raw substring mentions."""
    tokens = _segment_tokens(segment)
    if not tokens:
        return False

    head = tokens[0]
    rest = tokens[1:]

    if evidence == "make restart":
        return head == "make" and "restart" in rest
    if evidence == "make status":
        return head == "make" and "status" in rest
    if evidence == "make test":
        return head == "make" and "test" in rest
    if evidence == "uv sync":
        return head == "uv" and "sync" in rest
    if evidence == "telec init":
        return head == "telec" and "init" in rest
    if evidence == "pytest":
        return (
            head == "pytest"
            or (head == "uv" and "pytest" in rest)
            or (head in {"python", "python3"} and len(rest) >= 2 and rest[0] == "-m" and rest[1] == "pytest")
        )
    if evidence == "instrukt-ai-logs":
        return head == "instrukt-ai-logs"
    if evidence == "pkill -SIGUSR2":
        return head == "pkill" and any("SIGUSR2" in token for token in rest)
    if evidence == "kill -USR2":
        return head in {"kill", "pkill"} and any("USR2" in token for token in rest)
    if evidence == "--unix-socket /tmp/teleclaude-api.sock":
        return "--unix-socket" in tokens and "/tmp/teleclaude-api.sock" in tokens
    if evidence == "/agent-restart":
        return any("/agent-restart" in token for token in tokens)
    if evidence == "agent_restart":
        return "agent_restart" in segment

    return evidence in segment


def _command_has_evidence(command: str, evidence_markers: list[str]) -> bool:
    """Check evidence against executable command segments."""
    for segment in _split_shell_segments(command):
        if any(_segment_matches_evidence(segment, marker) for marker in evidence_markers):
            return True
    return False


def _command_invokes_search(command: str) -> bool:
    """Return True when a shell command executes rg/grep (directly or via wrappers)."""
    for segment in _split_shell_segments(command):
        tokens = _segment_tokens(segment.lower())
        if not tokens:
            continue
        head = tokens[0]
        rest = tokens[1:]
        if head in {"rg", "grep"}:
            return True
        if head == "uv" and len(rest) >= 2 and rest[0] == "run" and rest[1] in {"rg", "grep"}:
            return True
        if head in {"python", "python3"} and len(rest) >= 3 and rest[0] == "-m" and rest[1] in {"rg", "grep"}:
            return True
    return False


def _command_references_file(command: str, file_path: str) -> bool:
    """Return True when command segments include the file path as an argument token."""
    normalized = file_path.strip().replace("\\", "/")
    if not normalized:
        return False

    for segment in _split_shell_segments(command):
        for token in _segment_tokens(segment):
            clean = token.strip().strip("\"'`").strip(",;:")
            if not clean:
                continue
            clean = clean.replace("\\", "/")
            if clean == normalized or clean.endswith(f"/{normalized}"):
                return True
    return False


# ---------------------------------------------------------------------------
# Error state detection (R5)
# ---------------------------------------------------------------------------


def _check_error_state(timeline: TurnTimeline) -> list[str]:
    """Two-layer error detection: structural gate then content enrichment."""
    observations: list[str] = []
    if not timeline.has_data:
        return observations

    for error_pos, error_record in enumerate(timeline.tool_calls):
        if not error_record.had_error:
            continue
        if _is_non_actionable_error(error_record):
            continue
        # Layer 1: check for resolution evidence after this error
        subsequent = timeline.tool_calls[error_pos + 1 :]

        if _is_error_resolved(error_record, subsequent):
            continue

        # Layer 2: enrich unresolved errors with specific feedback
        observations.append(_enrich_error(error_record))

    return observations


def _is_non_actionable_error(record: ToolCallRecord) -> bool:
    """Ignore expected non-zero exits for search commands with no matches."""
    command = _extract_shell_command(record.input_data).strip().lower()
    snippet = (record.result_snippet or "").lower()
    if _command_invokes_search(command):
        if "process exited with code 1" in snippet:
            # `rg`/`grep` use exit code 1 for "no matches"; this is informational.
            if "no such file or directory" not in snippet and "permission denied" not in snippet:
                return True
    return False


def _is_error_resolved(error_record: ToolCallRecord, subsequent: list[ToolCallRecord]) -> bool:
    """Check if a subsequent action addressed the error."""
    error_command = _extract_shell_command(error_record.input_data)
    error_file = str(error_record.input_data.get("file_path", ""))

    for later in subsequent:
        # Re-invocation of the same command
        later_tool_name = _canonical_tool_name(later.tool_name)
        if later_tool_name in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            later_command = _extract_shell_command(later.input_data)
            # Same command re-run (e.g., second pytest after first failed)
            if error_command and _commands_overlap(error_command, later_command):
                return True
            # Bash command referencing same file area
            if error_file and _command_references_file(later_command, error_file):
                return True

        # Edit/Write targeting same file path
        if _canonical_tool_name(later.tool_name) in {"edit", "write"}:
            later_file = str(later.input_data.get("file_path", ""))
            if error_file and later_file == error_file:
                return True
            # Also check if Edit targets a file mentioned in the error command
            if error_command and later_file and _command_references_file(error_command, later_file):
                return True

    return False


def _commands_overlap(cmd_a: str, cmd_b: str) -> bool:
    """Check if two commands are the same operation with argument-level fidelity.

    We intentionally require near-exact overlap to avoid suppressing unresolved
    errors when a different command happens to share the same executable name
    (e.g. `pytest tests/a.py` vs `pytest tests/b.py`).
    """

    def _normalize(cmd: str) -> str:
        stripped = cmd.strip()
        if not stripped:
            return ""
        try:
            # Preserve argument identity while normalizing whitespace/quoting.
            return " ".join(shlex.split(stripped))
        except ValueError:
            # Fall back safely when shell parsing fails.
            return " ".join(stripped.split())

    norm_a = _normalize(cmd_a)
    norm_b = _normalize(cmd_b)
    return bool(norm_a) and norm_a == norm_b


def _enrich_error(record: ToolCallRecord) -> str:
    """Produce targeted feedback for an unresolved error (Layer 2)."""
    snippet = record.result_snippet

    # Check known patterns
    for pattern, message in CHECKPOINT_ERROR_ENRICHMENT:
        if pattern in snippet:
            return message

    # Check if it was a test command
    command = _extract_shell_command(record.input_data)
    if _command_has_evidence(command, CHECKPOINT_TEST_ERROR_COMMANDS):
        return CHECKPOINT_TEST_ERROR_MESSAGE

    return CHECKPOINT_GENERIC_ERROR_MESSAGE


# ---------------------------------------------------------------------------
# Edit hygiene (R6)
# ---------------------------------------------------------------------------


def _check_edit_hygiene(timeline: TurnTimeline, git_files: list[str]) -> list[str]:
    """Check for editing practices that indicate potential issues."""
    observations: list[str] = []

    # Edit without read: file_path in Edit but not in any preceding Read
    if timeline.has_data:
        read_files: set[str] = set()
        for record in timeline.tool_calls:
            tool_name = _canonical_tool_name(record.tool_name)
            if tool_name == "read":
                path = str(record.input_data.get("file_path", ""))
                if path:
                    read_files.add(path)
            elif tool_name == "edit":
                path = str(record.input_data.get("file_path", ""))
                if path and path not in read_files:
                    observations.append(
                        "Files were edited without being read first this turn — verify changes are correct"
                    )
                    break  # One observation is enough

    # Wide blast radius: changes span many top-level directories (git-only, no transcript needed)
    if git_files:
        top_dirs = {f.split("/")[0] for f in git_files if "/" in f}
        if len(top_dirs) > CHECKPOINT_BLAST_RADIUS_THRESHOLD:
            observations.append("Changes span multiple subsystems — consider committing completed work incrementally")

    return observations


# ---------------------------------------------------------------------------
# Working slug alignment (R7)
# ---------------------------------------------------------------------------


def _check_slug_alignment(
    git_files: list[str],
    context: CheckpointContext,
) -> list[str]:
    """Check if changes align with the active working slug's implementation plan."""
    observations: list[str] = []
    if not context.working_slug:
        return observations

    plan_path = Path(context.project_path) / "todos" / context.working_slug / "implementation-plan.md"
    if not plan_path.exists():
        return observations

    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError:
        return observations

    # Extract file paths from "Files to Change" table
    expected_files = _extract_plan_file_paths(plan_text)
    if not expected_files:
        return observations

    # Check for overlap
    overlap = set(git_files) & expected_files
    if not overlap:
        observations.append(
            f"Active work item `{context.working_slug}` expects changes in different files"
            " — verify you are working on the right task"
        )

    return observations


def _extract_plan_file_paths(plan_text: str) -> set[str]:
    """Extract file paths from implementation plan's Files to Change table."""
    paths: set[str] = set()
    in_table = False
    for line in plan_text.splitlines():
        if "Files to Change" in line or "File" in line and "Change" in line:
            in_table = True
            continue
        if in_table:
            if line.startswith("|") and not line.startswith("| ---"):
                # Extract first column (file path)
                cells = [c.strip() for c in line.split("|")]
                if len(cells) >= 2:
                    path_cell = cells[1]
                    match = re.search(r"`([^`]+)`", path_cell)
                    path = match.group(1).strip() if match else path_cell.strip("`").strip()
                    if path and not path.startswith("---"):
                        paths.add(path)
            elif not line.strip().startswith("|"):
                in_table = False
    return paths


def _dedupe_strings(items: list[str]) -> list[str]:
    """De-duplicate strings while preserving first-seen order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _compute_log_since_window(elapsed_since_turn_start_s: Optional[float]) -> str:
    """Compute `instrukt-ai-logs --since` window from elapsed turn time.

    Uses minute granularity, rounded up, with a conservative 2-minute minimum.
    """
    if elapsed_since_turn_start_s is None or elapsed_since_turn_start_s <= 0:
        return "2m"
    minutes = max(2, int((elapsed_since_turn_start_s + 59) // 60))
    return f"{minutes}m"


# ---------------------------------------------------------------------------
# Heuristic engine (R2-R8)
# ---------------------------------------------------------------------------


def run_heuristics(
    git_files: list[str],
    timeline: TurnTimeline,
    context: CheckpointContext,
    log_since_window: str = "2m",
) -> CheckpointResult:
    """Run all checkpoint heuristics and return structured result."""
    result = CheckpointResult()

    def append_required_action(action: str) -> None:
        if action not in result.required_actions:
            result.required_actions.append(action)

    # 1. File categorization
    categories = _categorize_files(git_files)
    result.categories = [c.name for c in categories]

    # 2. Build required actions with verification gap detection
    for category in sorted(categories, key=lambda c: c.precedence):
        if not category.instruction:
            continue  # e.g., hook runtime — no action needed

        evidence_seen = False
        if category.evidence_substrings:
            if category.evidence_must_follow_last_mutation:
                mutation_idx = _last_category_mutation_index(timeline, category, context.project_path)
                if mutation_idx is not None:
                    evidence_seen = _has_evidence_after_index(
                        timeline,
                        category.evidence_substrings,
                        mutation_idx,
                    )
                else:
                    evidence_seen = _has_evidence(timeline, category.evidence_substrings)
            else:
                evidence_seen = _has_evidence(timeline, category.evidence_substrings)

        if category.evidence_substrings and evidence_seen:
            # Also check for status evidence when daemon/config restart was suppressed
            if "make restart" in category.instruction and not _has_status_evidence(timeline):
                append_required_action("Run `make status` to verify daemon health")
            continue  # Suppress the main instruction

        append_required_action(category.instruction)
        # Add observation about missing verification
        if timeline.has_data and category.evidence_substrings:
            result.observations.append(
                f"{category.name.capitalize()} was modified but "
                f"`{category.evidence_substrings[0]}` was not observed this turn"
            )

    # Add log check if code changed and not already done
    has_code_changes = any(c.name != "tests only" for c in categories)
    if has_code_changes and not _has_evidence(timeline, CHECKPOINT_LOG_CHECK_EVIDENCE):
        append_required_action(f"Check logs: `instrukt-ai-logs teleclaude --since {log_since_window}`")

    # Add test instruction if code changed and not already done
    if categories and not _has_evidence(timeline, CHECKPOINT_TEST_EVIDENCE):
        append_required_action("Run targeted tests for changed behavior")

    # 3. Error state detection
    result.observations.extend(_check_error_state(timeline))

    # 4. Edit hygiene
    result.observations.extend(_check_edit_hygiene(timeline, git_files))

    # 5. Working slug alignment
    result.observations.extend(_check_slug_alignment(git_files, context))

    # Keep observations signal-rich and non-repetitive.
    result.observations = _dedupe_strings(result.observations)

    # Determine all-clear
    if not result.required_actions and not result.observations:
        result.is_all_clear = True

    return result


# ---------------------------------------------------------------------------
# Message composition (R9)
# ---------------------------------------------------------------------------


def build_checkpoint_message(
    git_files: list[str],
    timeline: TurnTimeline,
    context: CheckpointContext,
    log_since_window: str = "2m",
) -> str:
    """Build a structured checkpoint message from all signal sources."""
    result = run_heuristics(git_files, timeline, context, log_since_window=log_since_window)
    return _compose_checkpoint_message(git_files, result)


def _compose_checkpoint_message(git_files: list[str], result: CheckpointResult) -> str:
    """Compose checkpoint text from precomputed heuristic output."""
    response_policy = (
        "Response policy: perform checkpoint-required housekeeping silently. "
        "End with a short user-relevant debrief about actual task outcome, blocker, or decision needed. "
        "Do not mention checkpoint chores."
    )
    escape_hatch = (
        "Escape hatch (last resort only, and only when there is no actionable information left): "
        'run `touch "$TMPDIR/teleclaude_checkpoint_clear"` to disable checkpoints for this session. '
        "Re-enable by removing that file."
    )

    # Special case: docs only
    if not git_files or _is_docs_only(git_files):
        return (
            f"{CHECKPOINT_PREFIX}No code changes detected this turn. Did you run `telec sync`?\n"
            f"Commit if ready.\n\n{response_policy}\n\n{escape_hatch}"
        )

    # Special case: all clear
    if result.is_all_clear:
        return (
            f"{CHECKPOINT_PREFIX}All expected validations were observed. "
            "Docs check: if relevant, update existing docs or add a new doc. "
            f"Commit if ready.\n\n{response_policy}\n\n{escape_hatch}"
        )

    lines: list[str] = [f"{CHECKPOINT_PREFIX}Context-aware checkpoint"]

    # Changed files summary grouped by category
    if result.categories:
        lines.append("")
        lines.append(f"Changed: {', '.join(result.categories)}")

    # Required actions (numbered)
    if result.required_actions:
        lines.append("")
        lines.append("Required actions:")
        for i, action in enumerate(result.required_actions, 1):
            lines.append(f"{i}. {action}")
        lines.append(f"{len(result.required_actions) + 1}. Commit only after steps above are complete")

    # Observations (bullet points)
    if result.observations:
        lines.append("")
        lines.append("Observations:")
        for obs in result.observations:
            lines.append(f"- {obs}")

    # Capture reminder
    lines.append("Finish the steps above.")
    lines.append("")
    lines.append(response_policy)
    lines.append("")
    lines.append(escape_hatch)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def get_checkpoint_content(
    transcript_path: Optional[str],
    agent_name: AgentName,
    project_path: str,
    working_slug: Optional[str] = None,
    elapsed_since_turn_start_s: Optional[float] = None,
) -> Optional[str]:
    """Build context-aware checkpoint content for both hook and codex routes.

    Top-level entry point that orchestrates git diff, transcript extraction,
    and message building.

    Returns:
    - str: checkpoint payload when agent action is required or confirmation is useful.
    - None: no turn-local code changes detected; skip checkpoint entirely.
    - CHECKPOINT_MESSAGE: fail-open fallback on internal errors.
    """
    try:
        transcript_meta = _transcript_observability(transcript_path)
        base_extra = {
            "agent": agent_name.value,
            "project_path": project_path or "",
            "working_slug": working_slug or "",
            "transcript_present": bool(transcript_path),
            "transcript_path": transcript_meta["transcript_path"],
            "transcript_exists": transcript_meta["transcript_exists"],
            "transcript_size_bytes": transcript_meta["transcript_size_bytes"],
        }
        if not _is_checkpoint_project_supported(project_path):
            logger.info(
                "Checkpoint payload skipped (project out of scope)",
                extra={**base_extra, "mode": "unsupported_project", "message_len": 0},
            )
            return None

        git_files = _get_uncommitted_files(project_path)
        if git_files is None:
            logger.warning(
                "Checkpoint payload fallback to generic message (git unavailable)",
                extra=base_extra,
            )
            return CHECKPOINT_MESSAGE  # git unavailable — fall back to generic

        if transcript_path:
            timeline = extract_tool_calls_current_turn(transcript_path, agent_name)
        else:
            timeline = TurnTimeline(tool_calls=[], has_data=False)

        effective_git_files = _scope_git_files_to_current_turn(
            git_files,
            timeline,
            project_path,
        )

        # Intentionally no full-session fallback:
        # checkpoint attribution must stay strictly turn-local.
        used_session_fallback = False

        context = CheckpointContext(
            project_path=project_path,
            working_slug=working_slug,
            agent_name=agent_name,
        )
        log_since_window = _compute_log_since_window(elapsed_since_turn_start_s)

        result = run_heuristics(effective_git_files, timeline, context, log_since_window=log_since_window)
        if not effective_git_files or _is_docs_only(effective_git_files):
            logger.info(
                "Checkpoint payload skipped (no turn-local code changes)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "dirty_files": len(git_files),
                    "changed_files": len(effective_git_files),
                    "categories": result.categories,
                    "required_actions": len(result.required_actions),
                    "observations": len(result.observations),
                    "mode": "silent_no_changes",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                },
            )
            return None

        if result.is_all_clear:
            logger.info(
                "Checkpoint payload skipped (all checks already satisfied)",
                extra={
                    **base_extra,
                    "timeline_has_data": timeline.has_data,
                    "timeline_records": len(timeline.tool_calls),
                    "dirty_files": len(git_files),
                    "changed_files": len(effective_git_files),
                    "categories": result.categories,
                    "required_actions": len(result.required_actions),
                    "observations": len(result.observations),
                    "mode": "silent_all_clear",
                    "message_len": 0,
                    "used_session_fallback": used_session_fallback,
                },
            )
            return None

        message = _compose_checkpoint_message(effective_git_files, result)
        mode = (
            "docs_only"
            if (not effective_git_files or _is_docs_only(effective_git_files))
            else ("all_clear" if result.is_all_clear else "actionable")
        )
        logger.info(
            "Checkpoint payload computed",
            extra={
                **base_extra,
                "timeline_has_data": timeline.has_data,
                "timeline_records": len(timeline.tool_calls),
                "dirty_files": len(git_files),
                "changed_files": len(effective_git_files),
                "categories": result.categories,
                "required_actions": len(result.required_actions),
                "observations": len(result.observations),
                "mode": mode,
                "message_len": len(message),
                "used_session_fallback": used_session_fallback,
            },
        )
        return message

    except Exception:
        logger.warning(
            "Checkpoint content build failed (fail-open)",
            extra={
                "agent": agent_name.value,
                "project_path": project_path or "",
                "working_slug": working_slug or "",
                "transcript_present": bool(transcript_path),
                "transcript_path": transcript_path or "",
            },
            exc_info=True,
        )
        return CHECKPOINT_MESSAGE

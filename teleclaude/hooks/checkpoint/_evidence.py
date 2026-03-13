"""Evidence checking, error state detection, edit hygiene, and slug alignment."""

import re
import shlex
from pathlib import Path

from teleclaude.constants import (
    CHECKPOINT_BLAST_RADIUS_THRESHOLD,
    CHECKPOINT_ERROR_ENRICHMENT,
    CHECKPOINT_GENERIC_ERROR_MESSAGE,
    CHECKPOINT_STATUS_EVIDENCE,
    CHECKPOINT_TEST_ERROR_COMMANDS,
    CHECKPOINT_TEST_ERROR_MESSAGE,
    FileCategory,
)
from teleclaude.hooks.checkpoint._git import (
    _canonical_tool_name,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _file_matches_category,
    _normalize_repo_path,
    _segment_tokens,
    _split_shell_segments,
)
from teleclaude.hooks.checkpoint._models import CheckpointContext
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

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
        if tool_name not in {"edit", "write", "multiedit", "apply_patch", "notebookedit"}:
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
        if "Files to Change" in line or ("File" in line and "Change" in line):
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


def _compute_log_since_window(elapsed_since_turn_start_s: float | None) -> str:
    """Compute `instrukt-ai-logs --since` window from elapsed turn time.

    Uses minute granularity, rounded up, with a conservative 2-minute minimum.
    """
    if elapsed_since_turn_start_s is None or elapsed_since_turn_start_s <= 0:
        return "2m"
    minutes = max(2, int((elapsed_since_turn_start_s + 59) // 60))
    return f"{minutes}m"

"""Evidence checking, error state detection, edit hygiene, and slug alignment."""

import re
from pathlib import Path

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    CHECKPOINT_BLAST_RADIUS_THRESHOLD,
    CHECKPOINT_COMMIT_EVIDENCE,
    FileCategory,
)
from teleclaude.core.todos_db import get_todos_db_sync
from teleclaude.hooks.checkpoint._git import (
    _canonical_tool_name,
    _command_likely_mutates_files,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _extract_shell_touched_paths,
    _file_matches_category,
    _normalize_repo_path,
    _segment_tokens,
    _split_shell_segments,
)
from teleclaude.hooks.checkpoint._models import CheckpointContext
from teleclaude.snippet_validation import companion_parent, is_companion
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

__all__ = [
    "_check_companion_drift",
    "_check_edit_hygiene",
    "_check_slug_alignment",
    "_command_has_evidence",
    "_compute_log_since_window",
    "_dedupe_strings",
    "_extract_plan_file_paths",
    "_has_commit_evidence",
    "_has_commit_evidence_after_last_mutation",
    "_has_evidence",
    "_has_evidence_after_index",
    "_iter_shell_command_records",
    "_last_category_mutation_index",
    "_last_git_file_mutation_index",
    "_segment_matches_evidence",
]

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


def _has_commit_evidence(timeline: TurnTimeline) -> bool:
    """Return True when the commit-options command ran in this checkpoint cycle."""
    if not timeline.has_data:
        return False
    for record in timeline.tool_calls:
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            continue
        command = _extract_shell_command(record.input_data)
        if not _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
            continue
        if not record.had_error or _is_expected_commit_classification(record):
            return True
    return False


def _has_commit_evidence_after_index(timeline: TurnTimeline, after_index: int) -> bool:
    """Return True when commit-options evidence follows a timeline index."""
    if not timeline.has_data:
        return False
    for idx, record in enumerate(timeline.tool_calls):
        if idx <= after_index:
            continue
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            continue
        command = _extract_shell_command(record.input_data)
        if not _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
            continue
        if not record.had_error or _is_expected_commit_classification(record):
            return True
    return False


def _has_commit_evidence_after_last_mutation(
    timeline: TurnTimeline,
    git_files: list[str],
    project_path: str,
) -> bool:
    """Return True only when commit-options evidence follows the last relevant mutation."""
    last_mutation_idx = _last_git_file_mutation_index(timeline, git_files, project_path)
    if last_mutation_idx is None:
        return _has_commit_evidence(timeline)
    return _has_commit_evidence_after_index(timeline, last_mutation_idx)


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


_MUTATOR_TOOLS = {
    "edit",
    "write",
    "multiedit",
    "apply_patch",
    "notebookedit",
    "bash",
    "shell",
    "terminal",
    "run_shell_command",
    "exec_command",
}
_SHELL_TOOLS = {"bash", "shell", "terminal", "run_shell_command", "exec_command"}


def _record_touched_paths(
    record: ToolCallRecord,
    tool_name: str,
    project_path: str,
    *,
    include_shell_inference: bool,
) -> set[str]:
    """Collect repo-relative paths touched by a single tool call record."""
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
    if include_shell_inference and tool_name in _SHELL_TOOLS:
        command = _extract_shell_command(record.input_data)
        if _command_likely_mutates_files(command):
            touched.update(_extract_shell_touched_paths(command, project_path))
    return touched


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
        if tool_name not in _MUTATOR_TOOLS:
            continue
        touched = _record_touched_paths(record, tool_name, project_path, include_shell_inference=False)
        if any(_file_matches_category(path, category) for path in touched):
            last_index = idx

    return last_index


def _last_git_file_mutation_index(
    timeline: TurnTimeline,
    git_files: list[str],
    project_path: str,
) -> int | None:
    """Return the last timeline index that mutated one of the effective git files."""
    if not timeline.has_data or not git_files:
        return None

    effective_files = {path.strip().replace("\\", "/") for path in git_files if path.strip()}
    if not effective_files:
        return None

    last_index: int | None = None
    for idx, record in enumerate(timeline.tool_calls):
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in _MUTATOR_TOOLS:
            continue
        touched = _record_touched_paths(record, tool_name, project_path, include_shell_inference=True)
        if touched & effective_files:
            last_index = idx

    return last_index


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
    if evidence == "telec code test":
        return head == "telec" and rest[:2] == ["code", "test"]
    if evidence == "telec code commit":
        return head == "telec" and rest[:2] == ["code", "commit"]
    if evidence == "uv sync":
        return head == "uv" and "sync" in rest
    if evidence == "telec projects init":
        return head == "telec" and rest[:2] == ["projects", "init"]
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
    if evidence == "telec sessions restart":
        return head == "telec" and "sessions" in rest and "restart" in rest
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


def _is_expected_commit_classification(record: ToolCallRecord) -> bool:
    """The main-branch commit gate is the expected output of the checkpoint commit step."""
    command = _extract_shell_command(record.input_data)
    if not _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
        return False
    snippet = (record.result_snippet or "").lower()
    return "commits on main require classification" in snippet


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


def _check_companion_drift(git_files: list[str], project_path: str) -> list[str]:
    """Return actions for parent snippet edits missing their pending companions."""
    changed = {path.strip().replace("\\", "/") for path in git_files if path.strip()}
    if not changed:
        return []

    project_root = Path(project_path)
    actions: list[str] = []
    for rel_path in sorted(changed):
        if not rel_path.startswith("docs/") or not rel_path.endswith(".md"):
            continue
        parent_path = project_root / rel_path
        if is_companion(parent_path):
            continue
        for companion_path in _pending_companions(parent_path):
            companion_rel = companion_path.relative_to(project_root).as_posix()
            if companion_rel in changed:
                continue
            actions.append(f"Mirror `{rel_path}` into pending companion `{companion_rel}` before stopping")
    return actions


def _pending_companions(parent_path: Path) -> list[Path]:
    """Return pending companion siblings for a live parent snippet path."""
    if not parent_path.exists():
        return []
    return sorted(
        candidate
        for candidate in parent_path.parent.glob(f"{parent_path.stem}.*.md")
        if is_companion(candidate) and companion_parent(candidate) == parent_path
    )


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

    db = get_todos_db_sync(context.project_path)
    plan_text = db.read_artifact_sync(context.working_slug, ARTIFACT_IMPLEMENTATION_PLAN)
    if not plan_text:
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

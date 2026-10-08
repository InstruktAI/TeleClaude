"""Evidence checking, blast-radius, and companion presence."""

from pathlib import Path

from teleclaude.checkpoint_model import scope_matches
from teleclaude.cli.session_send_request import SessionSendUsageError, resolve_session_send
from teleclaude.cli.telec.handlers._arg_parsing import CliUsageError
from teleclaude.constants import (
    CHECKPOINT_BLAST_RADIUS_THRESHOLD,
    CHECKPOINT_COMMIT_EVIDENCE,
    CHECKPOINT_REVIEW_DISPATCH_EVIDENCE,
    CheckpointScope,
    SlashCommand,
)
from teleclaude.hooks.checkpoint._git import (
    _canonical_tool_name,
    _extract_apply_patch_paths,
    _extract_shell_command,
    _normalize_repo_path,
    _split_shell_segments,
)
from teleclaude.shell_path_parser import executable_command_tokens, matches_command_prefix
from teleclaude.snippet_validation import companion_parent, is_companion, is_retirement_companion
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

_SHELL_TOOL_NAMES = frozenset({"bash", "shell", "terminal", "run_shell_command", "exec_command"})
_SESSIONS_SEND_PREFIX = ("telec", "sessions", "send")

__all__ = [
    "_check_blast_radius",
    "_check_companion_drift",
    "_command_has_evidence",
    "_compute_log_since_window",
    "_dedupe_strings",
    "_has_commit_evidence",
    "_has_commit_evidence_after_last_mutation",
    "_has_evidence",
    "_has_evidence_after_index",
    "_has_review_dispatch_evidence",
    "_iter_shell_command_records",
    "_last_git_file_mutation_index",
    "_last_scope_mutation_index",
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
        command = _extract_shell_command(record.input_data)
        if _command_has_evidence(command, substrings):
            return True
    return False


def _has_review_dispatch_evidence(timeline: TurnTimeline, live_reviewer_ids: frozenset[str]) -> bool:
    """Return True when the commit(s) were dispatched to a reviewer this cycle.

    Recognizes a fresh ``/review-commits`` run, and a ``telec sessions send``
    addressed to one of this session's live commit reviewers. The send is
    identified by its target session, never by its message text.
    """
    if _has_evidence(timeline, CHECKPOINT_REVIEW_DISPATCH_EVIDENCE):
        return True
    if not timeline.has_data or not live_reviewer_ids:
        return False
    for record in timeline.tool_calls:
        if _canonical_tool_name(record.tool_name) not in _SHELL_TOOL_NAMES:
            continue
        for segment in _split_shell_segments(_extract_shell_command(record.input_data)):
            if _segment_sends_to(segment, live_reviewer_ids):
                return True
    return False


def _segment_sends_to(segment: str, session_ids: frozenset[str]) -> bool:
    """Return whether a command segment is a ``telec sessions send`` to one of ``session_ids``."""
    if not matches_command_prefix(segment, _SESSIONS_SEND_PREFIX):
        return False
    return _send_target(executable_command_tokens(segment)[len(_SESSIONS_SEND_PREFIX) :]) in session_ids


def _send_target(arguments: list[str]) -> str | None:
    """Return the session a ``telec sessions send`` delivers a message to, or None when it delivers none."""
    try:
        request = resolve_session_send(arguments)
    except (CliUsageError, SessionSendUsageError):
        return None
    return request.session_id if request.message else None


def _has_commit_evidence(timeline: TurnTimeline) -> bool:
    """Return True when the commit-options command ran in this checkpoint cycle."""
    if not timeline.has_data:
        return False
    for record in timeline.tool_calls:
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            continue
        command = _extract_shell_command(record.input_data)
        if _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
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
        if _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
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
    """Return shell-like tool calls with extracted command text, regardless of outcome."""
    records: list[tuple[int, ToolCallRecord, str]] = []
    if not timeline.has_data:
        return records
    for idx, record in enumerate(timeline.tool_calls):
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
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
) -> set[str]:
    """Collect repo-relative mutation paths from a tool record's structured fields."""
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
    return touched


def _last_scope_mutation_index(
    timeline: TurnTimeline,
    scopes: list[CheckpointScope],
    project_path: str,
) -> int | None:
    """Return the last timeline index that mutated a file matching any given scope."""
    if not timeline.has_data or not scopes:
        return None

    last_index: int | None = None
    for idx, record in enumerate(timeline.tool_calls):
        tool_name = _canonical_tool_name(record.tool_name)
        if tool_name not in _MUTATOR_TOOLS:
            continue
        touched = _record_touched_paths(record, tool_name, project_path)
        if any(scope_matches(path, scope) for path in touched for scope in scopes):
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
        if tool_name in _SHELL_TOOLS:
            command = _extract_shell_command(record.input_data)
            if _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
                # A commit is not a mutation of the files it commits.
                continue
        touched = _record_touched_paths(record, tool_name, project_path)
        if touched & effective_files:
            last_index = idx

    return last_index


def _segment_matches_evidence(segment: str, evidence: str) -> bool:
    """Match evidence against executable intent, not raw substring mentions."""
    tokens = executable_command_tokens(segment)
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
        return matches_command_prefix(segment, ("telec", "code", "test"))
    if evidence == "telec code commit":
        return matches_command_prefix(segment, ("telec", "code", "commit"))
    if evidence == "uv sync":
        return head == "uv" and "sync" in rest
    if evidence == "pytest":
        return (
            head == "pytest"
            or (head == "uv" and "pytest" in rest)
            or (head in {"python", "python3"} and len(rest) >= 2 and rest[0] == "-m" and rest[1] == "pytest")
        )
    if evidence == "instrukt-ai-logs":
        return head == "instrukt-ai-logs"
    if evidence == "telec sessions restart":
        return head == "telec" and "sessions" in rest and "restart" in rest
    if evidence == SlashCommand.REVIEW_COMMITS.value:
        # Only a real dispatch: `telec sessions run --command review-commits`,
        # with the command name as the value of --command (not merely mentioned).
        # A bare, unqualified token still resolves to this same command until the
        # documentation sweep lands, so both forms count as evidence here.
        if head != "telec" or "sessions" not in rest or "run" not in rest or "--command" not in tokens:
            return False
        command_idx = tokens.index("--command")
        if command_idx + 1 >= len(tokens):
            return False
        bare_evidence = evidence.rsplit("/", 1)[-1]
        return tokens[command_idx + 1] in {evidence, f"/{evidence}", bare_evidence, f"/{bare_evidence}"}
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


# ---------------------------------------------------------------------------
# Blast radius (R6)
# ---------------------------------------------------------------------------


def _check_blast_radius(git_files: list[str]) -> list[str]:
    """Observe when changes span many top-level subsystems (git-only, no transcript needed)."""
    observations: list[str] = []
    if git_files:
        top_dirs = {f.split("/")[0] for f in git_files if "/" in f}
        if len(top_dirs) > CHECKPOINT_BLAST_RADIUS_THRESHOLD:
            observations.append("Changes span multiple subsystems — consider committing completed work incrementally")
    return observations


def _check_companion_drift(git_files: list[str], project_path: str) -> list[str]:
    """Return mirror actions for parent edits with non-empty pending companions."""
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
    """Return non-retirement companion siblings for a live parent snippet path."""
    if not parent_path.exists():
        return []
    return sorted(
        candidate
        for candidate in parent_path.parent.glob(f"{parent_path.stem}.*.md")
        if is_companion(candidate)
        and not is_retirement_companion(candidate)
        and companion_parent(candidate) == parent_path
    )


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

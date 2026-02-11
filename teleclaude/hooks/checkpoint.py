"""Context-aware checkpoint builder for agent stop boundaries.

Thin consumer of transcript.py — never reads or parses transcripts directly.
Uses git diff for file-based signals and TurnTimeline for transcript-based signals.
All heuristics are deterministic pattern matching, zero LLM calls.
"""

import logging
import subprocess
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional

from teleclaude.constants import (
    CHECKPOINT_BLAST_RADIUS_THRESHOLD,
    CHECKPOINT_ERROR_ENRICHMENT,
    CHECKPOINT_FILE_CATEGORIES,
    CHECKPOINT_GENERIC_ERROR_MESSAGE,
    CHECKPOINT_LOG_CHECK_EVIDENCE,
    CHECKPOINT_MESSAGE,
    CHECKPOINT_NO_ACTION_PATTERNS,
    CHECKPOINT_STATUS_EVIDENCE,
    CHECKPOINT_TEST_ERROR_COMMANDS,
    CHECKPOINT_TEST_ERROR_MESSAGE,
    CHECKPOINT_TEST_EVIDENCE,
    FileCategory,
)
from teleclaude.core.agents import AgentName
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline, extract_tool_calls_current_turn

logger = logging.getLogger(__name__)


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
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path or None,
        )
        if result.returncode != 0:
            return None
        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        return files
    except Exception:
        return None


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
        if record.tool_name != "Bash":
            continue
        if record.had_error:
            continue
        command = str(record.input_data.get("command", ""))
        if any(sub in command for sub in substrings):
            return True
    return False


def _has_status_evidence(timeline: TurnTimeline) -> bool:
    """Check if make status was run after a restart."""
    if not timeline.has_data:
        return False
    saw_restart = False
    for record in timeline.tool_calls:
        if record.tool_name != "Bash":
            continue
        command = str(record.input_data.get("command", ""))
        if record.had_error:
            continue
        if "make restart" in command:
            saw_restart = True
        elif saw_restart and any(sub in command for sub in CHECKPOINT_STATUS_EVIDENCE):
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
        # Layer 1: check for resolution evidence after this error
        subsequent = timeline.tool_calls[error_pos + 1 :]

        if _is_error_resolved(error_record, subsequent):
            continue

        # Layer 2: enrich unresolved errors with specific feedback
        observations.append(_enrich_error(error_record))

    return observations


def _is_error_resolved(error_record: ToolCallRecord, subsequent: list[ToolCallRecord]) -> bool:
    """Check if a subsequent action addressed the error."""
    error_command = str(error_record.input_data.get("command", ""))
    error_file = str(error_record.input_data.get("file_path", ""))

    for later in subsequent:
        # Re-invocation of the same command
        if later.tool_name == "Bash":
            later_command = str(later.input_data.get("command", ""))
            # Same command re-run (e.g., second pytest after first failed)
            if error_command and _commands_overlap(error_command, later_command):
                return True
            # Bash command referencing same file area
            if error_file and error_file in later_command:
                return True

        # Edit/Write targeting same file path
        if later.tool_name in ("Edit", "Write"):
            later_file = str(later.input_data.get("file_path", ""))
            if error_file and later_file == error_file:
                return True
            # Also check if Edit targets a file mentioned in the error command
            if error_command and later_file and later_file in error_command:
                return True

    return False


def _commands_overlap(cmd_a: str, cmd_b: str) -> bool:
    """Check if two commands are essentially the same operation.

    Extracts the base command (first word or known compound like 'make test')
    and checks for equality.
    """

    def _base_cmd(cmd: str) -> str:
        stripped = cmd.strip()
        for compound in ("make test", "make restart", "make lint", "make status", "pip install"):
            if compound in stripped:
                return compound
        parts = stripped.split()
        return parts[0] if parts else ""

    base_a = _base_cmd(cmd_a)
    base_b = _base_cmd(cmd_b)
    return bool(base_a) and base_a == base_b


def _enrich_error(record: ToolCallRecord) -> str:
    """Produce targeted feedback for an unresolved error (Layer 2)."""
    snippet = record.result_snippet

    # Check known patterns
    for pattern, message in CHECKPOINT_ERROR_ENRICHMENT:
        if pattern in snippet:
            return message

    # Check if it was a test command
    command = str(record.input_data.get("command", ""))
    if any(cmd in command for cmd in CHECKPOINT_TEST_ERROR_COMMANDS):
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
            if record.tool_name == "Read":
                path = str(record.input_data.get("file_path", ""))
                if path:
                    read_files.add(path)
            elif record.tool_name == "Edit":
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
                    path = cells[1].strip("`").strip()
                    if path and not path.startswith("---"):
                        paths.add(path)
            elif not line.strip().startswith("|"):
                in_table = False
    return paths


# ---------------------------------------------------------------------------
# Heuristic engine (R2-R8)
# ---------------------------------------------------------------------------


def run_heuristics(
    git_files: list[str],
    timeline: TurnTimeline,
    context: CheckpointContext,
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

        if category.evidence_substrings and _has_evidence(timeline, category.evidence_substrings):
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
        append_required_action("Check logs: `instrukt-ai-logs teleclaude --since 2m`")

    # Add test instruction if code changed and not already done
    if categories and not _has_evidence(timeline, CHECKPOINT_TEST_EVIDENCE):
        append_required_action("Run targeted tests for changed behavior")

    # 3. Error state detection
    result.observations.extend(_check_error_state(timeline))

    # 4. Edit hygiene
    result.observations.extend(_check_edit_hygiene(timeline, git_files))

    # 5. Working slug alignment
    result.observations.extend(_check_slug_alignment(git_files, context))

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
) -> str:
    """Build a structured checkpoint message from all signal sources."""
    result = run_heuristics(git_files, timeline, context)

    # Special case: docs only
    if not git_files or _is_docs_only(git_files):
        return (
            "Context-aware checkpoint\n\n"
            "No code changes detected. "
            "Check logs: `instrukt-ai-logs teleclaude --since 2m`.\n"
            "Capture memories/bugs/ideas if needed. Commit if ready."
        )

    # Special case: all clear
    if result.is_all_clear:
        return "All expected validations were observed. Commit if ready."

    lines: list[str] = ["Context-aware checkpoint"]

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
    lines.append("")
    lines.append("Capture memories/bugs/ideas if needed.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def get_checkpoint_content(
    transcript_path: Optional[str],
    agent_name: AgentName,
    project_path: str,
    working_slug: Optional[str] = None,
) -> str:
    """Build context-aware checkpoint content for both hook and codex routes.

    Top-level entry point that orchestrates git diff, transcript extraction,
    and message building. Fail-open: returns generic Phase 1 message on any error.
    """
    try:
        git_files = _get_uncommitted_files(project_path)
        if git_files is None:
            return CHECKPOINT_MESSAGE  # git unavailable — fall back to generic

        if transcript_path:
            timeline = extract_tool_calls_current_turn(transcript_path, agent_name)
        else:
            timeline = TurnTimeline(tool_calls=[], has_data=False)

        context = CheckpointContext(
            project_path=project_path,
            working_slug=working_slug,
            agent_name=agent_name,
        )

        return build_checkpoint_message(git_files, timeline, context)

    except Exception:
        logger.debug("Checkpoint content build failed (fail-open)", exc_info=True)
        return CHECKPOINT_MESSAGE

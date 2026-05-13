"""Evidence checking, error state detection, edit hygiene, and slug alignment."""

import re
import shlex

from teleclaude.constants import (
    ARTIFACT_IMPLEMENTATION_PLAN,
    CHECKPOINT_BLAST_RADIUS_THRESHOLD,
    CHECKPOINT_COMMIT_EVIDENCE,
    CHECKPOINT_ERROR_ENRICHMENT,
    CHECKPOINT_GENERIC_ERROR_MESSAGE,
    CHECKPOINT_LOG_CHECK_EVIDENCE,
    CHECKPOINT_STATUS_EVIDENCE,
    CHECKPOINT_TEST_ERROR_COMMANDS,
    CHECKPOINT_TEST_ERROR_MESSAGE,
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
from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

__all__ = [
    "_check_edit_hygiene",
    "_check_error_state",
    "_check_slug_alignment",
    "_command_has_evidence",
    "_command_invokes_search",
    "_command_references_file",
    "_commands_overlap",
    "_compute_log_since_window",
    "_dedupe_strings",
    "_enrich_error",
    "_extract_plan_file_paths",
    "_has_commit_evidence",
    "_has_commit_evidence_after_last_mutation",
    "_has_evidence",
    "_has_evidence_after_index",
    "_has_status_evidence",
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
        mutator_tools = {
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
        if tool_name not in mutator_tools:
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
        mutator_tools = {
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
        if tool_name not in mutator_tools:
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
        if tool_name in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            command = _extract_shell_command(record.input_data)
            if _command_likely_mutates_files(command):
                touched.update(_extract_shell_touched_paths(command, project_path))

        if touched & effective_files:
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
    if _is_user_aborted_command_error(snippet):
        return True
    if _is_expected_commit_classification(record):
        return True
    if _is_global_python_stdin_probe(command):
        return True
    if _command_invokes_search(command):
        if "process exited with code 1" in snippet:
            # `rg`/`grep` use exit code 1 for "no matches"; this is informational.
            if "no such file or directory" not in snippet and "permission denied" not in snippet:
                return True
    return False


def _is_user_aborted_command_error(snippet: str) -> bool:
    """User-cancelled commands are interaction control, not unresolved work."""
    return any(
        marker in snippet
        for marker in (
            "aborted by user",
            "interrupted by user",
            "cancelled by user",
            "canceled by user",
        )
    )


def _is_global_python_stdin_probe(command: str) -> bool:
    """Bare/global Python heredoc probes are invalid for this repo and do not carry signal."""
    for segment in _split_shell_segments(command):
        tokens = _segment_tokens(segment)
        if len(tokens) < 2 or tokens[1] != "-":
            continue
        executable = tokens[0].replace("\\", "/")
        basename = executable.rsplit("/", 1)[-1]
        if basename not in {"python", "python3"}:
            continue
        if executable in {"python", "python3"} or ("/.venv/" not in executable and not executable.startswith(".venv/")):
            return "<<" in segment
    return False


def _is_expected_commit_classification(record: ToolCallRecord) -> bool:
    """The main-branch commit gate is the expected output of the checkpoint commit step."""
    command = _extract_shell_command(record.input_data)
    if not _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
        return False
    snippet = (record.result_snippet or "").lower()
    return "commits on main require classification" in snippet


def _is_error_resolved(error_record: ToolCallRecord, subsequent: list[ToolCallRecord]) -> bool:
    """Check if a subsequent action addressed the error."""
    error_command = _extract_shell_command(error_record.input_data)
    error_file = str(error_record.input_data.get("file_path", ""))
    error_families = _command_validation_families(error_command)

    for later in subsequent:
        # Re-invocation of the same command
        later_tool_name = _canonical_tool_name(later.tool_name)
        if later_tool_name in {"bash", "shell", "terminal", "run_shell_command", "exec_command"}:
            if later.had_error and not _is_non_actionable_error(later):
                continue
            later_command = _extract_shell_command(later.input_data)
            # Same command re-run (e.g., second pytest after first failed)
            if error_command and _commands_overlap(error_command, later_command):
                return True
            if _validation_family_resolves(error_command, later_command, error_families):
                return True
            # Bash command referencing same file area
            if error_file and _command_references_file(later_command, error_file):
                return True

        # Edit/Write targeting same file path
        if _canonical_tool_name(later.tool_name) in {"edit", "write"}:
            if later.had_error:
                continue
            later_file = str(later.input_data.get("file_path", ""))
            if error_file and later_file == error_file:
                return True
            # Also check if Edit targets a file mentioned in the error command
            if error_command and later_file and _command_references_file(error_command, later_file):
                return True

    return False


def _command_validation_families(command: str) -> set[str]:
    """Classify validation commands so later successful checks clear stale errors."""
    families: set[str] = set()
    if _command_has_evidence(command, CHECKPOINT_TEST_ERROR_COMMANDS):
        families.add("tests")
    if _command_has_evidence(command, CHECKPOINT_LOG_CHECK_EVIDENCE):
        families.add("logs")
    if _command_has_evidence(command, CHECKPOINT_STATUS_EVIDENCE):
        families.add("status")
    if _command_has_evidence(command, CHECKPOINT_COMMIT_EVIDENCE):
        families.add("commit")

    for segment in _split_shell_segments(command):
        tokens = _segment_tokens(segment)
        if not tokens:
            continue
        head = tokens[0].rsplit("/", 1)[-1]
        rest = tokens[1:]
        if head == "uv" and len(rest) >= 2 and rest[0] == "run":
            head = rest[1].rsplit("/", 1)[-1]
            rest = rest[2:]
        if head == "ruff" and (not rest or "check" in rest):
            families.add("lint")
        if head == "pyright":
            families.add("typecheck")
    return families


def _validation_family_resolves(error_command: str, later_command: str, error_families: set[str]) -> bool:
    """Return True when a later validation command is broad enough to resolve an earlier error."""
    later_families = _command_validation_families(later_command)
    for family in error_families & later_families:
        if family in {"commit", "logs", "status"}:
            return True
        error_targets = _validation_targets(error_command, family)
        later_targets = _validation_targets(later_command, family)
        if family == "tests" and not _pytest_selectors_cover(
            _pytest_selectors(error_command),
            _pytest_selectors(later_command),
        ):
            continue
        if _targets_cover(later_targets, error_targets):
            return True
    return False


def _validation_targets(command: str, family: str) -> set[str]:
    """Extract path-like validation targets for scope-aware stale-error clearing."""
    targets: set[str] = set()
    for segment in _split_shell_segments(command):
        tokens = _segment_tokens(segment)
        if not tokens:
            continue
        head = tokens[0].rsplit("/", 1)[-1]
        rest = tokens[1:]
        if head == "uv" and len(rest) >= 2 and rest[0] == "run":
            head = rest[1].rsplit("/", 1)[-1]
            rest = rest[2:]
        if family == "tests":
            if head == "telec" and rest[:2] == ["code", "test"]:
                targets.update(_path_like_args(rest[2:]))
            elif head == "make" and "test" in rest:
                targets.update(_path_like_args(rest[rest.index("test") + 1 :]))
            elif head == "pytest":
                targets.update(_path_like_args(rest))
            elif head in {"python", "python3"} and rest[:2] == ["-m", "pytest"]:
                targets.update(_path_like_args(rest[2:]))
        elif family == "lint" and head == "ruff":
            args = rest[1:] if rest[:1] == ["check"] else rest
            targets.update(_path_like_args(args))
        elif family == "typecheck" and head == "pyright":
            targets.update(_path_like_args(rest))
    return targets


def _path_like_args(args: list[str]) -> set[str]:
    """Return validation arguments that identify files or directories."""
    targets: set[str] = set()
    skip_next = False
    option_values = {
        "--config",
        "-c",
        "--rootdir",
        "--cov",
        "--cov-config",
        "--junitxml",
        "--basetemp",
        "--pythonpath",
        "--project",
        "--root",
        "--tb",
        "--timeout",
        "-k",
        "-m",
        "-p",
    }
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in option_values:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        target = arg.split("::", 1)[0].strip().replace("\\", "/")
        if target and not target.startswith("-"):
            targets.add(target.rstrip("/"))
    return targets


def _pytest_selectors(command: str) -> set[tuple[str, str]]:
    """Extract pytest selector options that narrow which tests run."""
    selectors: set[tuple[str, str]] = set()
    for segment in _split_shell_segments(command):
        tokens = _segment_tokens(segment)
        if not tokens:
            continue
        head = tokens[0].rsplit("/", 1)[-1]
        rest = tokens[1:]
        if head == "uv" and len(rest) >= 2 and rest[0] == "run":
            head = rest[1].rsplit("/", 1)[-1]
            rest = rest[2:]
        if head in {"python", "python3"} and rest[:2] == ["-m", "pytest"]:
            rest = rest[2:]
        elif head != "pytest":
            continue
        selectors.update(_extract_option_values(rest, {"-k", "-m"}))
    return selectors


def _extract_option_values(args: list[str], option_names: set[str]) -> set[tuple[str, str]]:
    """Return option/value pairs for options that constrain validation scope."""
    values: set[tuple[str, str]] = set()
    i = 0
    while i < len(args):
        arg = args[i]
        matched = next((name for name in option_names if arg == name or arg.startswith(f"{name}=")), None)
        if matched is None:
            i += 1
            continue
        if arg == matched:
            if i + 1 < len(args):
                values.add((matched, args[i + 1]))
                i += 2
                continue
        else:
            values.add((matched, arg.split("=", 1)[1]))
        i += 1
    return values


def _pytest_selectors_cover(error_selectors: set[tuple[str, str]], later_selectors: set[tuple[str, str]]) -> bool:
    """Return True when a later pytest run is broad enough for the failed selector."""
    return not later_selectors or later_selectors == error_selectors


def _targets_cover(later_targets: set[str], error_targets: set[str]) -> bool:
    """Return True when later validation targets cover the failed validation targets."""
    if not later_targets:
        return True
    if not error_targets:
        return False
    for failed in error_targets:
        if not any(failed == target or failed.startswith(f"{target}/") for target in later_targets):
            return False
    return True


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

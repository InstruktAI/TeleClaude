# Review Findings: fix-from-main-scoping

**Ad-hoc review (via from-main)** — scope and demo lanes skipped per procedure.

## Critical

No critical findings.

## Important

### IMP-1: `getattr` on known typed field violates fail-fast

**Location:** `teleclaude/todo_scaffold.py:554`
**Principle:** Fail Fast (Design Fundamentals)

```python
transcript_path = getattr(row, "native_log_file", None)
```

`native_log_file` is a typed field on `db_models.Session` (`native_log_file: str | None = None`).
Using `getattr` with a default hides potential `AttributeError` that would signal a real problem
(e.g., model schema change). Direct attribute access (`row.native_log_file`) is correct here —
it lets the type checker verify the access and fails fast if the field is removed.

**Fix:** Replace with `row.native_log_file`.
**Status:** Resolved during review — replaced `getattr` with direct attribute access.

### IMP-2: No test for empty intersection between session files and git status

**Location:** `tests/unit/test_todo_from_main.py`
**Principle:** Testing Policy — edge case coverage

When `_collect_session_touched_files` returns files that don't overlap with `git status` output,
the code raises `ValueError("No uncommitted changes match session-touched files...")` at line 644-646.
This is a real scenario (session touched files that were subsequently committed or reverted by
another process). No test covers this path.

**Fix:** Add a test where `_collect_session_touched_files` returns `{"completely/unrelated.py"}`
while git status reports `src/app.py` as modified. Assert `ValueError` with "No uncommitted changes match".

### IMP-3: `_collect_session_touched_files` has no direct unit test coverage

**Location:** `teleclaude/todo_scaffold.py:526-573`, `tests/unit/test_todo_from_main.py`
**Principle:** Testing Policy — new functionality requires tests

The core new function has five distinct error/branching paths (missing session ID, session not in DB,
no transcript, agent name fallback, empty results). Every test mocks this function entirely via
`patch(_COLLECT, ...)`. The composition logic — DB lookup, transcript path extraction, the wiring
between `extract_tool_calls_current_turn` and `_extract_turn_file_signals` — is untested.

A wiring bug (wrong attribute name, changed return signature of a dependency) would break
`from-main` in production with no test failure.

**Fix:** Add a dedicated test class for `_collect_session_touched_files` that mocks its
infrastructure dependencies (`_create_sync_engine`, `db_models.Session`,
`extract_tool_calls_current_turn`, `_extract_turn_file_signals`) rather than the function itself.
Cover at minimum: happy path, missing session ID, session not in DB, missing transcript,
empty touched files.

### IMP-4: Silent agent-name fallback hides configuration errors

**Location:** `teleclaude/todo_scaffold.py:558-561`
**Principle:** Fail Fast, Silent Failure Prevention

```python
try:
    agent_name = AgentName.from_str(get_default_agent())
except ValueError:
    agent_name = AgentName.CLAUDE
```

The `except ValueError` silently swallows two distinct failure modes: disabled/unknown agent in
config, and agent string not in the `AgentName` enum. If the actual agent is Gemini but falls
back to CLAUDE, the transcript is parsed with the wrong format. `extract_tool_calls_current_turn`
may return empty results, and the function raises a misleading "Could not determine session-touched
files" error — hiding that the real cause is agent misconfiguration.

**Fix:** At minimum, log a warning when falling back:

```python
except ValueError:
    _scaffold_logger.warning(
        "Could not resolve default agent; falling back to CLAUDE. "
        "Check config.yml agents section."
    )
    agent_name = AgentName.CLAUDE
```

### IMP-5: Transcript parse failure modes collapsed into one generic error

**Location:** `teleclaude/todo_scaffold.py:563-570`
**Principle:** Fail Fast, Diagnostics

`extract_tool_calls_current_turn` fails open — it returns `TurnTimeline(tool_calls=[], has_data=False)`
on any error (missing file, corrupt JSON, unrecognized format). The caller does not check
`timeline.has_data`, so four distinct failure modes all produce the same error message:
"Could not determine session-touched files from transcript."

The user cannot distinguish "transcript file missing" from "transcript is corrupt" from
"agent genuinely touched nothing."

**Fix:** Check `timeline.has_data` before proceeding:

```python
timeline = extract_tool_calls_current_turn(transcript_path, agent_name, full_session=True)
if not timeline.has_data:
    raise ValueError(
        f"Transcript parsing returned no data. "
        f"Verify transcript exists and is valid: {transcript_path}"
    )
touched_files, _saw_mutation = _extract_turn_file_signals(timeline, project_path)
```

## Suggestions

### SUG-1: Docstring overstates similarity to checkpoint system

**Location:** `teleclaude/todo_scaffold.py:529`

The docstring says "Uses the same transcript parsing as the checkpoint system." The checkpoint
system calls `extract_tool_calls_current_turn` with `full_session=False` (current turn only),
while this function uses `full_session=True` (all turns). The parsing primitives are shared but
the scope is deliberately broader.

**Suggestion:** "Uses the same transcript parsing primitives as the checkpoint system, but scans
the full session (not just the current turn) to capture all files this session mutated."

### SUG-2: Redundant `patch.dict` in test

**Location:** `tests/unit/test_todo_from_main.py:263`

```python
patch.dict("os.environ", {}, clear=False),  # no-op
patch.dict("os.environ", {"TELECLAUDE_SESSION_ID": ""}, clear=False),
```

The first `patch.dict` does nothing. Remove it.

### SUG-3: Misleading code comment about human authorship

**Location:** `teleclaude/todo_scaffold.py:654-655`

The comment says "The human authored these changes directly" but with session-scoped transcript
parsing, `from-main` is now explicitly designed for agent sessions (requires `TELECLAUDE_SESSION_ID`).
The marker HTML comment (`inline work delivered under human supervision`) is more accurate.

**Suggestion:** Reword to: "These changes were made directly on main (outside the normal todo
workflow) — build gates and reviewers recognize the marker and handle accordingly."

### SUG-4: Private API imports create coupling

**Location:** `teleclaude/todo_scaffold.py:540-541`

Importing `_extract_turn_file_signals` and `_create_sync_engine` (private by convention) couples
this module to implementation details of the checkpoint and receiver modules. Pragmatically justified
since these are the exact functions needed, but elevating them to public API would be cleaner.

## Lane Execution Summary

| Lane       | Executed | Findings                                                                         |
| ---------- | -------- | -------------------------------------------------------------------------------- |
| code       | Yes      | IMP-1                                                                            |
| paradigm   | Yes      | No findings — reuses existing infrastructure patterns                            |
| principles | Yes      | IMP-1, IMP-4, IMP-5 (fail-fast)                                                  |
| security   | Yes      | No findings — no secrets, injection, or info leakage                             |
| tests      | Yes      | IMP-2, IMP-3                                                                     |
| errors     | Yes      | IMP-4 (silent fallback), IMP-5 (collapsed failure modes)                         |
| types      | Yes      | No findings — `set[str]` return type correct, `type: ignore[arg-type]` justified |
| comments   | Yes      | SUG-1, SUG-3                                                                     |
| logging    | Yes      | IMP-4 (missing warning log on agent fallback)                                    |
| simplify   | Yes      | No findings                                                                      |

## Resolved During Review

- **IMP-1:** Replaced `getattr(row, "native_log_file", None)` with direct attribute access
  `row.native_log_file` in `teleclaude/todo_scaffold.py:554`.
- **IMP-2:** Added `test_no_intersection_between_session_and_status_raises` — verifies ValueError
  when session-touched files don't overlap with git status.
- **IMP-3:** Added `TestCollectSessionTouchedFiles` class with 6 direct unit tests covering:
  happy path, missing session ID, session not in DB, missing transcript, empty timeline
  (new `has_data` check), and no touched files.
- **IMP-4:** Added `_scaffold_logger.warning()` when agent name fallback to CLAUDE occurs.
- **IMP-5:** Added `timeline.has_data` check before `_extract_turn_file_signals`, producing
  a differentiated error message for transcript parse failures vs empty file results.

## Verdict: APPROVE

0 unresolved Critical findings. 0 unresolved Important findings.
All 5 Important findings resolved during review (inline fixes + tests).

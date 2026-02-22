# Bug Delivery Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fire-and-forget bug pipeline — `telec bugs report` captures a bug, dispatches an autonomous orchestrator that fixes, reviews, and merges via PR.

**Architecture:** Bugs are todos with a `bug.md` file instead of `input.md`. The `next-work` state machine detects `bug.md`, skips the prepare phase, and dispatches a fix worker (with debugger skill) instead of a build worker. Finalize deletes the todo directory instead of archiving. A new `telec bugs` CLI command handles intake and listing.

**Tech Stack:** Python (Pydantic, asyncio), YAML, Markdown templates, telec CLI, next-machine state machine, agent command artifacts.

---

### Task 1: bug.md Template

**Files:**

- Create: `templates/todos/bug.md`

**Step 1: Create the template**

```markdown
# Bug: {description}

## Symptom

{description}

## Discovery Context

Reported by: {reporter}
Session: {session_id}
Date: {date}

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
```

**Step 2: Commit**

```bash
git add templates/todos/bug.md
git commit -m "feat(bugs): add bug.md template"
```

---

### Task 2: Bug Scaffold Function

**Files:**

- Modify: `teleclaude/todo_scaffold.py`
- Create: `tests/unit/test_bug_scaffold.py`

**Step 1: Write the failing test**

```python
# tests/unit/test_bug_scaffold.py
"""Tests for bug todo scaffolding."""

from pathlib import Path

import pytest

from teleclaude.todo_scaffold import create_bug_skeleton


def test_create_bug_skeleton_creates_bug_md(tmp_path: Path) -> None:
    """Bug skeleton creates bug.md with symptom filled in."""
    # Create templates directory structure that the function expects
    result = create_bug_skeleton(
        project_root=tmp_path,
        slug="fix-double-fire",
        description="Session hook fires twice on reconnect",
        reporter="claude",
        session_id="abc-123",
    )
    bug_md = result / "bug.md"
    assert bug_md.exists()
    content = bug_md.read_text()
    assert "Session hook fires twice on reconnect" in content
    assert "claude" in content
    assert "abc-123" in content


def test_create_bug_skeleton_creates_state_json_at_build_phase(tmp_path: Path) -> None:
    """Bug state.json starts at in_progress phase with build pending."""
    import json

    result = create_bug_skeleton(
        project_root=tmp_path,
        slug="fix-double-fire",
        description="Session hook fires twice",
    )
    state = json.loads((result / "state.json").read_text())
    assert state["phase"] == "in_progress"
    assert state["build"] == "pending"
    assert state["review"] == "pending"


def test_create_bug_skeleton_does_not_create_requirements_or_plan(tmp_path: Path) -> None:
    """Bug skeleton does not create prepare-phase artifacts."""
    result = create_bug_skeleton(
        project_root=tmp_path,
        slug="fix-something",
        description="Something broke",
    )
    assert not (result / "requirements.md").exists()
    assert not (result / "implementation-plan.md").exists()
    assert not (result / "quality-checklist.md").exists()
    assert not (result / "input.md").exists()


def test_create_bug_skeleton_rejects_existing_dir(tmp_path: Path) -> None:
    """Raises if todo directory already exists."""
    (tmp_path / "todos" / "fix-dup").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        create_bug_skeleton(tmp_path, "fix-dup", "duplicate")


def test_create_bug_skeleton_rejects_invalid_slug(tmp_path: Path) -> None:
    """Rejects slugs that don't match the pattern."""
    with pytest.raises(ValueError, match="Invalid slug"):
        create_bug_skeleton(tmp_path, "Fix Bad Slug!", "bad")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_bug_scaffold.py -v`
Expected: FAIL with ImportError (create_bug_skeleton not defined)

**Step 3: Implement create_bug_skeleton**

Add to `teleclaude/todo_scaffold.py` after `create_todo_skeleton`:

```python
_BUG_STATE = TodoState(
    phase="in_progress",
    build="pending",
    review="pending",
    deferrals_processed=False,
    breakdown=BreakdownState(assessed=False, todos=[]),
    dor=None,
    review_round=0,
    max_review_rounds=3,
    review_baseline_commit="",
    unresolved_findings=[],
    resolved_findings=[],
).model_dump()


def create_bug_skeleton(
    project_root: Path,
    slug: str,
    description: str,
    *,
    reporter: str = "manual",
    session_id: str = "none",
) -> Path:
    """Create a bug todo skeleton — no prepare artifacts, starts at build phase."""
    slug = slug.strip()
    if not slug:
        raise ValueError("Slug is required")
    if not SLUG_PATTERN.match(slug):
        raise ValueError("Invalid slug. Use lowercase letters, numbers, and hyphens only")

    todos_root = project_root / "todos"
    todo_dir = todos_root / slug

    if todo_dir.exists():
        raise FileExistsError(f"Todo already exists: {todo_dir}")

    from datetime import datetime, timezone

    bug_content = _read_template("bug.md").format(
        description=description,
        reporter=reporter,
        session_id=session_id,
        date=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    state_content = json.dumps(_BUG_STATE, indent=2) + "\n"

    _write_file(todo_dir / "bug.md", bug_content)
    _write_file(todo_dir / "state.json", state_content)

    return todo_dir
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_bug_scaffold.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add teleclaude/todo_scaffold.py tests/unit/test_bug_scaffold.py
git commit -m "feat(bugs): add create_bug_skeleton scaffold function"
```

---

### Task 3: CLI Command — `telec bugs report` and `telec bugs list`

**Files:**

- Modify: `teleclaude/cli/telec.py` (add BUGS enum, CLI_SURFACE entry, handlers)

**Step 1: Add the BUGS command to TelecCommand enum**

At `teleclaude/cli/telec.py:43`, add `BUGS = "bugs"` to the enum.

**Step 2: Add CLI_SURFACE entry**

After the `"todo"` entry (line 143), add:

```python
"bugs": CommandDef(
    desc="Manage bug reports and fixes",
    subcommands={
        "report": CommandDef(
            desc="Report a bug and dispatch autonomous fix",
            args="<description>",
            flags=[
                Flag("--slug", desc="Override auto-generated slug"),
                _PROJECT_ROOT_LONG,
            ],
        ),
        "list": CommandDef(
            desc="List in-flight bug fixes",
            flags=[_PROJECT_ROOT_LONG],
        ),
    },
),
```

**Step 3: Add handler dispatch**

In `_handle_cli_command()` around line 706, add:

```python
elif cmd_enum is TelecCommand.BUGS:
    _handle_bugs(args)
```

**Step 4: Implement `_handle_bugs`, `_handle_bugs_report`, `_handle_bugs_list`**

```python
def _handle_bugs(args: list[str]) -> None:
    """Handle telec bugs commands."""
    if not args:
        print(_usage("bugs"))
        return

    subcommand = args[0]
    if subcommand == "report":
        _handle_bugs_report(args[1:])
    elif subcommand == "list":
        _handle_bugs_list(args[1:])
    else:
        print(f"Unknown bugs subcommand: {subcommand}")
        print(_usage("bugs"))
        raise SystemExit(1)


def _handle_bugs_report(args: list[str]) -> None:
    """Handle telec bugs report <description> [--slug <slug>]."""
    from teleclaude.todo_scaffold import create_bug_skeleton

    project_root = Path.cwd()
    slug_override: str | None = None
    description_parts: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            slug_override = args[i + 1]
            i += 2
        elif arg == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "report"))
            raise SystemExit(1)
        else:
            description_parts.append(arg)
            i += 1

    description = " ".join(description_parts).strip()
    if not description:
        print("Error: description is required")
        print(_usage("bugs", "report"))
        raise SystemExit(1)

    # Auto-generate slug from description if not provided
    if slug_override:
        slug = slug_override
    else:
        import re
        slug = "fix-" + re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")[:60]

    try:
        todo_dir = create_bug_skeleton(
            project_root=project_root,
            slug=slug,
            description=description,
        )
    except (ValueError, FileExistsError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)

    print(f"Bug reported: {slug}")
    print(f"  {todo_dir}")
    # TODO: Task 6 will add worktree creation and orchestrator dispatch here


def _handle_bugs_list(args: list[str]) -> None:
    """Handle telec bugs list — show in-flight bug fixes."""
    import json

    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)
        else:
            i += 1

    todos_dir = project_root / "todos"
    if not todos_dir.exists():
        print("No bugs in flight.")
        return

    bugs: list[tuple[str, str]] = []
    for entry in sorted(todos_dir.iterdir()):
        if entry.is_dir() and (entry / "bug.md").exists():
            state_file = entry / "state.json"
            status = "unknown"
            if state_file.exists():
                state = json.loads(state_file.read_text())
                build = state.get("build", "pending")
                review = state.get("review", "pending")
                if review == "approved":
                    status = "approved"
                elif review in ("started", "changes_requested"):
                    status = "reviewing"
                elif build == "complete":
                    status = "reviewing"
                elif build == "started":
                    status = "building"
                else:
                    status = "pending"
            bugs.append((entry.name, status))

    if not bugs:
        print("No bugs in flight.")
        return

    for slug, status in bugs:
        print(f"  {slug:<40} {status}")
```

**Step 5: Commit**

```bash
git add teleclaude/cli/telec.py
git commit -m "feat(bugs): add telec bugs report and list CLI commands"
```

---

### Task 4: State Machine — Bug Detection in next-work

**Files:**

- Modify: `teleclaude/core/next_machine/core.py`
- Create: `tests/unit/test_bug_state_machine.py`

This is the critical integration. The `next_work()` function at line 2004-2020 checks for `requirements.md` and `implementation-plan.md`. For bugs, we skip that check when `bug.md` exists, and dispatch `next-bugs-fix` instead of `next-build`.

**Step 1: Write the failing test**

```python
# tests/unit/test_bug_state_machine.py
"""Tests for bug detection in the next-work state machine."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.next_machine.core import is_bug_todo


def test_is_bug_todo_true_when_bug_md_exists(tmp_path: Path) -> None:
    """Detects bug todo by bug.md presence."""
    todo_dir = tmp_path / "todos" / "fix-something"
    todo_dir.mkdir(parents=True)
    (todo_dir / "bug.md").write_text("# Bug")
    assert is_bug_todo(str(tmp_path), "fix-something") is True


def test_is_bug_todo_false_when_no_bug_md(tmp_path: Path) -> None:
    """Regular todo without bug.md is not a bug."""
    todo_dir = tmp_path / "todos" / "some-feature"
    todo_dir.mkdir(parents=True)
    (todo_dir / "requirements.md").write_text("# Req")
    assert is_bug_todo(str(tmp_path), "some-feature") is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_bug_state_machine.py -v`
Expected: FAIL with ImportError

**Step 3: Add `is_bug_todo` helper**

In `teleclaude/core/next_machine/core.py`, near the other file-checking helpers (around `check_file_exists`):

```python
def is_bug_todo(cwd: str, slug: str) -> bool:
    """Check if a todo is a bug (has bug.md instead of requirements.md)."""
    return check_file_exists(cwd, f"todos/{slug}/bug.md")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_bug_state_machine.py -v`
Expected: PASS

**Step 5: Modify next_work() precondition check**

At `teleclaude/core/next_machine/core.py:2004-2020`, replace the precondition block:

```python
    # 3. Validate preconditions
    precondition_root = cwd
    worktree_path = Path(cwd) / "trees" / resolved_slug
    if (
        worktree_path.exists()
        and (worktree_path / "todos" / resolved_slug / "requirements.md").exists()
        and (worktree_path / "todos" / resolved_slug / "implementation-plan.md").exists()
    ):
        precondition_root = str(worktree_path)

    # Bug todos skip prepare-phase artifact checks
    is_bug = await asyncio.to_thread(is_bug_todo, precondition_root, resolved_slug)
    if not is_bug:
        # Only check for worktree preconditions if not checked above
        if precondition_root == cwd:
            is_bug = await asyncio.to_thread(is_bug_todo, cwd, resolved_slug)

    if not is_bug:
        has_requirements = check_file_exists(precondition_root, f"todos/{resolved_slug}/requirements.md")
        has_impl_plan = check_file_exists(precondition_root, f"todos/{resolved_slug}/implementation-plan.md")
        if not (has_requirements and has_impl_plan):
            return format_error(
                "NOT_PREPARED",
                f"todos/{resolved_slug} is missing requirements or implementation plan.",
                next_call=f'Call teleclaude__next_prepare(slug="{resolved_slug}") to complete preparation.',
            )
```

**Step 6: Modify build dispatch to use next-bugs-fix for bugs**

At `teleclaude/core/next_machine/core.py:2052-2067`, modify the build dispatch:

```python
    # 7. Check build status (from state.json in worktree)
    if not await asyncio.to_thread(is_build_complete, worktree_cwd, resolved_slug):
        await asyncio.to_thread(
            mark_phase, worktree_cwd, resolved_slug, PhaseName.BUILD.value, PhaseStatus.STARTED.value
        )
        try:
            guidance = await compose_agent_guidance(db)
        except RuntimeError as exc:
            return format_error("NO_AGENTS", str(exc))

        # Bug todos dispatch fix worker instead of build worker
        is_bug = await asyncio.to_thread(is_bug_todo, worktree_cwd, resolved_slug)
        command = "next-bugs-fix" if is_bug else "next-build"

        return format_tool_call(
            command=command,
            args=resolved_slug,
            project=cwd,
            guidance=guidance,
            subfolder=f"trees/{resolved_slug}",
            next_call=f'teleclaude__next_work(slug="{resolved_slug}")',
        )
```

**Step 7: Add POST_COMPLETION entry for next-bugs-fix**

In the `POST_COMPLETION` dict (line 81), add:

```python
    "next-bugs-fix": """WHEN WORKER COMPLETES:
1. Read worker output via get_session_data
2. teleclaude__end_session(computer="local", session_id="<session_id>")
3. teleclaude__mark_phase(slug="{args}", phase="build", status="complete")
4. Create PR if not already created:
   gh pr create --head fix/{args} --base main --title "fix: {args}" --body "Automated bug fix"
5. Call {next_call}
""",
```

**Step 8: Commit**

```bash
git add teleclaude/core/next_machine/core.py tests/unit/test_bug_state_machine.py
git commit -m "feat(bugs): detect bug.md in next-work, dispatch fix worker"
```

---

### Task 5: Bug Fix Worker Command

**Files:**

- Create: `agents/commands/next-bugs-fix.md`

**Step 1: Create the agent command**

```markdown
---
argument-hint: '[slug]'
description: Worker command - investigate and fix a bug using systematic debugging
---

# Bug Fix

You are now the Bug Fixer.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/bugs-handling.md
- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/policy/version-control-safety.md

## Required skills

Load the `superpowers:systematic-debugging` skill before starting work.

## Purpose

Investigate and fix the bug described in `todos/{slug}/bug.md`.

## Inputs

- Slug: "$ARGUMENTS"
- Worktree for the slug
- `todos/{slug}/bug.md` — the bug report (your requirement)

## Outputs

- Bug fixed and committed
- `bug.md` updated with Investigation, Root Cause, and Fix Applied sections
- Report format:
```

BUILD COMPLETE: {slug}

Bug: {symptom summary}
Root cause: {one-line root cause}
Fix: {one-line fix summary}
Commits made: {count}
Tests: PASSING
Lint: PASSING

Ready for review.

```

## Steps

1. Read `todos/{slug}/bug.md` to understand the symptom.
2. Load the `superpowers:systematic-debugging` skill.
3. Investigate the bug — trace the code path, reproduce if possible, identify root cause.
4. Update `bug.md` with your investigation findings and root cause.
5. Apply the minimal fix. Prefer the smallest change that resolves the symptom.
6. Verify: tests passing, lint passing.
7. Update `bug.md` with the fix applied section.
8. Commit all changes (bug.md updates + code fix).
9. Do not stop with uncommitted changes.
10. End with: `Ready for review.`
```

**Step 2: Run `telec sync` to distribute the artifact**

Run: `telec sync`
Expected: Artifact compiled and distributed.

**Step 3: Commit**

```bash
git add agents/commands/next-bugs-fix.md
git commit -m "feat(bugs): add next-bugs-fix worker command"
```

---

### Task 6: Bug Review — Teach Reviewer to Use bug.md

**Files:**

- Modify: `agents/commands/next-review.md`

**Step 1: Add bug.md fallback to the review command**

Add to the Steps section of `agents/commands/next-review.md`:

```markdown
- If `todos/{slug}/bug.md` exists (bug fix review):
  - Use `bug.md` as the requirement source instead of `requirements.md`.
  - Verify the fix addresses the symptom described in bug.md.
  - Verify the root cause analysis is sound.
  - Verify the fix is minimal and doesn't introduce regressions.
  - Skip implementation-plan.md checks (bugs don't have one).
```

**Step 2: Run `telec sync`**

Run: `telec sync`

**Step 3: Commit**

```bash
git add agents/commands/next-review.md
git commit -m "feat(bugs): teach reviewer to use bug.md as requirement source"
```

---

### Task 7: Bug Finalize — Delete Instead of Archive

**Files:**

- Modify: `teleclaude/core/next_machine/core.py` (POST_COMPLETION for next-finalize)

**Step 1: Modify the finalize POST_COMPLETION**

The current `next-finalize` POST_COMPLETION (line 107) includes `rm -rf todos/{args}` as step 3c, which already deletes the todo directory. However, it also calls `deliver_to_delivered()` during finalize. For bugs, we need to skip the delivery log.

Modify the finalize step in `next_work()` (around line 2128-2147) to pass a flag or note indicating it's a bug:

```python
    # 9. Review approved - dispatch finalize
    is_bug = await asyncio.to_thread(is_bug_todo, worktree_cwd, resolved_slug)
    # ... existing lock acquisition code ...
    return format_tool_call(
        command="next-finalize",
        args=resolved_slug,
        project=cwd,
        guidance=guidance,
        subfolder=f"trees/{resolved_slug}",
        next_call="teleclaude__next_work()",
        note="BUG FIX: Skip deliver_to_delivered — delete todo directory after merge. No delivery log entry." if is_bug else "",
    )
```

**Step 2: Commit**

```bash
git add teleclaude/core/next_machine/core.py
git commit -m "feat(bugs): skip delivery log for bug fixes in finalize"
```

---

### Task 8: Bug Dispatcher — Worktree + Orchestrator Launch

**Files:**

- Modify: `teleclaude/cli/telec.py` (`_handle_bugs_report`)

This is the final wiring: after creating the bug scaffold, create the branch, worktree, and dispatch an orchestrator session.

**Step 1: Extend `_handle_bugs_report` to dispatch**

Replace the TODO comment in `_handle_bugs_report` with:

```python
    # Create branch and worktree
    import subprocess

    branch_name = slug
    try:
        subprocess.run(
            ["git", "branch", branch_name, "main"],
            cwd=str(project_root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "worktree", "add", f"trees/{slug}", branch_name],
            cwd=str(project_root),
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        print(f"Error creating worktree: {exc.stderr.decode().strip()}")
        raise SystemExit(1)

    # Sync bug.md and state.json to worktree
    import shutil
    worktree_todo = project_root / "trees" / slug / "todos" / slug
    worktree_todo.mkdir(parents=True, exist_ok=True)
    shutil.copy2(todo_dir / "bug.md", worktree_todo / "bug.md")
    shutil.copy2(todo_dir / "state.json", worktree_todo / "state.json")

    # Dispatch orchestrator
    print(f"Worktree: trees/{slug}")
    print(f"Branch: {branch_name}")
    print("Dispatching orchestrator...")

    api = TelecAPIClient()
    try:
        result = asyncio.run(api.request(
            "POST",
            "/sessions/start",
            json={
                "agent": "claude",
                "project_path": str(project_root),
                "title": f"Bug fix: {slug}",
                "thinking_mode": "slow",
                "message": (
                    f"You are the orchestrator for bug fix '{slug}'. "
                    f"Run: teleclaude__next_work(slug=\"{slug}\") and follow the output verbatim. "
                    f"Continue calling next_work after each phase completes until finalize is done."
                ),
            },
        ))
        session_id = result.get("session_id", "unknown")
        print(f"Orchestrator session: {session_id}")
        print("Bug dispatched. Fix in progress.")
    except Exception as exc:
        print(f"Warning: Could not dispatch orchestrator: {exc}")
        print("Bug scaffold created. Run next-work manually to proceed.")
```

**Step 2: Commit**

```bash
git add teleclaude/cli/telec.py
git commit -m "feat(bugs): dispatch orchestrator from telec bugs report"
```

---

### Task 9: Readiness Gate Bypass for Bugs

**Files:**

- Modify: `teleclaude/core/next_machine/core.py`

Bugs skip the roadmap entirely, so `next_work()` needs to handle slug resolution for bugs that aren't in `roadmap.yaml`.

**Step 1: Modify slug validation in next_work**

At line 1953, the state machine checks `slug_in_roadmap()`. For bugs (explicit slug with `bug.md`), bypass this check:

```python
    if slug:
        # Bug todos bypass roadmap requirement
        is_bug = await asyncio.to_thread(is_bug_todo, cwd, slug)
        if not is_bug and not await asyncio.to_thread(slug_in_roadmap, cwd, slug):
            return format_error(
                "NOT_PREPARED",
                f"Item '{slug}' not found in roadmap.",
                next_call="Check todos/roadmap.yaml or call teleclaude__next_prepare().",
            )
```

Also bypass the DOR/readiness check at line 1961 for bugs (they start at `in_progress`, not `pending`).

And bypass dependency checks at line 1971 for bugs (they have no dependencies).

**Step 2: Commit**

```bash
git add teleclaude/core/next_machine/core.py
git commit -m "feat(bugs): bypass roadmap and DOR gates for bug todos"
```

---

### Task 10: Verification and Integration Test

**Files:**

- Modify: `tests/unit/test_bug_scaffold.py` (add integration-level checks)

**Step 1: Run the full test suite**

Run: `make test`
Expected: All tests pass.

**Step 2: Run lint and type checks**

Run: `make lint`
Expected: No errors.

**Step 3: Manual smoke test**

Run: `telec bugs report "test bug description" --slug fix-test-bug`
Expected: Creates `todos/fix-test-bug/bug.md` + `state.json`, creates worktree, dispatches orchestrator.

Run: `telec bugs list`
Expected: Shows `fix-test-bug` with status.

**Step 4: Clean up test artifacts**

```bash
rm -rf todos/fix-test-bug trees/fix-test-bug
git branch -D fix-test-bug 2>/dev/null
```

**Step 5: Final commit**

```bash
git add -A
git commit -m "test(bugs): verify bug delivery pipeline end-to-end"
```

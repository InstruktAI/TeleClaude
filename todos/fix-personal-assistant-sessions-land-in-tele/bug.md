# Bug: Personal assistant sessions land in ~/.teleclaude/people/{name}/workspace/ instead of directly in ~/.teleclaude/people/{name}/. The workspace subfolder is unnecessary indirection — the person's folder IS where their personal agent lives. scaffold_personal_workspace() in invite.py creates this extra folder and symlinks AGENTS.master.md into it. Fix: sessions should land in the person's folder directly. The AGENTS.master.md already lives there. Remove the workspace subfolder concept from scaffold_personal_workspace(), update all callers in telegram_adapter.py and discord_adapter.py to use the person folder directly.

## Symptom

Personal assistant sessions land in ~/.teleclaude/people/{name}/workspace/ instead of directly in ~/.teleclaude/people/{name}/. The workspace subfolder is unnecessary indirection — the person's folder IS where their personal agent lives. scaffold_personal_workspace() in invite.py creates this extra folder and symlinks AGENTS.master.md into it. Fix: sessions should land in the person's folder directly. The AGENTS.master.md already lives there. Remove the workspace subfolder concept from scaffold_personal_workspace(), update all callers in telegram_adapter.py and discord_adapter.py to use the person folder directly.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-02

## Investigation

`scaffold_personal_workspace()` in `teleclaude/invite.py` (line 110) constructs
`workspace_path = _PEOPLE_DIR / person_name / "workspace"` and returns that path.

Both callers — `telegram_adapter.py` (lines 416, 490) and `discord_adapter.py`
(lines 1812, 1886) — pass this path directly as `project_path` to `CreateSessionCommand`,
so every personal-assistant session lands in `~/.teleclaude/people/{name}/workspace/`
instead of `~/.teleclaude/people/{name}/`.

The function also symlinks/copies `AGENTS.master.md` from the person folder into the
workspace subfolder — unnecessary indirection because the file already lives in the
person folder.

## Root Cause

`scaffold_personal_workspace()` creates and returns a `workspace/` subfolder under the
person's directory. The person's folder *is* the workspace — there is no need for the
extra level.

## Fix Applied

Changed `scaffold_personal_workspace()` to return `_PEOPLE_DIR / person_name` directly:

- Removed the `workspace` subfolder construction.
- Removed the symlink/copy logic for `AGENTS.master.md` (the file already lives in the
  person folder; a fallback writer creates a default if absent).
- Kept the `teleclaude.yml` creation, now targeting the person folder directly.

No caller changes needed — all four call sites already use the returned path as
`project_path` without further manipulation.

New test file: `tests/unit/test_invite_scaffold.py` — six tests covering the return
path, folder creation, default file creation, no-overwrite guard, and absence of the
removed `workspace/` subfolder.

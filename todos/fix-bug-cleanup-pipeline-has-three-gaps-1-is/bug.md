# Bug: Bug cleanup pipeline has three gaps: (1) _is_bug_slug() in state_machine.py:400-402 checks wrong path todos/bugs/{slug}/bug.md instead of todos/{slug}/bug.md — always returns False. (2) telec roadmap deliver fails for items not in roadmap.yaml — should work for any todo: clean up the todo dir, optionally record in delivered.yaml, skip roadmap removal if not present. (3) telec todo remove requires roadmap entry — should be best-effort: remove todo directory, remove roadmap entry if present, remove worktree+branch if present, never fail just because one artifact is missing. Bugs are intentionally NOT added to roadmap — they are picked up immediately by orchestrators. The fix is to make deliver and remove robust for items that exist only as todo directories.

## Symptom

Bug cleanup pipeline has three gaps: (1) _is_bug_slug() in state_machine.py:400-402 checks wrong path todos/bugs/{slug}/bug.md instead of todos/{slug}/bug.md — always returns False. (2) telec roadmap deliver fails for items not in roadmap.yaml — should work for any todo: clean up the todo dir, optionally record in delivered.yaml, skip roadmap removal if not present. (3) telec todo remove requires roadmap entry — should be best-effort: remove todo directory, remove roadmap entry if present, remove worktree+branch if present, never fail just because one artifact is missing. Bugs are intentionally NOT added to roadmap — they are picked up immediately by orchestrators. The fix is to make deliver and remove robust for items that exist only as todo directories.

## Detail

Three fixes needed: (A) state_machine.py:400 fix path from todos/bugs/{slug}/bug.md to todos/{slug}/bug.md. (B) deliver_to_delivered() in core.py:2166 should not require roadmap entry — if slug not in roadmap, still record in delivered.yaml and clean up todo dir. (C) remove_todo in telec.py should be best-effort — remove whatever exists (dir, roadmap entry, worktree, branch) without failing if any subset is missing.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-11

## Investigation

Traced each of the three reported gaps to their exact locations:

(A) `teleclaude/core/integration/state_machine.py:402` — `_is_bug_slug()` constructs
`todos/bugs/{slug}/bug.md` but bugs live at `todos/{slug}/bug.md`. No bug.md at the wrong
path ever exists, so this always returns False, causing the integration machine to call
`deliver_to_delivered` on every bug slug. That call then fails because bugs are not in
the roadmap, producing the warning at line 937.

(B) `teleclaude/core/next_machine/core.py:2172-2176` — `deliver_to_delivered()` returns
False when the slug is absent from roadmap.yaml and not already in delivered.yaml. Since
bugs intentionally skip the roadmap, this gate always rejects them. The function had no
path to accept a slug that exists only as a todo directory.

(C) `teleclaude/todo_scaffold.py:280-286` — `remove_todo()` raises `RuntimeError` when
`trees/{slug}/` exists, telling the caller to remove the worktree manually first. Bug fix
slugs always have an active worktree (that IS the working context), so this guard makes
cleanup impossible through the standard CLI command.

## Root Cause

Three independent defects, each blocking a different stage of bug cleanup:

1. **Wrong path in `_is_bug_slug()`:** `todos/bugs/{slug}` should be `todos/{slug}`.
2. **`deliver_to_delivered()` requires roadmap entry:** No code path handled slugs that
   exist only as a `todos/{slug}/` directory (the bug case).
3. **`remove_todo()` refuses on worktree presence:** Should remove the worktree/branch
   instead of refusing to proceed.

## Fix Applied

`teleclaude/core/integration/state_machine.py`:
- `_is_bug_slug`: changed path from `todos/bugs/{slug}/bug.md` to `todos/{slug}/bug.md`.

`teleclaude/core/next_machine/core.py`:
- `deliver_to_delivered`: when slug is not in roadmap and not already delivered, check if
  `todos/{slug}/` directory exists; if so, proceed to record in delivered.yaml instead of
  returning False. Moved `save_roadmap` into the `else` branch so it only runs when an
  entry was actually removed.

`teleclaude/todo_scaffold.py`:
- `remove_todo`: removed the `RuntimeError` guard on worktree presence. Instead,
  proactively removes the worktree with `git worktree remove --force` and the local
  branch with `git branch -D` (both best-effort/non-fatal). Added `found_worktree` to
  the "anything found" check so a worktree-only slug is recognised as valid.

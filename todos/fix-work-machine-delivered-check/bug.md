# Bug: telec todo work returns ITEM_NOT_READY for delivered slugs when state.yaml is missing — get_item_phase defaults to pending instead of checking delivered.yaml first

## Symptom

telec todo work returns ITEM_NOT_READY for delivered slugs when state.yaml is missing — get_item_phase defaults to pending instead of checking delivered.yaml first

## Detail

When the integrator delivers a slug and cleans up the todo folder (deleting state.yaml), get_item_phase in slug_resolution.py falls through to ItemPhase.PENDING because state.get('phase') returns None on missing file. The DONE check at line 297 of work.py never fires because phase is never 'done'. Fix: check delivered.yaml in get_item_phase (or \_validate_explicit_slug_readiness) before falling back to pending. If slug is in delivered.yaml, return DONE immediately.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-20

## Investigation

Traced the call chain from `telec todo work` → `_validate_explicit_slug_readiness` → `get_item_phase`.

`get_item_phase` calls `read_phase_state(cwd, slug)` first. When `state.yaml` is missing (deleted
after delivery), `read_phase_state` returns `default_state()` — a `TodoState` model dump that
always includes `phase = "pending"`. The subsequent check `isinstance(phase, str)` is therefore
always True for a missing state file, returning `"pending"` immediately and making the
`delivered.yaml` / `roadmap.yaml` cross-check unreachable dead code.

A prior fix attempt (commit `5dca8c4ab`) added the delivered.yaml check but placed it AFTER the
`isinstance(phase, str)` guard — so it was never reached. The check in the commit message and
docstring ("when state.yaml has no phase") was incorrect; the default state always has a phase.

Reproduction test: `test_get_item_phase_returns_done_for_delivered_slug_with_no_state_yaml`
confirmed the bug: `get_item_phase` returned `"pending"` instead of `"done"` for a slug in
`delivered.yaml` with no `state.yaml` present.

## Root Cause

`get_item_phase` read `state.yaml` (getting the `"pending"` default) before checking
`delivered.yaml`. Since `default_state()` always populates `phase = "pending"`, the
`isinstance(phase, str)` early-return fired before the delivered.yaml check, making the
DONE path unreachable for delivered slugs with cleaned-up `state.yaml`.

## Fix Applied

Moved the `delivered.yaml` / `roadmap.yaml` checks to the TOP of `get_item_phase`, before
reading `state.yaml`. Delivered slugs now return `ItemPhase.DONE` immediately. The
`state.yaml` read is only reached for non-delivered slugs (the common path, unchanged).

Two regression tests added to `tests/unit/core/next_machine/test_slug_resolution.py`:

- `test_get_item_phase_returns_done_for_delivered_slug_with_no_state_yaml` — was RED, now GREEN.
- `test_get_item_phase_raises_on_slug_in_both_delivered_and_roadmap` — was RED, now GREEN.

Additional fixes in the same commit set (pre-existing failures exposed):

- `teleclaude/memory/search.py`, `store.py`, `context/builder.py`: tests patched
  `create_engine` to return a URL string; `engine.dispose()` was added later and
  broke the tests. Fixed by patching `create_engine` to return `MagicMock()`.
- `teleclaude/hooks/receiver/_session.py`: pylint `invalid-name` and `global-statement`
  warnings suppressed with inline disable comments.
- `teleclaude/memory/search.py`: two lines exceeding the 120-char limit split.
- `tests/unit/install/test_git_wrapper_permissions.py`: test file tried to import the git
  wrapper as Python after it was rewritten to bash. Rewritten to use subprocess with a fake
  git binary; CWD-restriction tests (Python-only behavior) removed.

# Review Findings: fix-personal-assistant-sessions-land-in-tele

## Summary

Bug fix review. The implementation addresses the symptom exactly as described in `bug.md`.

## Findings

### Critical
_(none)_

### Important
_(none)_

### Suggestions
_(none)_

## Why No Issues

**Paradigm-fit verification:**
- `scaffold_personal_workspace()` follows the established pattern of using `_PEOPLE_DIR` as the root and constructing paths relative to it — no filesystem hacks or hardcoded paths.
- All four call sites in `telegram_adapter.py` and `discord_adapter.py` consume the returned `Path` as `project_path` without further manipulation; no adapter-layer changes were needed.
- Tests use `monkeypatch.setattr` to inject a `tmp_path`-backed `_PEOPLE_DIR`, consistent with the project's existing fixture patterns.

**Requirements verification:**
- Symptom: sessions landed in `~/.teleclaude/people/{name}/workspace/`. Fixed: `scaffold_personal_workspace()` now returns `_PEOPLE_DIR / person_name` directly.
- Root cause (symlink/copy indirection and extra subfolder): removed entirely.
- Callers verified unchanged — all four sites pass the return value directly to `CreateSessionCommand(project_path=...)`.
- Fallback `AGENTS.master.md` writer is correct and idempotent.
- `teleclaude.yml` creation is preserved at the correct level.

**Copy-paste duplication check:**
- New test file is not a copy of any existing test file; it is purpose-built for `scaffold_personal_workspace`.
- No duplication found in the implementation change.

**`test_inbound_queue.py` change:**
- The poll-loop replacement for `asyncio.sleep(0.3)` is a pre-existing flakiness fix included in this branch (noted in the diff). It does not affect the bug fix scope and is a clear correctness improvement.

**Manual verification note:**
- Runtime path correction cannot be observed in the review environment (requires a live Telegram/Discord session). The unit tests cover the path-return contract directly and are sufficient proof of the fix. The call-site audit confirms no session-creation code was left behind that still references the old `workspace/` subfolder.

## Verdict

**APPROVE**

# Review Findings: discord-slash-commands-like-telegram

## Critical

- `/cancel` is not thread-scoped and can interrupt a session from a non-thread forum channel.
  - Requirement mismatch: `/cancel` must work in session threads only and return an ephemeral error outside session threads.
  - Code path: [`teleclaude/adapters/discord_adapter.py:1847`](teleclaude/adapters/discord_adapter.py:1847) + channel-level fallback in [`teleclaude/adapters/discord_adapter.py:1783`](teleclaude/adapters/discord_adapter.py:1783).
  - Concrete trace: with `interaction.channel.id=600` (non-thread forum channel) and `_find_session` returning a session, `_handle_cancel_slash` sends `"Sent CTRL+C"` and dispatches `KeysCommand(key="cancel")` instead of rejecting context.
  - Risk: users can interrupt the wrong session from outside its thread.
  - Fix: add an explicit non-thread guard in `_handle_cancel_slash` before lookup (`No active session in this thread.`), and avoid channel-level fallback for this slash path.

## Important

- Launcher lifecycle does not pin the launcher message.
  - Requirement mismatch: success criteria requires a pinned launcher message in project forums.
  - Code path: launcher create/update only edits/sends and stores message ID in [`teleclaude/adapters/discord_adapter.py:465`](teleclaude/adapters/discord_adapter.py:465); no `pin()` call exists in launcher flow.
  - Risk: launcher discoverability and persistence expectations are not met.
  - Fix: pin on create/update (with permission-safe error handling) and add a regression test.

- Test coverage misses the thread-only `/cancel` contract and launcher pinning behavior.
  - Existing tests validate only "session found/not found" outcomes without enforcing thread context: [`tests/unit/test_discord_adapter.py:1427`](tests/unit/test_discord_adapter.py:1427), [`tests/unit/test_discord_adapter.py:1443`](tests/unit/test_discord_adapter.py:1443).
  - No launcher pin behavior assertion exists in the new launcher lifecycle tests.
  - Risk: the two requirement regressions above can pass unit tests undetected.
  - Fix: add tests for non-thread `/cancel` rejection and message pin/update pin behavior.

## Suggestions

- Manual verification gap: Discord UI behavior (button interactions in real forums, slash registration visibility, and persistence after daemon restart) was not validated against a live Discord guild in this review environment.

## Paradigm-Fit Assessment

- Data flow: implementation mostly follows existing adapter boundaries (`CreateSessionCommand`, `KeysCommand`, command service dispatch) without bypassing core data paths.
- Component reuse: launcher and slash flows are integrated into existing `DiscordAdapter` lifecycle patterns; no copy-paste component forks observed.
- Pattern consistency: coding style and routing conventions are largely consistent with adjacent adapter code; findings above are behavioral contract gaps rather than architecture breaks.

## Fixes Applied

- Issue: `/cancel` is not thread-scoped and can interrupt sessions from non-thread forum channels (Critical).
  - Fix: added explicit non-thread rejection in `_handle_cancel_slash` before any session lookup; retained thread-only success flow.
  - Commit: `1a767f8c`

- Issue: launcher lifecycle does not pin launcher message (Important).
  - Fix: added `_pin_launcher_message` helper and invoked pin on both launcher update and create paths with permission-safe logging.
  - Commit: `0d12d664`

- Issue: test coverage misses thread-only `/cancel` and launcher pinning contracts (Important).
  - Fix: added regression tests for non-thread `/cancel` rejection, launcher pin on create/update, and updated slash tests to use thread context.
  - Commit: `e98e088e`

## Verdict

REQUEST CHANGES

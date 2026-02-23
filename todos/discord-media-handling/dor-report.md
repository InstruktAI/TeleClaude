# Discord Media Handling — DOR Report

## Assessment

### Gate 1: Intent & success — PASS

Problem statement is explicit: Discord adapter drops image/file attachments silently. Six success criteria are concrete and independently testable (workspace file creation, dual text+attachment processing, regression safety).

### Gate 2: Scope & size — PASS

One production file (`discord_adapter.py`) plus one new test file. Voice handling is already shipped and correctly excluded. Fits a single build session.

### Gate 3: Verification — PASS

Five integration test cases defined (image-only, file-only, text+image, multi-attachment, download failure, audio regression). Demo plan covers four live scenarios with log-based verification. Edge cases are covered.

### Gate 4: Approach known — PASS

Pattern is proven in two places:

- Telegram adapter `_handle_file_attachment` (line 330) demonstrates the full download-to-`HandleFileCommand` pipeline.
- Discord voice handler `_handle_voice_attachment` (line 1066) demonstrates the Discord-side download via `attachment.save()` and session resolution via `_resolve_or_create_session`.
  The command layer (`HandleFileCommand` / `handle_file`) is adapter-agnostic — confirmed by reading the handler signature (requires only `session_id`, `file_path`, `filename`, `caption`, `file_size`).

### Gate 5: Research — N/A

No new dependencies. Uses existing discord.py attachment API and existing command service.

### Gate 6: Dependencies — PASS

No prerequisite work items. The voice handler, `HandleFileCommand`, `handle_file`, and `get_session_output_dir` are all in place.

### Gate 7: Integration safety — PASS

The change inserts a new code path between the existing voice check (line 923) and the text guard (line 929). The voice path is untouched (still returns early on audio). The text path is untouched except that the early return on empty text no longer blocks attachment-only messages — attachments are processed before the text guard.

### Gate 8: Tooling impact — N/A

No tooling, scaffolding, or configuration changes.

## Plan-to-requirement fidelity

| Requirement                       | Plan task(s)                                                                                        | Status  |
| --------------------------------- | --------------------------------------------------------------------------------------------------- | ------- |
| R1: Image attachment handling     | Task 1 (extract non-audio), Task 2 (download + `handle_file`), Task 3 (integrate), Task 4 (imports) | Covered |
| R2: File attachment handling      | Task 1, Task 2, Task 3, Task 4                                                                      | Covered |
| R3: Text + attachment coexistence | Task 3 (process attachments before text guard, continue to text processing)                         | Covered |
| R4: Attachment ordering           | Task 1 (iterate attachments in order), Task 3 (audio-first early return preserved)                  | Covered |
| R5: Error resilience              | Task 2 (try/except per attachment, ERROR-level logging, continue)                                   | Covered |
| SC1-SC6                           | Task 5 (test cases map 1:1 to success criteria)                                                     | Covered |

No contradictions. No orphan tasks. Every requirement traces to implementation. Every task traces to a requirement.

## Codebase verification

All code references validated against the current codebase:

- `_handle_on_message` at line 893, voice check at 923-927, text guard at 929-931 — confirmed.
- `_extract_audio_attachment` at line 1054, `_handle_voice_attachment` at line 1066 — confirmed.
- `HandleFileCommand` at `types/commands.py` line 218 — confirmed, not yet imported in discord adapter.
- `get_session_output_dir` in `core/session_utils.py` line 59 — confirmed, not yet imported in discord adapter.
- `attachment.save()` download pattern at line 1087 — confirmed (via `_require_async_callable`).
- Telegram `_handle_file_attachment` at `input_handlers.py` line 330 — confirmed, uses identical `HandleFileCommand` dispatch.
- Existing test infrastructure: `tests/unit/test_discord_adapter.py` and `tests/integration/test_voice_flow.py` provide reusable patterns.

## Assumptions (validated)

1. `attachment.save(path)` is the correct download API — confirmed by existing voice handler at line 1087.
2. `content_type` on Discord attachments reliably distinguishes image vs. other files — standard discord.py behavior.
3. `HandleFileCommand` / `handle_file` is adapter-agnostic — confirmed by reading the command handler signature.

## Notes

- The plan specifies caption assignment to the first attachment only (to avoid duplication when multiple attachments share one message). This is not explicitly stated in requirements (R1/R2 say "include caption if present") but is a reasonable implementation choice. The builder should follow the plan's approach.
- Input.md line-number references (347-349) are stale but irrelevant — requirements.md and implementation-plan.md reference correct line numbers.

## Open questions

None.

## Verdict

**PASS — Score 9/10.** All eight gates satisfied. Plan-to-requirement fidelity is complete with no contradictions. Codebase references are verified against current code. Ready for build.

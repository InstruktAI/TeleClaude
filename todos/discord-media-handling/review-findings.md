# Discord Media Handling — Review Findings

## Paradigm-Fit Assessment

1. **Data flow**: Uses the established command service layer (`HandleFileCommand` / `get_command_service().handle_file()`), `get_session_output_dir()`, and `_resolve_or_create_session()`. No inline hacks or bypasses. **Pass.**
2. **Component reuse**: Reuses `_resolve_or_create_session`, `_require_async_callable`, `get_session_output_dir`, `HandleFileCommand`. The `_extract_file_attachments` mirrors `_extract_audio_attachment` structurally (same pattern, different filter) — appropriate, not a copy-paste violation. **Pass.**
3. **Pattern consistency**: Follows the same shape as `_handle_voice_attachment` — session resolution, download, command dispatch. Logging, error handling, and `_require_async_callable` usage all match established patterns. **Pass.**

## Critical

None.

## Important

### 1. Double session resolution for text+attachment messages

**File:** `teleclaude/adapters/discord_adapter.py:930-940`

When a message has both file attachments and text, `_resolve_or_create_session` is called twice:

- First in `_handle_file_attachments` (line 1130)
- Again in the text processing path (line 940)

The second call finds the session created/resolved by the first, so no double creation occurs — but it's a redundant DB round-trip (lookup + metadata update) on every text+attachment message.

**Fix**: Either hoist session resolution before both paths in `_handle_on_message` and pass the session down, or have `_handle_file_attachments` return the resolved session for reuse by the text path.

## Suggestions

### 1. Missing `file_size` in HandleFileCommand

**File:** `teleclaude/adapters/discord_adapter.py:1170-1177`

`HandleFileCommand` accepts `file_size` (defaults to 0). The Telegram adapter populates it from `file_obj.file_size`. Discord attachments expose a `size` attribute that could be used. Not breaking (default is 0), but a data completeness gap.

### 2. File attachments not gated by relay mode

**File:** `teleclaude/adapters/discord_adapter.py:930-933` vs `948-950`

File attachments are processed before the relay mode check. During active relay, text is diverted to the relay thread but files still go to the AI session. This is explicitly out of scope per requirements ("Relay thread file forwarding — deferred"), but the asymmetry could confuse operators. Consider either skipping file processing during relay mode or documenting this as a known limitation in a future iteration.

## Verdict: APPROVE

The implementation correctly satisfies all 5 requirements (R1-R5) and all 6 success criteria. The code follows established codebase paradigms, reuses the command service layer properly, and includes comprehensive test coverage with 6 passing tests covering image-only, file-only, text+image, multiple attachments, download failure resilience, and audio regression. The Important finding (double session resolution) is a performance optimization opportunity, not a correctness issue.

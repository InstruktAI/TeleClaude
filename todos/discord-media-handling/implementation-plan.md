# Discord Media Handling — Implementation Plan

## Overview

Add image and file attachment handling to `discord_adapter.py` `_handle_on_message`, reusing the existing command service layer (`HandleFileCommand` / `handle_file`).

## Files to modify

1. `teleclaude/adapters/discord_adapter.py` — main changes
2. `tests/integration/test_discord_media.py` — new test file

## Tasks

### Task 1: Add attachment extraction helper [x]

**File:** `teleclaude/adapters/discord_adapter.py`

Add `_extract_file_attachments(message) -> list[object]` static method alongside `_extract_audio_attachment`:

- Iterate `message.attachments`
- Exclude attachments where `content_type` starts with `audio/` (already handled by voice path)
- Return remaining attachments (images and other files)

### Task 2: Add file/image attachment handler [x]

**File:** `teleclaude/adapters/discord_adapter.py`

Add `_handle_file_attachments(self, message, attachments: list[object]) -> None` method:

- Call `_resolve_or_create_session(message)` to get session
- For each attachment:
  - Determine file type: `content_type.startswith("image/")` → photo, else → file
  - Set subdirectory: `photos/` for images, `files/` for others
  - Derive filename from `attachment.filename` or generate default
  - Download to `get_session_output_dir(session.session_id) / subdir / filename`
  - Call `get_command_service().handle_file(HandleFileCommand(...))` with caption from `message.content` (first attachment only gets caption to avoid duplication)
- Wrap each attachment in try/except — log errors, continue to next

### Task 3: Integrate into `_handle_on_message` flow [x]

**File:** `teleclaude/adapters/discord_adapter.py`

Modify the flow after the voice attachment check (line ~928):

- Extract non-audio attachments via `_extract_file_attachments`
- If any exist, call `_handle_file_attachments`
- Continue to text processing (don't return early) — allows text + attachment coexistence
- Adjust the early return on empty text: only return if there are no attachments AND no text

Current flow (lines 923-931):

```python
audio_attachment = self._extract_audio_attachment(message)
if audio_attachment is not None:
    await self._handle_voice_attachment(message, audio_attachment)
    return

text = getattr(message, "content", None)
if not isinstance(text, str) or not text.strip():
    return
```

New flow:

```python
audio_attachment = self._extract_audio_attachment(message)
if audio_attachment is not None:
    await self._handle_voice_attachment(message, audio_attachment)
    return

# Handle image/file attachments (non-audio)
file_attachments = self._extract_file_attachments(message)
if file_attachments:
    await self._handle_file_attachments(message, file_attachments)

text = getattr(message, "content", None)
if not isinstance(text, str) or not text.strip():
    return  # No text — if attachments existed, they were already handled above

# ... rest of text processing unchanged
```

### Task 4: Add imports [x]

**File:** `teleclaude/adapters/discord_adapter.py`

Add imports for:

- `HandleFileCommand` from `teleclaude.types.commands`
- `get_session_output_dir` from `teleclaude.core.session_utils`

Check if these are already imported (HandleVoiceCommand is already imported for the voice handler).

### Task 5: Integration tests [x]

**File:** `tests/integration/test_discord_media.py` (new)

Test cases:

1. Image-only message: creates session, downloads image, dispatches `handle_file`
2. File-only message (PDF): same pattern for files
3. Text + image message: both `handle_file` and `process_message` are called
4. Multiple attachments: all non-audio attachments are processed
5. Download failure: logged, other attachments still processed
6. Audio attachment: still handled by existing voice path (regression check)

Use the same mocking patterns as `test_voice_flow.py` — mock `attachment.save`, `get_command_service`, `db`.

## Execution order

Task 4 → Task 1 → Task 2 → Task 3 → Task 5

## Risk

Low. The change adds a new code path alongside the existing voice and text paths. No modifications to existing paths except adjusting the early-return guard for empty text.

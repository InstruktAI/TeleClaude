# File Upload Handler Implementation Plan

## Overview

Enable users to upload files (documents, photos, PDFs, zip archives, etc.) via Telegram and have them automatically passed to Claude Code or other terminal processes for analysis and processing.

## Architecture Pattern (Voice Message as Reference)

**Voice Message Flow (Existing):**
```
Telegram → Download to temp → Transcribe → Send TEXT to tmux → Delete temp
```

**File Upload Flow (New):**
```
Telegram → Download to persistent storage → Send @PATH to tmux → Keep file
```

### Key Differences from Voice

1. **Storage**: Persistent (session-scoped) vs temporary
2. **Processing**: Path reference vs transcription
3. **Cleanup**: On session end vs immediate
4. **Input format**: `@/path/to/file` vs plain text

## Implementation Tasks

### 1. Event System Extension

**File**: `teleclaude/core/events.py`

Add new event type:
```python
# In EventType literal
"file",          # File/photo upload received

# In TeleClaudeEvents class
FILE: Literal["file"] = "file"  # File or photo uploaded
```

**Rationale**: Consistent with existing VOICE event pattern.

---

### 2. File Storage Structure

**Create persistent storage hierarchy:**
```
session_files/
├── {session_id_1}/
│   ├── document_123.pdf
│   ├── photo_456.jpg
│   └── archive_789.zip
├── {session_id_2}/
│   └── screenshot_001.png
└── .gitignore  # Ignore all uploaded files
```

**Location**: Project root `/session_files/`
**Lifecycle**: Created on first upload, deleted when session closed
**Benefits**:
- Organized by session (easy cleanup)
- Survives daemon restarts (Claude can reference after crash)
- Clear ownership (one session = one directory)

**Cleanup strategy**:
- Delete session directory when `/exit` called
- Delete in `finally` block of session exit handler
- Add to existing session cleanup routine

---

### 3. Telegram Adapter Handler

**File**: `teleclaude/adapters/telegram_adapter.py`

#### 3.1 Register Handlers in `start()` Method

Add after voice handler registration (~line 176):
```python
# Handle file uploads (documents and photos) in topics
self.app.add_handler(MessageHandler(filters.Document.ALL, self._handle_file_upload))
self.app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo_upload))
```

**Note**: Two separate handlers because Telegram treats photos and documents differently:
- Photos: Compressed, multiple sizes, no filename
- Documents: Original quality, has filename, explicit MIME type

#### 3.2 Implement `_handle_file_upload()` Method

**Responsibilities**:
1. Deduplicate (like voice - track processed message IDs)
2. Find session from topic
3. Download file to `session_files/{session_id}/`
4. Preserve original filename
5. Delete Telegram message (clean UX, like voice)
6. Emit FILE event with session_id and file path

**Pseudo-code**:
```python
async def _handle_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document uploads in topics."""
    # 1. Deduplication check
    if message_id in self._processed_file_messages:
        return
    self._processed_file_messages.add(message_id)

    # 2. Get session
    session = await self._get_session_from_topic(update)
    if not session:
        return

    # 3. Create session file directory
    session_dir = Path("session_files") / session.session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # 4. Download file
    document = update.message.document
    file = await document.get_file()
    filename = document.file_name or f"file_{message_id}"
    file_path = session_dir / filename
    await file.download_to_drive(file_path)

    # 5. Delete Telegram message (clean UX)
    try:
        await update.message.delete()
    except Exception as e:
        logger.warning("Failed to delete file message: %s", e)

    # 6. Emit FILE event
    await self.client.handle_event(
        event=TeleClaudeEvents.FILE,
        payload={
            "session_id": session.session_id,
            "file_path": str(file_path),
            "filename": filename,
        },
        metadata={
            "adapter_type": "telegram",
            "user_id": update.effective_user.id,
            "message_id": message_id,
            "mime_type": document.mime_type,
            "file_size": document.file_size,
        },
    )
```

#### 3.3 Implement `_handle_photo_upload()` Method

**Key differences from documents**:
1. Photos arrive as array of sizes (thumbnail, medium, large)
2. No original filename (generate from timestamp)
3. Always JPEG format

**Logic**:
```python
async def _handle_photo_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo uploads in topics."""
    # Get largest photo size
    photo = update.message.photo[-1]  # Last element = highest resolution

    # Generate filename with timestamp
    filename = f"photo_{int(time.time())}_{message_id}.jpg"

    # Rest identical to document handler
```

---

### 4. Core File Handler Module

**File**: `teleclaude/core/file_handler.py` (NEW)

**Purpose**: Adapter-agnostic business logic for file uploads (mirrors `voice_message_handler.py`)

#### 4.1 High-Level Handler Function

```python
async def handle_file(
    session_id: str,
    file_path: str,
    filename: str,
    context: dict[str, object],
    send_feedback: Callable[[str, str, bool], Awaitable[Optional[str]]],
) -> None:
    """Handle file upload (adapter-agnostic utility).

    Args:
        session_id: Session ID
        file_path: Path to downloaded file
        filename: Original filename
        context: Platform-specific context (adapter_type, user_id, file_size, etc.)
        send_feedback: Async function to send user feedback (session_id, message, append)
    """
```

**Core Logic**:

1. **Validate session exists**
   ```python
   session = await db.get_session(session_id)
   if not session:
       return
   ```

2. **Check if process is running** (like voice)
   ```python
   is_process_running = await db.is_polling(session_id)
   if not is_process_running:
       await send_feedback(
           session_id,
           f"📎 File upload requires an active process. File saved: {filename}",
           False,
       )
       return
   ```

3. **Detect Claude Code process** (check if "claude" or "claude.ai" in process name)
   ```python
   # Check tmux pane title or process list
   is_claude_running = await _is_claude_code_running(session.tmux_session_name)
   ```

4. **Send file reference to terminal**
   ```python
   if is_claude_running:
       # Claude Code: Use @ prefix for automatic file reading
       input_text = f"@{file_path}"
   else:
       # Other processes: Send plain path
       input_text = file_path

   success = await terminal_bridge.send_keys(
       session.tmux_session_name,
       input_text,
       append_exit_marker=False,  # Never append marker for file inputs
   )
   ```

5. **Send confirmation feedback**
   ```python
   if success:
       file_size_mb = context.get("file_size", 0) / 1_048_576
       await send_feedback(
           session_id,
           f"📎 File uploaded: {filename} ({file_size_mb:.2f} MB)",
           True,  # Append to existing output
       )
   ```

#### 4.2 Helper: Detect Claude Code Process

```python
async def _is_claude_code_running(tmux_session_name: str) -> bool:
    """Detect if Claude Code is running in the tmux session.

    Strategy:
    1. Check pane title (tmux display-message -p '#{pane_title}')
    2. Check running command (ps aux | grep claude)

    Returns:
        True if Claude Code detected, False otherwise
    """
    # Implementation uses terminal_bridge.execute_command()
```

---

### 5. Daemon Integration

**File**: `teleclaude/daemon.py`

#### 5.1 Subscribe to FILE Events

In `start()` method, add after VOICE subscription (~line 150):
```python
self.client.on(TeleClaudeEvents.FILE, self._handle_file)
```

#### 5.2 Implement Event Handler

```python
async def _handle_file(self, event: str, context: dict[str, object]) -> None:
    """Handler for FILE events - pure business logic.

    Args:
        event: Event type (always "file")
        context: Unified context (all payload + metadata fields)
    """
    session_id = context.get("session_id")
    file_path = context.get("file_path")
    filename = context.get("filename")

    if not session_id or not file_path or not filename:
        logger.warning(
            "FILE event missing required fields: session_id=%s, file_path=%s, filename=%s",
            session_id, file_path, filename
        )
        return

    # Define send_feedback (same pattern as voice)
    async def send_feedback(sid: str, msg: str, append: bool) -> Optional[str]:
        """Send feedback message and mark for deletion on next input."""
        message_id = await self.client.send_message(sid, msg)
        if message_id:
            await db.add_pending_deletion(sid, message_id)
        return message_id

    # Handle file using utility function
    await file_handler.handle_file(
        session_id=str(session_id),
        file_path=str(file_path),
        filename=str(filename),
        context=context,
        send_feedback=send_feedback,
    )
```

---

### 6. Session Cleanup Integration

**File**: `teleclaude/daemon.py` (or relevant session cleanup module)

**Add to session exit/cleanup logic**:

```python
async def _cleanup_session_files(session_id: str) -> None:
    """Delete uploaded files when session closes.

    Args:
        session_id: Session ID to clean up
    """
    session_dir = Path("session_files") / session_id
    if session_dir.exists():
        try:
            shutil.rmtree(session_dir)
            logger.info("Cleaned up session files: %s", session_dir)
        except Exception as e:
            logger.warning("Failed to clean up session files %s: %s", session_dir, e)
```

**Call from**:
- `/exit` command handler (like output file cleanup)
- `handle_topic_closed` (Telegram topic deletion)
- Session timeout cleanup routine

---

### 7. Testing Strategy

#### Unit Tests

**File**: `tests/unit/test_file_handler.py`

1. **Test file reference formatting**
   - Claude Code running → `@/path/to/file`
   - Other process running → `/path/to/file`

2. **Test rejection when no process running**
   - Verify feedback message sent
   - File still saved (not deleted)

3. **Test Claude Code detection**
   - Mock tmux output with "claude" in title
   - Mock tmux output without "claude"

#### Integration Tests

**File**: `tests/integration/test_file_upload.py`

1. **End-to-end file upload flow**
   - Telegram → Download → Event → Handler → Terminal
   - Verify file saved to correct location
   - Verify correct input sent to tmux

2. **Session cleanup**
   - Upload file → Close session → Verify files deleted

3. **Restart resilience**
   - Upload file → Restart daemon → Verify files still exist

---

### 8. Configuration (Optional Future Enhancement)

**File**: `config.yml`

```yaml
files:
  max_size_mb: 20  # Max file size (Telegram limit is 20MB for bots)
  allowed_extensions:  # Empty = allow all
    - .pdf
    - .txt
    - .md
    - .py
    - .zip
    - .jpg
    - .png
  storage_path: session_files  # Relative to project root
```

---

### 9. Documentation Updates

#### 9.1 Architecture Doc

**File**: `docs/architecture.md`

Add section under "Message Flow Architecture":
```markdown
### File Upload Flow

1. User uploads file/photo via Telegram
2. TelegramAdapter downloads to `session_files/{session_id}/`
3. Adapter emits FILE event with file_path
4. Daemon validates session and checks for running process
5. If Claude Code running: send `@{file_path}` to terminal
6. If other process: send `{file_path}` to terminal
7. Files cleaned up when session closes
```

#### 9.2 README

**File**: `README.md`

Add to features list:
```markdown
- 📎 **File uploads**: Send documents, photos, PDFs, zip files - automatically passed to Claude Code for analysis
```

---

### 10. Error Handling

**Edge cases to handle:**

1. **File too large** (Telegram limit: 20MB for bots)
   - Telegram handles rejection
   - Log warning if download fails

2. **Disk space exhausted**
   - Catch OSError on mkdir/write
   - Send error feedback to user
   - Don't crash daemon

3. **Malformed filenames** (path traversal, special chars)
   - Sanitize filename: `re.sub(r'[^\w\-.]', '_', filename)`
   - Prevent directory traversal: use `Path().resolve()` and verify parent

4. **Session closed during upload**
   - Check session still exists before sending to terminal
   - If session gone, delete file immediately

5. **Duplicate filenames** in same session
   - Append counter: `file.pdf` → `file_1.pdf` → `file_2.pdf`
   - Or use timestamp: `file_1699123456.pdf`

---

### 11. Security Considerations

1. **Path traversal prevention**
   ```python
   # Resolve path and verify it's within session_files
   file_path = (session_dir / filename).resolve()
   if not file_path.is_relative_to(session_dir):
       raise ValueError("Path traversal detected")
   ```

2. **Filename sanitization**
   ```python
   import re
   safe_filename = re.sub(r'[^\w\-.]', '_', original_filename)
   ```

3. **File size limits**
   - Telegram enforces 20MB for bots (no extra code needed)
   - Could add config-based limit for additional safety

4. **MIME type validation** (optional)
   - Check `document.mime_type` against allowlist
   - Reject executable files (.exe, .sh, .bat) if paranoid

---

## Implementation Order

1. ✅ **Create this plan** (DONE)
2. Add FILE event to `events.py`
3. Create `session_files/` directory structure
4. Implement `file_handler.py` core logic
5. Add Telegram handlers (`_handle_file_upload`, `_handle_photo_upload`)
6. Add daemon event subscription (`_handle_file`)
7. Integrate session cleanup
8. Write unit tests
9. Write integration tests
10. Update documentation
11. Test end-to-end with real Telegram uploads

---

## Open Questions / Design Decisions

### Q1: Should we support drag-and-drop of multiple files at once?

**Answer**: Start with single file per upload (simplest). Multi-file can be added later by:
- Detecting multiple files in one message (Telegram supports media groups)
- Downloading all to session directory
- Sending multiple `@path1 @path2 @path3` to terminal

### Q2: What if Claude Code isn't installed on the system?

**Answer**:
- Handler should gracefully degrade (send plain path instead of @path)
- Detection logic should not assume `claude` binary exists
- Focus on process detection, not installation check

### Q3: Should we show preview/thumbnail in Telegram?

**Answer**: No - delete message immediately (like voice) for clean UX. User knows file was uploaded by seeing it in their "sent" history.

### Q4: What about binary files (executables, images)?

**Answer**:
- Images: Claude Code can analyze (vision capability)
- PDFs: Claude Code can read text
- Zip: Send path, let user decide to unzip in terminal
- Executables: Just send path, don't execute automatically (security)

### Q5: Should files persist after session restart?

**Answer**: Yes! This enables:
- Reference files across multiple commands
- Survive daemon restarts (like session_output files)
- Long-lived sessions with file context

---

## Success Criteria

1. ✅ User uploads PDF via Telegram
2. ✅ File saved to `session_files/{session_id}/filename.pdf`
3. ✅ If Claude Code running: receives `@/path/to/file.pdf` as input
4. ✅ If other process: receives `/path/to/file.pdf` as input
5. ✅ Feedback message shows "📎 File uploaded: filename.pdf (1.23 MB)"
6. ✅ Files deleted when session closed
7. ✅ Works for both documents and photos
8. ✅ Survives daemon restarts

---

## Future Enhancements (Out of Scope for MVP)

1. **Multi-file uploads** (media groups)
2. **File preview/thumbnails** in Telegram
3. **Automatic extraction** of zip/tar archives
4. **Image OCR** before sending to Claude
5. **File versioning** (keep history of uploaded files)
6. **Allowlist/blocklist** by MIME type or extension
7. **Quota limits** per session (e.g., max 100MB total)
8. **Cloud storage integration** (S3, GCS) for large files

---

## References

- Voice message handler: `teleclaude/core/voice_message_handler.py`
- Event system: `teleclaude/core/events.py`
- Telegram adapter: `teleclaude/adapters/telegram_adapter.py`
- Claude Code file syntax: https://stevekinney.com/courses/ai-development/referencing-files-in-claude-code

---

**END OF PLAN**

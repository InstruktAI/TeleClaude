# Discord Media Handling — Demo Plan

## Medium

Discord help desk forum (live interaction via TeleClaude Discord adapter).

## Scenarios

### 1. Image-only message

**Action:** Send a screenshot (no text) to a Discord help desk thread.
**Observe:** A session is created (or existing session found). The AI agent receives the image path and acknowledges the file.
**Validate:** Check session workspace — `workspace/{session_id}/photos/` contains the image file.

### 2. File attachment

**Action:** Send a PDF document to a Discord help desk thread.
**Observe:** The AI agent receives the file path and acknowledges the document.
**Validate:** Check `workspace/{session_id}/files/` contains the PDF.

### 3. Text + image combo

**Action:** Send a message with text "Here's the error screenshot" plus an attached image.
**Observe:** The AI agent receives both the text message and the image file path — it can reference the screenshot content.
**Validate:** Both `process_message` and `handle_file` events fire in daemon logs.

### 4. Voice message (regression)

**Action:** Send a voice message to a Discord help desk thread.
**Observe:** Voice message is transcribed and processed as before.
**Validate:** No change in behavior from current voice handling.

## Log verification

```bash
instrukt-ai-logs teleclaude --since 5m --grep "Downloaded.*to:"
```

Should show lines like:

- `Downloaded photo to: /path/to/workspace/{session_id}/photos/image.png`
- `Downloaded file to: /path/to/workspace/{session_id}/files/document.pdf`

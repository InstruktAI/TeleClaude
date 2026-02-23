# Discord Media Handling — Requirements

## Problem

The Discord adapter silently drops image uploads and file attachments. After the voice handling check (which works), `_handle_on_message` returns early if no text is present (line 930). Messages with text + attachments process the text but ignore the attachment.

Customers sending screenshots, documents, or image-only messages to the help desk get no response.

## Scope

Add image and file attachment handling to the Discord adapter's `_handle_on_message` flow. Voice messages are already handled and out of scope.

## Requirements

### R1: Image attachment handling

When a Discord message contains an image attachment (`content_type` starting with `image/`):

- Resolve or create a session (reuse `_resolve_or_create_session`)
- Download the image to `{session_workspace}/photos/{filename}`
- Dispatch via `command_service.handle_file()` with `HandleFileCommand`
- Include the message caption (text content) if present

### R2: File attachment handling

When a Discord message contains a non-audio, non-image attachment:

- Resolve or create a session
- Download the file to `{session_workspace}/files/{filename}`
- Dispatch via `command_service.handle_file()` with `HandleFileCommand`
- Include the message caption if present

### R3: Text + attachment coexistence

When a Discord message contains both text and one or more non-audio attachments:

- Process all attachments (images and files) via `handle_file`
- Process the text via `process_message` as today
- Both paths execute; attachments are not swallowed by the text path

### R4: Attachment ordering

When a message contains multiple attachments:

- Process each attachment individually in order
- Audio attachments continue to be handled by the existing voice path (first audio wins, returns early)
- Non-audio attachments (images, files) are processed after the voice check

### R5: Error resilience

- A failed download for one attachment must not prevent processing of other attachments or the text
- Download failures are logged at ERROR level
- No user-facing error messages for file downloads (consistent with current voice error handling which only logs)

## Non-requirements

- Embed handling (linked images, video embeds) — deferred
- DM file attachments — the DM handler is a separate flow, deferred
- Relay thread file forwarding — deferred
- File size limits — rely on Discord's own limits
- Deduplication — not needed; Discord messages are delivered once (unlike Telegram edited messages)

## Success criteria

1. A Discord help desk message with only an image (no text) creates a session and injects the image
2. A Discord help desk message with only a PDF (no text) creates a session and injects the file
3. A Discord help desk message with text + image processes both the text and the image
4. Multiple attachments in one message are all processed
5. Existing voice message handling is unchanged
6. Existing text-only message handling is unchanged

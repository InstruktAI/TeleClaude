# Demo: discord-session-routing

## Medium

Discord server (live) + daemon logs.

## Walkthrough

### 1. Per-project forums exist

**Observe:** After daemon startup, the Discord server's "Projects" category contains one forum per trusted dir (e.g., "TeleClaude", "dotfiles"). Each forum was auto-provisioned.

**Validate:**

```bash
telec config get computer.trusted_dirs | grep discord_forum
```

Each trusted dir should have a `discord_forum` ID populated.

### 2. Session lands in correct project forum

**Observe:** Start a session in the TeleClaude project. The Discord thread appears in the "TeleClaude" project forum, not in "All Sessions".

**Validate:**

```bash
telec claude fast "echo hello"
# Check Discord — thread should be in TeleClaude forum
```

### 3. Thread title is description-only

**Observe:** The Discord thread title is just the session description (e.g., "Untitled"), not the full metadata-rich format used in Telegram.

### 4. Thread header shows metadata

**Observe:** The first message in the Discord thread contains structured metadata:

```
project: TeleClaude | agent: claude/fast
tc: abc12345
ai: (pending)
```

### 5. Catch-all fallback works

**Observe:** A session without a matching project path falls back to the "All Sessions" forum. Its title includes the project prefix: `{project}: {description}`.

### 6. Admin messages from project forums are accepted

**Observe:** Send a message from a project forum thread as an admin. The message is routed to the session and processed.

### 7. Telegram is unchanged

**Observe:** Telegram topics still use the metadata-rich title format. Footer behavior is identical.

**Validate:**

```bash
# Start session, check Telegram — title format should be unchanged
# e.g. "TeleClaude: Claude-fast@MozMini - Untitled"
```

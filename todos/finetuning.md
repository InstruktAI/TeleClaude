# Session Lifecycle Fixes

## Problem

- Cleanup script finds dead sessions but Telegram UI doesn't show they're closed
- User closes topic in Telegram but tmux keeps running
- `/cd` command doesn't save working directory, so reopened sessions start at wrong location
- User can't reopen closed sessions

## What Needs to Be Done

### 1. Telegram Adapter - Detect Topic Close/Reopen

Add handlers for when user closes/reopens topics:

```python
# telegram_adapter.py start() method
self.app.add_handler(MessageHandler(
    filters.StatusUpdate.FORUM_TOPIC_CLOSED,
    self._handle_forum_topic_closed
))
self.app.add_handler(MessageHandler(
    filters.StatusUpdate.FORUM_TOPIC_REOPENED,
    self._handle_forum_topic_reopened
))

async def _handle_forum_topic_closed(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User closed topic."""
    topic_id = str(update.message.message_thread_id)
    sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)
    if sessions:
        session = sessions[0]
        await self.client.handle_event(
            event="session_closed",
            payload={"session_id": session.session_id},
            metadata={"adapter_type": "telegram"}
        )

async def _handle_forum_topic_reopened(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User reopened topic."""
    topic_id = str(update.message.message_thread_id)
    sessions = await db.get_sessions_by_adapter_metadata("telegram", "topic_id", topic_id)
    if sessions:
        session = sessions[0]
        # Trigger reopen via event
        await self.client.handle_event(
            event="session_reopened",
            payload={"session_id": session.session_id},
            metadata={"adapter_type": "telegram"}
        )
```

### 2. Daemon - Handle session_closed Event

```python
# daemon.py run() method - register handlers
self.client.on("session_closed", self._handle_session_closed)
self.client.on("session_reopened", self._handle_session_reopened)

# Wire DB to client
db.set_client(self.client)

# daemon.py - add handler method
async def _handle_session_closed(self, event: str, context: dict) -> None:
    """User closed topic - kill tmux and mark closed."""
    session_id = context.get("session_id")
    if not session_id:
        return

    session = await db.get_session(str(session_id))
    if not session:
        return

    # Kill tmux
    await terminal_bridge.kill_session(session.tmux_session_name)

    # Stop polling
    await self.polling_coordinator.stop_polling(str(session_id))

    # Mark closed in DB (DB will update UI via AdapterClient)
    await db.update_session(str(session_id), closed=True)

async def _handle_session_reopened(self, event: str, context: dict) -> None:
    """User reopened topic - recreate tmux."""
    session_id = context.get("session_id")
    if not session_id:
        return

    session = await db.get_session(str(session_id))
    if not session:
        return

    await self._reopen_session(session)
```

### 3. Daemon - Auto-Reopen on Message to Closed Session

```python
# daemon.py _handle_message() - add auto-reopen logic
async def _handle_message(self, event: str, context: dict) -> None:
    """Handle MESSAGE events."""
    session_id = context.get("session_id")
    text = context.get("text")

    if not session_id or not text:
        return

    session = await db.get_session(str(session_id))
    if not session:
        return

    # Auto-reopen if closed
    if session.closed:
        await self._reopen_session(session)

    # Handle message normally
    await self.handle_message(str(session_id), str(text), context)
```

### 4. DB - Update UI When Session Closed/Reopened

```python
# db.py
class Db:
    def __init__(self, db_path: str) -> None:
        self._db: Optional[aiosqlite.Connection] = None
        self._client: Optional["AdapterClient"] = None

    def set_client(self, client: "AdapterClient") -> None:
        """Wire to AdapterClient for UI updates."""
        self._client = client

    async def update_session(self, session_id: str, **fields: object) -> None:
        """Update session and trigger UI updates."""
        if not fields:
            return

        old_session = await self.get_session(session_id)

        # ... existing update logic ...

        # Update UI via AdapterClient
        if self._client and old_session:
            # Session closed - add ❌ emoji
            if "closed" in fields and fields["closed"] and not old_session.closed:
                await self._client.set_channel_status(session_id, "closed")

            # Session reopened - remove ❌ emoji
            if "closed" in fields and not fields["closed"] and old_session.closed:
                await self._client.set_channel_status(session_id, "active")
```

### 5. DB - Remove Bogus handle_event Calls

```python
# db.py - REMOVE these lines (they don't work, handle_event doesn't exist):
await self._client.handle_event(...)  # ❌ DELETE ALL OF THESE
```

### 6. AdapterClient - Add set_channel_status Wrapper

**NOTE:** Adapters already have `set_channel_status()` - we just need a wrapper in AdapterClient for DB to call.

```python
# adapter_client.py
async def set_channel_status(self, session_id: str, status: str) -> None:
    """Update channel status (add/remove emoji) in origin adapter.

    Args:
        session_id: Session ID
        status: "closed" or "active"
    """
    session = await db.get_session(session_id)
    if not session:
        return

    adapter = self.adapters.get(session.origin_adapter)
    if adapter:
        await adapter.set_channel_status(session_id, status)
```

### 7. Fix /cd to Save Working Directory

```python
# command_handlers.py handle_cd_session()
success = await execute_terminal_command(session.session_id, cd_command, True, message_id)

# Save to DB
if success:
    await db.update_session(session.session_id, working_directory=target_dir)
```

### 8. Move session_lifecycle.py Functions to Proper Locations

**Delete `teleclaude/core/session_lifecycle.py` and move functions:**

```python
# Move migrate_session_metadata() to db.py
# db.py - add this method to Db class
async def migrate_session_metadata(self) -> None:
    """Migrate old session metadata to new format.

    Old format: {"topic_id": 12345}
    New format: {"channel_id": "12345"}
    """
    sessions = await self.list_sessions()
    migrated = 0

    for session in sessions:
        if not session.adapter_metadata:
            continue

        if "topic_id" in session.adapter_metadata and "channel_id" not in session.adapter_metadata:
            new_metadata = session.adapter_metadata.copy()
            new_metadata["channel_id"] = str(new_metadata.pop("topic_id"))
            await self.update_session(session.session_id, adapter_metadata=new_metadata)
            migrated += 1
            logger.debug("Migrated session %s metadata", session.session_id[:8])

    if migrated > 0:
        logger.info("Migrated %d session(s) to new metadata format", migrated)
```

```python
# Move periodic_cleanup() and cleanup_inactive_sessions() to daemon.py
# daemon.py - add these methods to Daemon class
async def _periodic_cleanup(self) -> None:
    """Periodically clean up inactive sessions (72h lifecycle)."""
    while True:
        try:
            await asyncio.sleep(3600)  # Run every hour
            await self._cleanup_inactive_sessions()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Error in periodic cleanup: %s", e)

async def _cleanup_inactive_sessions(self) -> None:
    """Clean up sessions inactive for 72+ hours."""
    try:
        cutoff_time = datetime.now() - timedelta(hours=72)
        sessions = await db.list_sessions()

        for session in sessions:
            if session.closed:
                continue

            if not session.last_activity:
                logger.warning("No last_activity for session %s", session.session_id[:8])
                continue

            if session.last_activity < cutoff_time:
                logger.info(
                    "Cleaning up inactive session %s (inactive for %s)",
                    session.session_id[:8],
                    datetime.now() - session.last_activity,
                )

                # Kill tmux
                await terminal_bridge.kill_session(session.tmux_session_name)

                # Mark closed (DB will update UI)
                await db.update_session(session.session_id, closed=True)

                logger.info("Session %s cleaned up (72h lifecycle)", session.session_id[:8])

    except Exception as e:
        logger.error("Error cleaning up inactive sessions: %s", e)
```

**Update daemon.py to call migrate and start periodic cleanup:**

```python
# daemon.py run() method - after db.initialize()
await db.migrate_session_metadata()

# Start periodic cleanup task
asyncio.create_task(self._periodic_cleanup())
```

### 9. Add reopen_session to Daemon

```python
# daemon.py - add this method to Daemon class
async def _reopen_session(self, session: Session) -> None:
    """Recreate tmux at saved working directory and mark active."""

    await terminal_bridge.create_session(
        session_name=session.tmux_session_name,
        working_directory=session.working_dir,
        shell=self.config.computer.default_shell,
        terminal_size=session.terminal_size or "120x40",
    )

    await db.update_session(session.session_id, closed=False)
```

## Files to Modify

1. `teleclaude/adapters/telegram_adapter.py` - Add forum topic handlers
2. `teleclaude/daemon.py` - Add handlers, wire db.set_client(), add \_reopen_session() method, move cleanup functions from session_lifecycle.py
3. `teleclaude/core/db.py` - Add set_client(), call client.set_channel_status(), remove handle_event calls, move migrate function from session_lifecycle.py
4. `teleclaude/core/adapter_client.py` - Add set_channel_status() method
5. `teleclaude/core/command_handlers.py` - Save working_directory after /cd
6. `teleclaude/core/session_lifecycle.py` - DELETE THIS FILE (move functions to db.py and daemon.py)

Done.

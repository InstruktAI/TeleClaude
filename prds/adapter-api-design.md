# TeleClaude Adapter API Design

## Overview

The TeleClaude daemon is designed with a client-agnostic architecture. The core daemon handles terminal sessions, recording, and business logic, while **adapters** handle platform-specific communication (Telegram, WhatsApp, Slack, etc.).

This document defines the interface between the core daemon and adapters.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                  Core Daemon                        │
│                                                     │
│  ┌────────────────┐      ┌──────────────────┐     │
│  │ Session Manager│◄────►│ Terminal Bridge  │     │
│  │   (SQLite)     │      │     (tmux)       │     │
│  └────────────────┘      └──────────────────┘     │
│           │                       │                │
│           ▼                       ▼                │
│  ┌────────────────┐      ┌──────────────────┐     │
│  │ Output Stream  │      │  Recorder Mgr    │     │
│  │   Manager      │      │  (text + video)  │     │
│  └────────────────┘      └──────────────────┘     │
│           │                                        │
│           └──────────► Events ─────────────┐      │
│                                             │      │
└─────────────────────────────────────────────┼──────┘
                                              │
                        ┌─────────────────────┼──────────────┐
                        │    Adapter Layer    │              │
                        │                     ▼              │
                        │  ┌───────────────────────────┐     │
                        │  │   BaseAdapter (ABC)       │     │
                        │  │   - send_message()        │     │
                        │  │   - edit_message()        │     │
                        │  │   - create_channel()      │     │
                        │  │   - send_file()           │     │
                        │  │   ... (see interface)     │     │
                        │  └───────────────────────────┘     │
                        │              △                     │
                        │              │                     │
                        │    ┌─────────┴─────────┐          │
                        │    │                   │          │
                        │    ▼                   ▼          │
                        │  ┌──────────────┐  ┌──────────┐   │
                        │  │   Telegram   │  │ WhatsApp │   │
                        │  │   Adapter    │  │ Adapter  │   │
                        │  └──────────────┘  └──────────┘   │
                        └──────────────────────────────────┘
                                      │
                                      ▼
                              External Platform
                           (Telegram, WhatsApp, etc.)
```

---

## Core Daemon → Adapter Communication

The daemon communicates with adapters through method calls on the adapter instance.

### BaseAdapter Interface

```python
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

@dataclass
class Message:
    """Represents an outgoing message"""
    session_id: str
    text: str
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class File:
    """Represents a file to send"""
    session_id: str
    file_path: str
    caption: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class BaseAdapter(ABC):
    """
    Abstract base class for all messaging platform adapters.

    Adapters must implement these methods to enable the core daemon
    to send messages, manage channels, and interact with the platform.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize adapter with configuration.

        Args:
            config: Adapter-specific configuration (credentials, settings, etc.)
        """
        self.config = config
        self._message_callbacks = []
        self._file_callbacks = []
        self._voice_callbacks = []
        self._command_callbacks = []

    # ==================== Lifecycle Methods ====================

    @abstractmethod
    async def start(self) -> None:
        """
        Initialize adapter and start listening for incoming messages.
        Should be non-blocking (run in background task).
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """
        Gracefully stop adapter and cleanup resources.
        """
        pass

    # ==================== Outgoing Messages ====================

    @abstractmethod
    async def send_message(self, session_id: str, text: str,
                          metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Send a text message to the channel associated with session_id.

        Args:
            session_id: Unique session identifier
            text: Message text (may contain markdown)
            metadata: Optional adapter-specific metadata

        Returns:
            message_id: Platform-specific message ID for later reference

        Raises:
            AdapterError: If message cannot be sent
        """
        pass

    @abstractmethod
    async def edit_message(self, session_id: str, message_id: str, text: str,
                          metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Edit an existing message (for live output updates).

        Args:
            session_id: Session identifier
            message_id: Message ID returned from send_message()
            text: New message text
            metadata: Optional adapter-specific metadata

        Returns:
            True if edit succeeded, False otherwise

        Note:
            Some platforms have time limits on edits (e.g., Telegram: ~48 hours).
            Return False if edit fails, daemon will send new message instead.
        """
        pass

    @abstractmethod
    async def send_file(self, session_id: str, file_path: str,
                       caption: Optional[str] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Upload and send a file to the channel.

        Args:
            session_id: Session identifier
            file_path: Local path to file
            caption: Optional caption/description
            metadata: Optional adapter-specific metadata

        Returns:
            message_id: Message ID of the file message

        Raises:
            AdapterError: If file cannot be sent
        """
        pass

    # ==================== Channel Management ====================

    @abstractmethod
    async def create_channel(self, session_id: str, title: str,
                           metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a new channel/topic/thread for the session.

        Args:
            session_id: Session identifier
            title: Channel title (e.g., "[Mac] debugging")
            metadata: Optional adapter-specific metadata

        Returns:
            channel_id: Platform-specific channel identifier

        Raises:
            AdapterError: If channel cannot be created

        Note:
            Store channel_id in session's adapter_metadata for routing.
        """
        pass

    @abstractmethod
    async def update_channel_title(self, channel_id: str, title: str) -> bool:
        """
        Update the title of an existing channel.

        Args:
            channel_id: Channel identifier returned from create_channel()
            title: New title (may include status emoji)

        Returns:
            True if update succeeded, False otherwise
        """
        pass

    @abstractmethod
    async def set_channel_status(self, channel_id: str, status: str) -> bool:
        """
        Update status indicator in channel title.

        Args:
            channel_id: Channel identifier
            status: Status string, one of:
                - 'active' (🟢)
                - 'waiting' (🟡)
                - 'slow' (🟠)
                - 'stalled' (🔴)
                - 'idle' (⏸️)
                - 'dead' (❌)

        Returns:
            True if update succeeded, False otherwise

        Note:
            Adapter should append emoji to existing title.
        """
        pass

    @abstractmethod
    async def delete_channel(self, channel_id: str) -> bool:
        """
        Delete/close a channel (if supported by platform).

        Args:
            channel_id: Channel identifier

        Returns:
            True if deleted, False if not supported or failed
        """
        pass

    # ==================== Device Detection ====================

    @abstractmethod
    async def get_device_type(self, user_context: Any) -> str:
        """
        Attempt to detect the device type from user context.

        Args:
            user_context: Platform-specific user/message context

        Returns:
            Device type: 'mobile', 'tablet', 'desktop', or 'unknown'

        Note:
            Return 'unknown' if detection not possible. Daemon will use default.
        """
        pass

    # ==================== Callback Registration ====================

    def on_message(self, callback: Callable[[str, str, Dict], None]) -> None:
        """
        Register callback for incoming text messages.

        Callback signature:
            async def callback(session_id: str, text: str, context: Dict) -> None

        Args:
            callback: Async function to call when message received
        """
        self._message_callbacks.append(callback)

    def on_file(self, callback: Callable[[str, str, Dict], None]) -> None:
        """
        Register callback for incoming file uploads.

        Callback signature:
            async def callback(session_id: str, file_path: str, context: Dict) -> None

        Args:
            callback: Async function to call when file received
        """
        self._file_callbacks.append(callback)

    def on_voice(self, callback: Callable[[str, str, Dict], None]) -> None:
        """
        Register callback for incoming voice messages.

        Callback signature:
            async def callback(session_id: str, audio_path: str, context: Dict) -> None

        Args:
            callback: Async function to call when voice message received
        """
        self._voice_callbacks.append(callback)

    def on_command(self, callback: Callable[[str, str, list, Dict], None]) -> None:
        """
        Register callback for bot commands.

        Callback signature:
            async def callback(command: str, args: List[str], context: Dict) -> None

        Args:
            callback: Async function to call when command received

        Example:
            /new-session → callback('new-session', [], context)
            /resize large → callback('resize', ['large'], context)
        """
        self._command_callbacks.append(callback)

    # ==================== Helper Methods ====================

    async def _emit_message(self, session_id: str, text: str, context: Dict) -> None:
        """Internal: Emit message event to all registered callbacks"""
        for callback in self._message_callbacks:
            await callback(session_id, text, context)

    async def _emit_file(self, session_id: str, file_path: str, context: Dict) -> None:
        """Internal: Emit file event to all registered callbacks"""
        for callback in self._file_callbacks:
            await callback(session_id, file_path, context)

    async def _emit_voice(self, session_id: str, audio_path: str, context: Dict) -> None:
        """Internal: Emit voice event to all registered callbacks"""
        for callback in self._voice_callbacks:
            await callback(session_id, audio_path, context)

    async def _emit_command(self, command: str, args: list, context: Dict) -> None:
        """Internal: Emit command event to all registered callbacks"""
        for callback in self._command_callbacks:
            await callback(command, args, context)


class AdapterError(Exception):
    """Base exception for adapter errors"""
    pass
```

---

## Adapter → Daemon Communication (Events)

Adapters communicate with the daemon by invoking registered callbacks when events occur (incoming messages, files, commands).

### Event Flow

1. **Incoming Message** (user sends text in a session topic):
   ```python
   # In TelegramAdapter
   async def handle_message(self, update, context):
       session_id = self._get_session_id_from_topic(update.message.message_thread_id)
       text = update.message.text
       user_context = {
           'user_id': update.effective_user.id,
           'message_id': update.message.message_id,
           'device': await self.get_device_type(update)
       }

       # Emit to daemon
       await self._emit_message(session_id, text, user_context)
   ```

2. **Incoming Command** (user sends `/new-session` in General topic):
   ```python
   # In TelegramAdapter
   async def handle_command(self, update, context):
       command = update.message.text[1:]  # Strip leading '/'
       args = command.split()[1:]  # Parse arguments
       command_name = command.split()[0]

       user_context = {
           'user_id': update.effective_user.id,
           'chat_id': update.effective_chat.id,
           'message_thread_id': update.message.message_thread_id
       }

       # Emit to daemon
       await self._emit_command(command_name, args, user_context)
   ```

3. **Incoming File**:
   ```python
   # In TelegramAdapter
   async def handle_file(self, update, context):
       session_id = self._get_session_id_from_topic(update.message.message_thread_id)

       # Download file
       file = await update.message.document.get_file()
       file_path = await file.download_to_drive()

       user_context = {
           'filename': update.message.document.file_name,
           'size': update.message.document.file_size,
           'mime_type': update.message.document.mime_type
       }

       # Emit to daemon
       await self._emit_file(session_id, file_path, user_context)
   ```

4. **Incoming Voice**:
   ```python
   # In TelegramAdapter
   async def handle_voice(self, update, context):
       session_id = self._get_session_id_from_topic(update.message.message_thread_id)

       # Download voice message
       voice = await update.message.voice.get_file()
       audio_path = await voice.download_to_drive()

       user_context = {
           'duration': update.message.voice.duration,
           'mime_type': update.message.voice.mime_type
       }

       # Emit to daemon
       await self._emit_voice(session_id, audio_path, user_context)
   ```

---

## Session ID ↔ Channel ID Mapping

The core daemon uses `session_id` (UUID) to identify sessions internally. Adapters map these to platform-specific `channel_id` (Telegram topic_id, Slack channel_id, etc.).

**Storage in SQLite**:
```sql
sessions (
    session_id TEXT PRIMARY KEY,  -- "550e8400-e29b-41d4-a716-446655440000"
    adapter_type TEXT,              -- "telegram"
    adapter_metadata TEXT           -- JSON: {"channel_id": "123456", "chat_id": "-1001234567890"}
)
```

**Adapter Responsibilities**:
- Store `channel_id` in `adapter_metadata` when creating channel
- Look up `session_id` from incoming message's channel
- Provide mapping helper methods:

```python
class TelegramAdapter(BaseAdapter):
    async def _get_session_id_from_topic(self, topic_id: int) -> Optional[str]:
        """Query database for session_id by topic_id in adapter_metadata"""
        query = """
            SELECT session_id FROM sessions
            WHERE adapter_type = 'telegram'
            AND json_extract(adapter_metadata, '$.topic_id') = ?
        """
        result = await self.db.execute(query, (topic_id,))
        row = await result.fetchone()
        return row[0] if row else None

    async def _get_topic_id_from_session(self, session_id: str) -> Optional[int]:
        """Query database for topic_id by session_id"""
        query = """
            SELECT adapter_metadata FROM sessions
            WHERE session_id = ? AND adapter_type = 'telegram'
        """
        result = await self.db.execute(query, (session_id,))
        row = await result.fetchone()
        if row:
            metadata = json.loads(row[0])
            return metadata.get('topic_id')
        return None
```

---

## Daemon Core Logic

### Initialization

```python
class TeleClaudeDaemon:
    def __init__(self, config):
        self.config = config
        self.session_manager = SessionManager(config.db_path)
        self.terminal_bridge = TerminalBridge()
        self.recorder_manager = RecorderManager()
        self.adapters = []

        # Initialize adapters
        if config.telegram.enabled:
            telegram_adapter = TelegramAdapter(config.telegram)
            self.adapters.append(telegram_adapter)

        # Register callbacks
        for adapter in self.adapters:
            adapter.on_message(self.handle_message)
            adapter.on_file(self.handle_file)
            adapter.on_voice(self.handle_voice)
            adapter.on_command(self.handle_command)

    async def start(self):
        # Start all adapters
        for adapter in self.adapters:
            await adapter.start()

        # Reconnect to existing tmux sessions
        await self.reconnect_sessions()

        # Start output streaming loops
        await self.start_output_streamers()

    async def handle_message(self, session_id: str, text: str, context: Dict):
        """Handle incoming text message from any adapter"""
        session = await self.session_manager.get_session(session_id)
        if not session:
            return

        # Send to terminal
        await self.terminal_bridge.send_keys(session.tmux_session_name, text + "\n")

        # Update last activity
        await self.session_manager.update_last_activity(session_id)

        # Increment command count (for title generation)
        session.command_count += 1
        if session.command_count == 5:
            await self.generate_session_title(session_id)

    async def handle_command(self, command: str, args: list, context: Dict):
        """Handle bot commands from any adapter"""
        if command == 'new-session':
            await self.create_session(context)
        elif command == 'close-session':
            session_id = context.get('session_id')
            await self.close_session(session_id)
        elif command == 'send-text':
            duration = args[0] if args else '20m'
            await self.send_text_recording(context['session_id'], duration)
        # ... etc

    async def handle_file(self, session_id: str, file_path: str, context: Dict):
        """Handle file upload from any adapter"""
        # Move to upload directory
        dest = await self.file_handler.save_file(file_path, context.get('filename'))

        # Send confirmation via adapter
        session = await self.session_manager.get_session(session_id)
        adapter = self._get_adapter(session.adapter_type)
        await adapter.send_message(
            session_id,
            f"File saved: {dest}",
            metadata={'reply_to': context.get('message_id')}
        )

    async def handle_voice(self, session_id: str, audio_path: str, context: Dict):
        """Handle voice message from any adapter"""
        session = await self.session_manager.get_session(session_id)
        adapter = self._get_adapter(session.adapter_type)

        # Show "transcribing" message
        msg_id = await adapter.send_message(session_id, "🎤 Transcribing...")

        # Transcribe
        text = await self.voice_handler.transcribe(audio_path)

        # Show transcription
        await adapter.edit_message(session_id, msg_id, f"🎤 Transcribed: \"{text}\"")

        # Send to terminal
        await self.terminal_bridge.send_keys(session.tmux_session_name, text + "\n")

    def _get_adapter(self, adapter_type: str) -> BaseAdapter:
        """Get adapter instance by type"""
        for adapter in self.adapters:
            if adapter.config['type'] == adapter_type:
                return adapter
        raise ValueError(f"Adapter not found: {adapter_type}")
```

### Output Streaming

```python
class OutputStreamer:
    def __init__(self, session_id: str, daemon: TeleClaudeDaemon):
        self.session_id = session_id
        self.daemon = daemon
        self.last_output = ""
        self.last_message_id = None
        self.start_time = None
        self.running = True

    async def run(self):
        """Poll tmux output and send to adapter"""
        session = await self.daemon.session_manager.get_session(self.session_id)
        adapter = self.daemon._get_adapter(session.adapter_type)

        while self.running:
            # Capture new output
            output = await self.daemon.terminal_bridge.capture_pane(session.tmux_session_name)

            if output != self.last_output:
                new_output = output[len(self.last_output):]

                # Format output
                formatted = self._format_output(new_output)

                # Check if large output
                if self._is_large_output(formatted):
                    formatted = self._truncate_output(formatted)

                # Send or edit message (hybrid mode)
                elapsed = time.time() - (self.start_time or time.time())
                if elapsed < 5 and self.last_message_id:
                    # Edit mode
                    success = await adapter.edit_message(
                        self.session_id,
                        self.last_message_id,
                        formatted
                    )
                    if not success:
                        # Edit failed, send new message
                        self.last_message_id = await adapter.send_message(
                            self.session_id,
                            formatted
                        )
                else:
                    # Send new message
                    self.last_message_id = await adapter.send_message(
                        self.session_id,
                        formatted
                    )
                    self.start_time = time.time()

                self.last_output = output

            await asyncio.sleep(1.5)  # Poll interval
```

---

## Example: Telegram Adapter Implementation

See `teleclaude/adapters/telegram_adapter.py` (to be implemented in Phase 6).

Key points:
- Use `python-telegram-bot` library
- Store `topic_id` and `chat_id` in adapter_metadata
- Map Telegram topics to sessions
- Handle rate limiting
- Implement all abstract methods

---

## Example: WhatsApp Adapter (Future)

```python
class WhatsAppAdapter(BaseAdapter):
    """
    WhatsApp Business API adapter.

    Mapping:
    - Sessions → separate group chats (one per session)
    - No native topic support, so each session = new group
    """

    async def create_channel(self, session_id, title, metadata=None):
        # Create WhatsApp group
        group_id = await self.wa_client.create_group(title)
        return group_id

    async def send_message(self, session_id, text, metadata=None):
        # Look up group_id from session adapter_metadata
        group_id = await self._get_group_id(session_id)
        msg_id = await self.wa_client.send_message(group_id, text)
        return msg_id

    # ... implement other methods
```

---

## Testing Adapters

### Mock Adapter for Testing

```python
class MockAdapter(BaseAdapter):
    """In-memory adapter for testing without external services"""

    def __init__(self, config):
        super().__init__(config)
        self.messages = []
        self.channels = {}

    async def start(self):
        pass

    async def send_message(self, session_id, text, metadata=None):
        msg_id = str(len(self.messages))
        self.messages.append({'id': msg_id, 'session': session_id, 'text': text})
        return msg_id

    async def edit_message(self, session_id, message_id, text, metadata=None):
        for msg in self.messages:
            if msg['id'] == message_id:
                msg['text'] = text
                return True
        return False

    async def create_channel(self, session_id, title, metadata=None):
        channel_id = f"channel_{len(self.channels)}"
        self.channels[channel_id] = {'title': title, 'session': session_id}
        return channel_id

    # ... minimal implementation of other methods

    # Test helpers
    def simulate_message(self, session_id, text):
        """Simulate incoming message from user"""
        asyncio.create_task(self._emit_message(session_id, text, {}))

    def get_messages(self, session_id):
        """Get all messages sent to session"""
        return [m for m in self.messages if m['session'] == session_id]
```

---

## Error Handling

Adapters should raise `AdapterError` for any failures:

```python
class AdapterError(Exception):
    """Base class for adapter errors"""
    pass

class AdapterConnectionError(AdapterError):
    """Raised when adapter cannot connect to platform"""
    pass

class AdapterRateLimitError(AdapterError):
    """Raised when rate limit is hit"""
    pass

class AdapterAuthError(AdapterError):
    """Raised when authentication fails"""
    pass
```

The daemon should catch these and:
1. Log the error
2. Retry with exponential backoff (for transient errors)
3. Alert user if unrecoverable

---

## Configuration

Each adapter receives its configuration from `.env` and `config.yml`:

```yaml
adapters:
  telegram:
    enabled: true
    bot_token: ${TELEGRAM_BOT_TOKEN}
    supergroup_id: ${TELEGRAM_SUPERGROUP_ID}
    user_whitelist: ${TELEGRAM_USER_IDS}
    rate_limit:
      messages_per_second: 30
      edits_per_second: 5

  whatsapp:
    enabled: false
    api_key: ${WHATSAPP_API_KEY}
    phone_number: ${WHATSAPP_PHONE_NUMBER}
```

---

## Summary

The adapter API provides:

1. **Clear separation of concerns**: Core daemon handles terminal logic, adapters handle messaging
2. **Extensibility**: Easy to add new platforms without touching core code
3. **Testability**: Mock adapters for testing without external dependencies
4. **Flexibility**: Each adapter can leverage platform-specific features while maintaining common interface

Next steps: Implement `TelegramAdapter` in Phase 6 of the implementation plan.

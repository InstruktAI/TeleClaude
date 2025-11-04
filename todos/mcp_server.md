# MCP Server Implementation for Multi-Computer AI-to-AI Communication

## Overview

Implement MCP (Model Context Protocol) server in TeleClaude daemon to enable Claude Code running on different computers to communicate with each other via Telegram as a distributed message bus.

**Core Concept:** Each daemon exposes an MCP server that allows Claude Code to:
1. Discover other computers in the TeleClaude network
2. Send commands/messages to remote computers' Claude Code instances
3. Receive streaming responses as remote AI processes commands

**Architecture Principles:**
- ✅ Fully decentralized (no central coordinator)
- ✅ Telegram as message bus (reliable, persistent, observable)
- ✅ Per-computer bot tokens (each daemon independent)
- ✅ Topic-based routing (pattern matching determines message flow)
- ✅ Streaming responses (real-time output delivery)

---

## Topic Naming Convention

### Pattern: `$InitiatorComp > $TargetComp - {title}`

**Examples:**
- `$macbook > $workstation - Check logs` = macbook's AI asking workstation's AI to check logs
- `$server > $macbook - Install deps` = server's AI asking macbook's AI to install dependencies
- `$Comp1 > $Comp2 - Debug issue` = generic example

### Why This Pattern?

1. **Self-describing**: Topic name immediately shows initiator, target, and purpose
2. **Easy pattern matching**: Daemons can filter topics with simple regex
3. **Human readable**: Clear in Telegram UI what's happening
4. **AI-generated indicator**: `$` prefix signals AI-originated (vs human `/new_session My Project`)
5. **Unique per task**: Title allows multiple concurrent sessions between same computers
6. **Traceable**: Description stored in DB helps AI remember why session was created

---

## Pattern Matching Rules for Daemons

Each daemon must identify which topics and messages it should respond to:

### 1. Outgoing Topics (Initiated by this computer)

**Pattern:** `${self.computer_name} > $* - *`

**Meaning:** This daemon initiated these AI-to-AI sessions and should:
- Poll for responses from remote computers
- Stream responses back to local MCP client (Claude Code)

**Examples:**
```python
self.computer_name = "macbook"

# Topics this daemon should poll for responses:
"$macbook > $workstation - Check logs"  ✅ Match (I initiated)
"$macbook > $server - Install deps"     ✅ Match (I initiated)
"$workstation > $macbook - Debug"       ❌ No match (incoming, not outgoing)
"macbook studio"                        ❌ No match (human session, not AI-to-AI)
```

### 2. Incoming Topics (Directed at this computer)

**Pattern:** `$* > $${self.computer_name} - *`

**Meaning:** Remote daemon initiated this session targeting this computer. This daemon should:
- Monitor for `/claude_resume` command
- Start Claude Code in the session
- Forward subsequent messages to Claude Code
- Stream Claude Code's output back to Telegram topic

**Examples:**
```python
self.computer_name = "workstation"

# Topics this daemon should respond to:
"$macbook > $workstation - Check logs"    ✅ Match (incoming request for me)
"$server > $workstation - Install deps"   ✅ Match (incoming request for me)
"$workstation > $macbook - Debug"         ❌ No match (outgoing, not incoming)
"$laptop > $server - Status"              ❌ No match (not for me)
```

### 3. Human Sessions (Standard Interactive)

**Pattern:** Does NOT start with `$`

**Meaning:** Human-created session (via `/new_session My Project`). Handle normally:
- Poll output for display in Telegram
- Forward user messages to tmux session
- Standard TeleClaude behavior

**Examples:**
```
"macbook studio"                        ✅ Human session
"My Project"                            ✅ Human session
"$macbook > $workstation - Check logs"  ❌ AI-to-AI session
```

### Pattern Matching Implementation

```python
# In telegram_adapter.py or mcp_server.py

def classify_topic(self, topic_name: str) -> str:
    """Classify topic type based on naming pattern.

    Returns:
        'outgoing_ai' - AI-to-AI session initiated by this computer
        'incoming_ai' - AI-to-AI session targeting this computer
        'human' - Human interactive session
        'unknown' - Does not match any pattern
    """
    # AI-to-AI pattern: $Initiator > $Target - Title
    ai_pattern = r'^\$(\w+) > \$(\w+) - (.+)$'
    match = re.match(ai_pattern, topic_name)

    if match:
        initiator = match.group(1)
        target = match.group(2)
        title = match.group(3)

        if initiator == self.computer_name:
            return 'outgoing_ai'
        elif target == self.computer_name:
            return 'incoming_ai'
        else:
            return 'unknown'  # Not for us

    # No $ prefix = human session
    if not topic_name.startswith('$'):
        return 'human'

    return 'unknown'


def should_poll_for_mcp_responses(self, topic_name: str) -> bool:
    """Check if daemon should poll this topic for MCP streaming responses."""
    return self.classify_topic(topic_name) == 'outgoing_ai'


def should_handle_incoming_request(self, topic_name: str) -> bool:
    """Check if daemon should handle incoming AI-to-AI requests in this topic."""
    return self.classify_topic(topic_name) == 'incoming_ai'
```

---

## Computer Registry with Heartbeat Mechanism

### Overview

**Dynamic computer discovery** via shared Telegram topic with periodic heartbeats. No manual configuration lists needed.

**Architecture:**

1. **Shared topic:** `# Online Now` (created by first daemon)
2. **Each daemon on startup:**
   - Posts ONE status message to `# Online Now` topic
   - Stores its message ID
3. **Heartbeat loop (every 30s):**
   - Each daemon **edits its own message** with updated timestamp
   - This is the "heartbeat" that proves it's alive
4. **Registry polling loop (every 30s):**
   - Each daemon polls `# Online Now` topic
   - Parses all messages to extract computer names + timestamps
   - Builds **in-memory list** of computers
   - Marks as offline if `last_seen > 60s ago`

### Message Format (Simple Single-Line)

Each daemon posts ONE message in `# Online Now` topic:

```
macbook - last seen at 2025-11-04 15:30:45
```

That's it! Simple, parseable, easy to read in Telegram UI.

### Implementation: ComputerRegistry Class

**New file:** `teleclaude/core/computer_registry.py`

```python
"""Computer registry with heartbeat mechanism for dynamic discovery."""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ComputerRegistry:
    """Manages computer discovery via Telegram heartbeat topic.

    Each daemon:
    - Posts status message to registry topic
    - Updates message every 30s (heartbeat)
    - Polls registry to discover other computers
    - Builds in-memory list of online/offline computers
    """

    def __init__(
        self,
        telegram_adapter: Any,
        computer_name: str,
        bot_username: str,
        config: dict
    ):
        self.telegram_adapter = telegram_adapter
        self.computer_name = computer_name
        self.bot_username = bot_username
        self.config = config

        # In-memory state
        self.computers = {}  # {computer_name: {status, last_seen, bot_username, ...}}
        self.registry_topic_id: Optional[int] = None
        self.my_message_id: Optional[int] = None

        # Configuration
        self.heartbeat_interval = 30  # Update status every 30s
        self.poll_interval = 30  # Poll registry every 30s
        self.offline_threshold = 60  # Mark offline after 60s of no heartbeat

    async def start(self):
        """Start registry: post status + start background loops."""
        logger.info("Starting computer registry for %s", self.computer_name)

        # Find or create registry topic
        self.registry_topic_id = await self._get_or_create_registry_topic()

        # Post initial status
        await self._update_my_status()

        # Immediately poll once to get current state
        await self._refresh_computer_list()

        # Start background loops
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._poll_registry_loop())

        logger.info(
            "Computer registry started: topic_id=%s, discovered %d computers",
            self.registry_topic_id,
            len(self.computers)
        )

    async def _get_or_create_registry_topic(self) -> int:
        """Find or create the '# Online Now' topic."""
        registry_name = "# Online Now"

        # Try to find existing topic
        topics = await self.telegram_adapter.get_all_topics()
        for topic in topics:
            if topic.name == registry_name:
                logger.info("Found existing registry topic: %s", topic.id)
                return topic.id

        # Create new topic
        logger.info("Creating new registry topic: %s", registry_name)
        topic = await self.telegram_adapter.create_topic(registry_name)
        return topic.message_thread_id

    async def _heartbeat_loop(self):
        """Edit our status message every N seconds (heartbeat)."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                await self._update_my_status()
                logger.debug("Heartbeat sent for %s", self.computer_name)
            except Exception as e:
                logger.error("Heartbeat update failed: %s", e)

    async def _poll_registry_loop(self):
        """Poll registry topic and refresh in-memory computer list every N seconds."""
        while True:
            await asyncio.sleep(self.poll_interval)
            try:
                await self._refresh_computer_list()
                logger.debug(
                    "Registry polled: %d total, %d online",
                    len(self.computers),
                    len([c for c in self.computers.values() if c["status"] == "online"])
                )
            except Exception as e:
                logger.error("Registry poll failed: %s", e)

    async def _update_my_status(self):
        """Post or edit our status message in registry topic."""
        text = self._format_status_message()

        if self.my_message_id is None:
            # First time - post new message
            msg = await self.telegram_adapter.send_message_to_topic(
                topic_id=self.registry_topic_id,
                text=text,
                parse_mode="Markdown"
            )
            self.my_message_id = msg.message_id
            logger.info("Posted initial status to registry: message_id=%s", self.my_message_id)
        else:
            # Update existing message (heartbeat)
            await self.telegram_adapter.edit_message(
                message_id=self.my_message_id,
                topic_id=self.registry_topic_id,
                text=text,
                parse_mode="Markdown"
            )

    def _format_status_message(self) -> str:
        """Format status message for registry (simple single line)."""
        return f"{self.computer_name} - last seen at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    async def _refresh_computer_list(self):
        """Poll '# Online Now' topic and parse all computer statuses."""
        messages = await self.telegram_adapter.get_topic_messages(
            topic_id=self.registry_topic_id,
            limit=100  # Support up to 100 computers
        )

        now = datetime.now()

        for msg in messages:
            try:
                # Parse: "computer_name - last seen at 2025-11-04 15:30:45"
                match = re.match(r'^(\w+) - last seen at ([\d\-: ]+)$', msg.text.strip())
                if not match:
                    continue

                computer_name = match.group(1)
                last_seen_str = match.group(2)
                last_seen = datetime.strptime(last_seen_str, '%Y-%m-%d %H:%M:%S')

                # Determine online status (< offline_threshold = online)
                seconds_ago = (now - last_seen).total_seconds()
                is_online = seconds_ago < self.offline_threshold

                # Extract bot_username from message sender
                # msg.from_user.username should be "teleclaude_macbook_bot"
                bot_username = f"@{msg.from_user.username}" if msg.from_user else None

                # Update in-memory registry
                self.computers[computer_name] = {
                    "name": computer_name,
                    "bot_username": bot_username,
                    "status": "online" if is_online else "offline",
                    "last_seen": last_seen,
                    "last_seen_ago": f"{int(seconds_ago)}s ago"
                }

            except Exception as e:
                logger.warning("Failed to parse registry message: %s", e)

    # === Public API for MCP tools and daemon ===

    def get_online_computers(self) -> list[dict]:
        """Get list of currently online computers (for teleclaude__list).

        Returns:
            List of dicts with computer info, sorted by name.
        """
        computers = [
            c for c in self.computers.values()
            if c["status"] == "online"
        ]
        return sorted(computers, key=lambda c: c["name"])

    def get_all_computers(self) -> list[dict]:
        """Get all computers (online + offline), sorted by name."""
        return sorted(self.computers.values(), key=lambda c: c["name"])

    def is_computer_online(self, computer_name: str) -> bool:
        """Check if specific computer is currently online."""
        return (
            computer_name in self.computers
            and self.computers[computer_name]["status"] == "online"
        )

    def get_computer_info(self, computer_name: str) -> Optional[dict]:
        """Get info for specific computer (or None if not found)."""
        return self.computers.get(computer_name)
```

### Integration with Daemon

**In `daemon.py` startup:**

```python
from teleclaude.core.computer_registry import ComputerRegistry

class TeleClaudeDaemon:
    def __init__(self, config_path: str, env_path: str):
        # ... existing init ...

        # Initialize computer registry
        self.computer_registry = ComputerRegistry(
            telegram_adapter=self.telegram_adapter,
            computer_name=self.config["computer"]["name"],
            bot_username=self.config["computer"]["bot_username"],
            config=self.config
        )

    async def start(self):
        # ... existing startup ...

        # Start computer registry (heartbeat + polling)
        await self.computer_registry.start()

        # ... rest of startup ...
```

### Edge Cases Handled

1. **Daemon crash:** Heartbeat stops → marked offline after 60s
2. **Daemon restart:** Posts new status → immediately back online
3. **Registry topic doesn't exist:** First daemon creates it
4. **Stale messages:** Ignored if `last_seen > 60s ago`
5. **Clock skew:** Use message edit time as fallback (TODO: enhancement)
6. **Multiple daemons same computer:** Each has unique bot_username, no conflict

### Benefits

✅ **Dynamic discovery** - No manual config lists, computers auto-discovered
✅ **In-memory state** - Fast lookups, no database queries
✅ **Automatic offline detection** - Stale heartbeats (>60s) = offline
✅ **Resilient** - Each daemon independent, no coordination needed
✅ **Observable** - Registry topic visible in Telegram UI for debugging
✅ **Scalable** - Supports 100+ computers (topic message limit)

---

## Dual-Mode Output Architecture for AI-to-AI Sessions

### Problem: Sliding Window Data Loss

**Context:** TeleClaude edits messages in-place with last ~3400 chars (sliding window). This works for humans but creates race conditions for AI-to-AI communication:

```
t=0s:  Comp2 sends message with chars 0-3400
t=1s:  Comp2 edits message with chars 1000-4400  [chars 0-999 lost]
t=2s:  Comp1 polls, sees only chars 1000-4400    [missed chars 0-999]
```

**Solution:** Context-aware output modes based on session type.

### Mode 1: Human Sessions (Existing Behavior)

**When:** Topic does NOT match `$X > $Y - {title}` pattern (standard interactive sessions)

**Behavior:**
- Edit same message for clean UX
- Truncate to ~3400 chars (sliding window)
- Download button for full output
- Polling optimized for human readability

**Why:** Humans want clean, real-time UI with edited messages showing latest state.

### Mode 2: AI-to-AI Sessions (New Behavior)

**When:** Topic matches `$X > $Y - {title}` pattern (AI-to-AI communication)

**Behavior:**
- Send **sequential messages** (no editing, no loss)
- Each message = chunk up to adapter's max message length
- Include chunk markers for ordering: `[Chunk N/Total]`
- Include completion marker: `[Output Complete]`
- No truncation - all output preserved

**Why:** AI consumers need every byte of output for processing. Data loss breaks automation.

### Message Format for AI Sessions

```
Message 1:
```sh
[first 3400 chars of output]
```
[Chunk 1/3]

Message 2:
```sh
[next 3400 chars of output]
```
[Chunk 2/3]

Message 3:
```sh
[remaining output]
```
[Chunk 3/3]

Message 4:
[Output Complete]
```

**Note:** Chunk size and polling interval are **adapter-determined** (not config values). Each adapter knows its platform's limits (Telegram: 4096 chars, WhatsApp: different, etc.).

### Implementation: Session Type Detection

**File:** `teleclaude/core/polling_coordinator.py`

```python
def _is_ai_to_ai_session(topic_name: str) -> bool:
    """Check if topic matches AI-to-AI pattern: $X > $Y - {title}"""
    return bool(re.match(r'^\$\w+ > \$\w+ - .+$', topic_name))


async def poll_and_send_output(
    session_id: str,
    tmux_session_name: str,
    session_manager: SessionManager,
    output_poller: OutputPoller,
    get_adapter_for_session: Callable[[str], Awaitable[Any]],
    get_output_file: Callable[[str], Path],
) -> None:
    """Poll terminal output and send to chat adapter."""

    # ... existing setup code ...

    # NEW: Detect session type
    session = await session_manager.get_session(session_id)
    is_ai_session = _is_ai_to_ai_session(session.topic_name)

    try:
        async for event in output_poller.poll(...):
            if isinstance(event, OutputChanged):
                if is_ai_session:
                    # AI mode: Send sequential chunks (no editing)
                    await _send_output_chunks_ai_mode(
                        event.session_id,
                        adapter,
                        event.output,
                        session_manager,
                    )
                else:
                    # Human mode: Edit same message (current behavior)
                    await output_message_manager.send_output_update(
                        event.session_id,
                        adapter,
                        event.output,
                        event.started_at,
                        event.last_changed_at,
                        session_manager,
                        max_message_length=3800,
                    )
            # ... existing event handling for IdleDetected, ProcessExited ...
```

### Chunked Output Sender for AI Mode

```python
async def _send_output_chunks_ai_mode(
    session_id: str,
    adapter: BaseAdapter,
    full_output: str,
    session_manager: SessionManager,
) -> None:
    """Send output as sequential chunks for AI consumption.

    Uses adapter's max_message_length (platform-specific).
    No editing - each chunk is a new message.
    """
    # Get adapter's platform-specific max message length
    chunk_size = adapter.get_max_message_length() - 100  # Reserve for markdown + markers

    # Split output into chunks
    chunks = [full_output[i:i+chunk_size]
              for i in range(0, len(full_output), chunk_size)]

    # Send each chunk as new message
    for idx, chunk in enumerate(chunks, 1):
        # Format with sequence marker
        message = f"```sh\n{chunk}\n```\n[Chunk {idx}/{len(chunks)}]"

        # Send as NEW message (don't edit)
        await adapter.send_message(session_id, message)

        # Small delay to preserve order (Telegram API constraint)
        await asyncio.sleep(0.1)

    # Mark completion (MCP streaming loop will detect and stop)
    await adapter.send_message(session_id, "[Output Complete]")
```

### Comp1's MCP Polling Logic

```python
async def teleclaude__send(self, target: str, message: str) -> AsyncIterator[str]:
    """Send message to remote AI and stream response."""

    # ... setup code (create topic, wake Claude, send message) ...

    # STREAMING PHASE: Poll for sequential chunk messages
    last_message_id = None
    chunk_buffer = []

    while True:
        # Poll for NEW messages only (adapter determines interval)
        messages = await self._get_topic_messages_since(
            topic_id,
            after_message_id=last_message_id,
            poll_interval=self.telegram_adapter.get_ai_session_poll_interval()
        )

        for msg in messages:
            last_message_id = msg.message_id

            # Check if completion marker
            if "[Output Complete]" in msg.text:
                # Yield final buffer and return
                if chunk_buffer:
                    yield ''.join(chunk_buffer)
                return

            # Extract chunk content (strip markdown and markers)
            content = self._extract_chunk_content(msg.text)
            chunk_buffer.append(content)

            # Yield accumulated chunks periodically
            if len(chunk_buffer) >= 5:  # Batch for efficiency
                yield ''.join(chunk_buffer)
                chunk_buffer.clear()

        # Use adapter-determined poll interval
        await asyncio.sleep(self.telegram_adapter.get_ai_session_poll_interval())

def _extract_chunk_content(self, message_text: str) -> str:
    """Extract actual output from chunk message."""
    # Remove markdown code fences
    content = message_text.replace('```sh', '').replace('```', '')
    # Remove chunk markers
    content = re.sub(r'\[Chunk \d+/\d+\]', '', content)
    return content.strip()
```

### Adapter Interface Additions

**File:** `teleclaude/adapters/base_adapter.py`

```python
class BaseAdapter(ABC):
    """Base adapter interface for all messaging platforms."""

    # ... existing abstract methods ...

    def get_max_message_length(self) -> int:
        """Get platform's max message length for chunking.

        Returns:
            Maximum characters per message (platform-specific).
            Used for AI-to-AI output chunking.
        """
        raise NotImplementedError

    def get_ai_session_poll_interval(self) -> float:
        """Get polling interval for AI-to-AI sessions (seconds).

        Returns:
            Optimal polling frequency for this platform.
            Faster than human mode for real-time AI communication.
        """
        raise NotImplementedError
```

**File:** `teleclaude/adapters/telegram_adapter.py`

```python
class TelegramAdapter(BaseAdapter):
    # ... existing methods ...

    def get_max_message_length(self) -> int:
        """Telegram's max message length is 4096 chars."""
        return 4096

    def get_ai_session_poll_interval(self) -> float:
        """Telegram AI sessions poll faster than human sessions.

        Returns:
            0.5 seconds for real-time AI communication.
        """
        return 0.5
```

### Benefits

1. **No data loss:** Every byte sent as discrete message, no sliding window
2. **Real-time streaming:** Comp1 yields chunks as they arrive
3. **Reliable ordering:** Chunk markers + message IDs preserve sequence
4. **Fault tolerance:** If Comp1 misses a poll, messages persist in topic history
5. **Clean separation:** Human sessions keep clean UX, AI sessions optimize for reliability
6. **Platform agnostic:** Adapter determines optimal chunk size and poll interval
7. **Simple completion detection:** `[Output Complete]` marker is explicit, no heuristics

### Edge Cases Handled

1. **Network delays:** Messages persist in topic, no loss if Comp1 briefly disconnects
2. **Out-of-order delivery:** Chunk markers allow reordering if needed
3. **Large outputs:** Chunking handles unlimited output size
4. **Comp1 crashes mid-stream:** Can resume from last_message_id on restart
5. **Comp2 crashes mid-output:** ProcessExited event sends final chunk + completion marker

---

## MCP Tools Specification

### Tool 1: `teleclaude__list`

**Purpose:** Discover available computers in TeleClaude network

**Signature:**
```python
@mcp_server.tool()
async def teleclaude__list() -> list[dict]:
    """
    List all available TeleClaude computers.

    Returns:
        List of online computers with their info.

    Example return:
        [
            {
                "name": "macbook",
                "bot_username": "@teleclaude_macbook_bot",
                "status": "online",
                "last_seen_ago": "15s ago"
            },
            {
                "name": "workstation",
                "bot_username": "@teleclaude_workstation_bot",
                "status": "online",
                "last_seen_ago": "22s ago"
            }
        ]
    """
```

**Implementation:**

```python
async def teleclaude__list(self) -> list[dict]:
    """List available computers from in-memory registry."""
    # Get online computers from registry (maintained by heartbeat mechanism)
    return self.daemon.computer_registry.get_online_computers()
```

**Simple and fast!** No Telegram API calls needed - just returns in-memory state updated by background polling loop.

---

### Tool 2: `teleclaude__start_session`

**Purpose:** Start a new AI-to-AI session with a remote computer

**Signature:**
```python
@mcp_server.tool()
async def teleclaude__start_session(
    target: str,
    title: str,
    description: str
) -> dict:
    """
    Start a new AI-to-AI session with remote computer's Claude Code.

    Args:
        target: Computer name (e.g., "workstation", "server")
        title: Short title for the session (e.g., "Check logs", "Debug issue")
        description: Detailed description of why this session was created

    Returns:
        dict with:
            session_id: Session ID for use with teleclaude__send
            topic_name: Telegram topic name ($Initiator > $Target - Title)
            status: "ready" or "error"
            message: Status message

    Example usage:
        result = await mcp.call_tool("teleclaude__start_session", {
            "target": "workstation",
            "title": "Check nginx logs",
            "description": "User reported 502 errors, need to check nginx error logs for root cause"
        })
        # Returns: {"session_id": "abc123", "topic_name": "$macbook > $workstation - Check nginx logs", "status": "ready"}
    """
```

**Implementation:**
```python
async def teleclaude__start_session(self, target: str, title: str, description: str) -> dict:
    """Start new AI-to-AI session with remote computer."""

    # 1. Validate target is online
    if not self.daemon.computer_registry.is_computer_online(target):
        return {
            "status": "error",
            "message": f"Computer '{target}' is offline",
            "available": [c['name'] for c in self.daemon.computer_registry.get_online_computers()]
        }

    # 2. Create topic name
    topic_name = f"${self.computer_name} > ${target} - {title}"

    # 3. Create Telegram topic
    topic_id = await self.telegram_adapter.create_topic(topic_name)

    # 4. Create session in database with description
    session_id = str(uuid.uuid4())
    await self.session_manager.create_session(
        session_id=session_id,
        computer_name=self.computer_name,
        title=topic_name,
        tmux_session_name=f"{self.computer_name}-session-{session_id[:8]}",
        adapter_type="telegram",
        adapter_metadata={"channel_id": str(topic_id)},
        description=description  # NEW: Store why this session was created
    )

    # 5. Send /claude_resume to wake remote Claude Code
    await self.telegram_adapter.send_message(session_id, "/claude_resume")

    # 6. Wait for Claude Code ready
    await self._wait_for_claude_ready(session_id, timeout=10)

    return {
        "session_id": session_id,
        "topic_name": topic_name,
        "status": "ready",
        "message": f"Session ready with {target}"
    }
```

---

### Tool 3: `teleclaude__list_sessions`

**Purpose:** List all AI-to-AI sessions initiated by this computer

**Signature:**
```python
@mcp_server.tool()
async def teleclaude__list_sessions(
    target: Optional[str] = None
) -> list[dict]:
    """
    List AI-to-AI sessions initiated by this computer.

    Args:
        target: Optional filter by target computer name

    Returns:
        List of session info dicts with:
            session_id: Session ID
            target: Target computer name
            title: Session title
            description: Why session was created
            status: "active" or "closed"
            created_at: ISO timestamp

    Example usage:
        # List all AI sessions
        sessions = await mcp.call_tool("teleclaude__list_sessions", {})

        # List sessions with specific target
        sessions = await mcp.call_tool("teleclaude__list_sessions", {"target": "workstation"})

        # Returns: [
        #   {
        #     "session_id": "abc123",
        #     "target": "workstation",
        #     "title": "Check nginx logs",
        #     "description": "User reported 502 errors...",
        #     "status": "active",
        #     "created_at": "2025-11-04T19:30:00"
        #   }
        # ]
    """
```

**Implementation:**
```python
async def teleclaude__list_sessions(self, target: Optional[str] = None) -> list[dict]:
    """List AI-to-AI sessions initiated by this computer."""

    # Query sessions with AI-to-AI pattern from this computer
    pattern = f"${self.computer_name} > $"
    if target:
        pattern = f"${self.computer_name} > ${target} - "

    sessions = await self.session_manager.get_sessions_by_title_pattern(pattern)

    # Parse and return session info
    result = []
    for session in sessions:
        # Parse topic name: $Initiator > $Target - Title
        match = re.match(r'^\$\w+ > \$(\w+) - (.+)$', session.title)
        if match:
            result.append({
                "session_id": session.session_id,
                "target": match.group(1),
                "title": match.group(2),
                "description": session.description,  # NEW: From DB
                "status": "closed" if session.closed else "active",
                "created_at": session.created_at.isoformat()
            })

    return result
```

---

### Tool 4: `teleclaude__send`

**Purpose:** Send message to an existing AI-to-AI session and stream response

**Signature:**
```python
@mcp_server.tool()
async def teleclaude__send(
    session_id: str,
    message: str
) -> AsyncIterator[str]:
    """
    Send message to existing AI-to-AI session and stream response.

    Args:
        session_id: Session ID from teleclaude__start_session
        message: Message/command to send to remote Claude Code

    Yields:
        str: Response chunks from remote Claude Code as they arrive

    Example usage:
        # Start session first
        session = await mcp.call_tool("teleclaude__start_session", {
            "target": "workstation",
            "title": "Check logs",
            "description": "Debug 502 errors"
        })

        # Send commands to session
        async for chunk in mcp.call_tool("teleclaude__send", {
            "session_id": session["session_id"],
            "message": "tail -100 /var/log/nginx/error.log"
        }):
            print(chunk, end='')
    """
```

**Implementation Flow:**

```python
async def teleclaude__send(self, session_id: str, message: str) -> AsyncIterator[str]:
    """Send to remote AI session and stream response chunks."""

    # === PHASE 1: VALIDATE SESSION ===

    # 1. Get session from database
    session = await self.session_manager.get_session(session_id)
    if not session:
        yield f"[Error: Session '{session_id}' not found]"
        return

    # 2. Verify this is an AI-to-AI session
    if not _is_ai_to_ai_session(session.title):
        yield f"[Error: Session '{session_id}' is not an AI-to-AI session]"
        return

    # 3. Verify session is active
    if session.closed:
        yield f"[Error: Session '{session_id}' is closed]"
        return

    # === PHASE 2: SEND MESSAGE ===

    # 4. Send message to session
    await self.terminal_bridge.send_keys(
        session.tmux_session_name,
        message,
        append_exit_marker=True
    )

    # === PHASE 3: STREAMING (yield chunks as they arrive) ===

    # 5. Poll topic for responses and stream to MCP client
    topic_id = session.adapter_metadata.get("channel_id")
    last_message_id = None
    idle_count = 0
    max_idle_polls = 600  # 5 minutes (600 * 0.5s polls)
    heartbeat_interval = 60  # Send heartbeat every 60s if no output
    last_yield_time = time.time()

    while True:
        # Get new messages from topic since last poll
        messages = await self._get_topic_messages_since(
            topic_id=topic_id,
            after_message_id=last_message_id
        )

        if messages:
            idle_count = 0  # Reset idle counter

            for msg in messages:
                last_message_id = msg.message_id

                # Check for completion marker
                if "[Output Complete]" in msg.text:
                    return  # End stream

                # Extract chunk content (strip markdown and markers)
                content = self._extract_chunk_content(msg.text)
                if content:
                    yield content
                    last_yield_time = time.time()
        else:
            # No new messages - increment idle counter
            idle_count += 1

            # Send heartbeat if no output for a while
            if time.time() - last_yield_time > heartbeat_interval:
                yield "[⏳ Waiting for response...]\n"
                last_yield_time = time.time()

            # Timeout if idle too long
            if idle_count >= max_idle_polls:
                yield "\n[Timeout: No response from remote computer for 5 minutes]"
                return

        # Poll every 500ms
        await asyncio.sleep(0.5)
```

**Helper Methods:**

```python
async def _send_and_wait_for_topic(
    self,
    command: str,
    expected_topic_name: str,
    timeout: int = 5
) -> int:
    """Send command and wait for topic creation (ACK).

    Returns:
        topic_id: Telegram message_thread_id of created topic
    """
    topic_created = asyncio.Event()
    topic_id_holder = {"id": None}

    # Register callback for topic creation
    callback_id = self.telegram_adapter.register_topic_callback(
        lambda topic_id, topic_name: (
            topic_id_holder.update({"id": topic_id}),
            topic_created.set()
        ) if topic_name == expected_topic_name else None
    )

    try:
        # Send command to supergroup
        await self.telegram_adapter.send_text_to_group(command)

        # Wait for topic creation (ACK)
        await asyncio.wait_for(topic_created.wait(), timeout=timeout)

        return topic_id_holder["id"]
    finally:
        self.telegram_adapter.unregister_topic_callback(callback_id)


async def _wait_for_claude_ready(self, topic_id: int, timeout: int = 10) -> None:
    """Wait for remote Claude Code to signal it's ready."""
    start = time.time()

    while time.time() - start < timeout:
        messages = await self._get_recent_topic_messages(topic_id, limit=5)

        for msg in messages:
            # Look for ready signal
            if "Claude Code ready" in msg.text or "🤖 Starting Claude Code" in msg.text:
                return

        await asyncio.sleep(0.5)

    raise TimeoutError(f"Claude Code did not start within {timeout}s")


def _is_output_finished(self, text: str) -> bool:
    """Check if terminal output indicates command finished."""
    # Exit marker (injected by send_keys)
    if "__EXIT__" in text:
        return True

    # Process exit message
    if "✅ Process exited" in text or "Process exited (code:" in text:
        return True

    # Idle notification is NOT end of stream (keep polling)
    if "⏸️ No output" in text:
        return False

    return False


def _is_trusted_target(self, target: str) -> bool:
    """Check if target computer is in whitelist."""
    trusted_bots = self.config.get("telegram", {}).get("trusted_bots", [])
    target_bot = f"teleclaude_{target}_bot"
    return target_bot in trusted_bots
```

---

## Daemon Message Handling

### Incoming AI-to-AI Requests

When daemon receives message in a topic matching `# * > {self.computer_name}`:

```python
# In telegram_adapter.py _handle_text_message():

async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    thread_id = update.message.message_thread_id

    # Get topic name
    topic = await self._get_topic_info(thread_id)
    topic_name = topic.name if topic else None

    # Check if this is an incoming AI-to-AI request
    if self.classify_topic(topic_name) == 'incoming_ai':
        await self._handle_incoming_ai_request(update, context, topic_name)
        return

    # ... existing human session handling ...


async def _handle_incoming_ai_request(
    self,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    topic_name: str
):
    """Handle incoming AI-to-AI request."""
    text = update.message.text
    thread_id = update.message.message_thread_id

    # Get or create session for this topic
    session = await self._get_or_create_ai_session(thread_id, topic_name)

    # Handle /claude_resume command
    if text == "/claude_resume":
        # Start Claude Code in this session
        await self.terminal_bridge.send_keys(
            session.tmux_session_name,
            "claude"  # Or: cd ~/project && claude
        )

        # Wait briefly for startup
        await asyncio.sleep(2)

        # Confirm ready
        await self.send_message(
            session.session_id,
            f"🤖 Starting Claude Code on {self.computer_name}..."
        )
        return

    # Forward message to Claude Code (running in tmux)
    await self.terminal_bridge.send_keys(
        session.tmux_session_name,
        text
    )

    # Start polling output (will stream to Telegram topic)
    # This uses existing polling mechanism
    await self._poll_and_send_output(
        session.session_id,
        session.tmux_session_name
    )
```

### Outgoing Topic Polling

Daemon must poll all outgoing topics to capture responses for MCP streaming:

```python
# In daemon.py startup:

async def start(self):
    # ... existing startup ...

    # Start MCP server
    self.mcp_server = MCPServer(
        config=self.config,
        telegram_adapter=self.telegram_adapter,
        terminal_bridge=self.terminal_bridge,
        session_manager=self.session_manager
    )
    await self.mcp_server.start()

    # Start background topic poller for MCP responses
    asyncio.create_task(self._poll_outgoing_topics_for_mcp())


async def _poll_outgoing_topics_for_mcp(self):
    """Background task: Poll outgoing AI-to-AI topics for MCP streaming."""
    while True:
        try:
            # Get all forum topics
            topics = await self.telegram_adapter.get_all_topics()

            # Filter for our outgoing AI-to-AI topics
            outgoing_pattern = f"# {self.config['computer']['name']} > "
            outgoing_topics = [
                t for t in topics
                if t.name.startswith(outgoing_pattern)
            ]

            # For each outgoing topic, check for new messages
            for topic in outgoing_topics:
                # These messages will be consumed by active MCP streaming calls
                await self.mcp_server.check_topic_for_updates(topic.id)

            await asyncio.sleep(0.5)  # Poll every 500ms

        except Exception as e:
            logger.error(f"Error polling outgoing topics: {e}")
            await asyncio.sleep(5)  # Back off on error
```

---

## New Command: `/claude_resume`

**Purpose:** Start Claude Code in current session (for AI-to-AI communication)

**Registration:**
```python
# In telegram_adapter.py start():
self.app.add_handler(CommandHandler("claude_resume", self._handle_claude_resume))

commands = [
    # ... existing commands ...
    BotCommand("claude_resume", "Start Claude Code in this session (AI-to-AI)"),
]
```

**Handler:**
```python
async def _handle_claude_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start Claude Code in current session."""
    session = await self._get_session_from_topic(update)
    if not session:
        return

    # Send command to start Claude Code
    await self.terminal_bridge.send_keys(
        session.tmux_session_name,
        "claude"  # Or configured command from config.yml
    )

    # Confirm
    await self.send_message(
        session.session_id,
        f"🤖 Starting Claude Code on {self.computer_name}..."
    )
```

---

## Configuration Changes

### config.yml.sample

```yaml
computer:
    name: macbook  # Unique per computer
    bot_username: teleclaude_macbook_bot
    default_shell: /bin/zsh
    default_working_dir: ${WORKING_DIR}
    trustedDirs: [...]

telegram:
    supergroup_id: ${TELEGRAM_SUPERGROUP_ID}

    # Whitelist of trusted bots (security)
    trusted_bots:
        - teleclaude_macbook_bot
        - teleclaude_workstation_bot
        - teleclaude_server_bot
        - teleclaude_laptop_bot

mcp:
    enabled: true

    # Transport type: 'stdio' for Claude Code, 'socket' for other clients
    transport: stdio

    # Socket path if using socket transport (not used for stdio)
    socket_path: /tmp/teleclaude-${COMPUTER_NAME}.sock

    # Command to start Claude Code (for /claude_resume)
    claude_command: claude  # Or: cd ~/project && claude
```

### .env (per computer)

```bash
# Unique bot token per computer
TELEGRAM_BOT_TOKEN=123:ABC_your_unique_bot_token

# Computer identifier (should match config.yml computer.name)
COMPUTER_NAME=macbook

# Shared supergroup for all bots
TELEGRAM_SUPERGROUP_ID=-100123456789

# Working directory
WORKING_DIR=/Users/user/teleclaude
```

---

## MCP Server Implementation Structure

### File: `teleclaude/mcp_server.py`

```python
"""MCP server for TeleClaude multi-computer communication."""

import asyncio
import logging
import re
import time
from typing import Any, AsyncIterator, Optional

from mcp.server import Server
from mcp.types import Tool, TextContent

logger = logging.getLogger(__name__)


class TeleClaudeMCPServer:
    """MCP server for exposing TeleClaude functionality to Claude Code."""

    def __init__(
        self,
        config: dict,
        telegram_adapter: Any,
        terminal_bridge: Any,
        session_manager: Any
    ):
        self.config = config
        self.telegram_adapter = telegram_adapter
        self.terminal_bridge = terminal_bridge
        self.session_manager = session_manager

        self.computer_name = config["computer"]["name"]
        self.server = Server("teleclaude")

        # Setup MCP tool handlers
        self._setup_tools()

    def _setup_tools(self):
        """Register MCP tools."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="teleclaude__list",
                    description="List all available TeleClaude computers",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    }
                ),
                Tool(
                    name="teleclaude__send",
                    description="Send message to remote computer's Claude Code and stream response",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "target": {
                                "type": "string",
                                "description": "Target computer name (e.g., 'workstation', 'server')"
                            },
                            "message": {
                                "type": "string",
                                "description": "Message or command to send to remote Claude Code"
                            }
                        },
                        "required": ["target", "message"]
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            if name == "teleclaude__list":
                return await self.teleclaude__list()
            elif name == "teleclaude__send":
                # MCP SDK will handle async generator streaming
                return await self.teleclaude__send(**arguments)

    async def start(self):
        """Start MCP server."""
        transport = self.config.get("mcp", {}).get("transport", "stdio")

        if transport == "stdio":
            # Use stdio transport for Claude Code integration
            from mcp.server.stdio import stdio_server
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options()
                )
        elif transport == "socket":
            # Use Unix socket transport
            socket_path = self.config["mcp"]["socket_path"]
            # TODO: Implement socket transport
            raise NotImplementedError("Socket transport not yet implemented")

    async def teleclaude__list(self) -> list[dict]:
        """List available computers."""
        # Implementation from spec above
        pass

    async def teleclaude__send(self, target: str, message: str) -> AsyncIterator[str]:
        """Send to remote AI and stream response."""
        # Implementation from spec above
        pass

    def classify_topic(self, topic_name: str) -> str:
        """Classify topic type based on naming pattern."""
        # Implementation from spec above
        pass

    # ... helper methods ...
```

---

## Implementation Phases

### Phase 1: Basic Infrastructure (Week 1)

**Goals:**
- Computer registry with heartbeat mechanism
- MCP server skeleton with stdio transport
- Tool registration and basic handlers
- Topic pattern matching and classification

**Tasks:**
1. Create `teleclaude/core/computer_registry.py` with `ComputerRegistry` class
2. Implement heartbeat loop (post/edit status message every 30s)
3. Implement registry polling loop (refresh in-memory list every 30s)
4. Add computer registry initialization to `daemon.py`
5. Create `teleclaude/mcp_server.py` with `TeleClaudeMCPServer` class
6. Add MCP SDK dependency to `requirements.txt`
7. Implement topic classification logic (`classify_topic()`)
8. Implement `teleclaude__list` tool (returns registry data)
9. Add MCP server initialization to `daemon.py`
10. Update configuration schema (config.yml.sample)
11. Add unit tests for pattern matching and registry parsing

**Deliverables:**
- Computer registry discovers and tracks all daemons (online/offline)
- MCP server starts with daemon
- `teleclaude__list` returns list of online computers from registry
- Topic classification works correctly

---

### Phase 2: Remote Command Execution (Week 2)

**Goals:**
- Implement `teleclaude__send` tool with basic flow
- Topic creation and ACK detection
- Non-streaming version first (simplification)

**Tasks:**
1. Implement `_send_and_wait_for_topic()` helper
2. Add topic creation callback mechanism to telegram_adapter
3. Implement basic `teleclaude__send` (no streaming yet)
4. Add `/claude_resume` command handler
5. Implement incoming AI-to-AI request handling
6. Add whitelist security check
7. Test end-to-end: Comp1 → Comp2 execution (single response)

**Deliverables:**
- Can send command from Comp1 to Comp2 via MCP
- Comp2 creates topic and executes command
- Comp1 receives single response (no streaming yet)

---

### Phase 3: Response Streaming (Week 3)

**Goals:**
- Implement streaming responses from remote computer
- Background topic poller for MCP
- Full async generator implementation

**Tasks:**
1. Implement `_poll_outgoing_topics_for_mcp()` background task
2. Implement `check_topic_for_updates()` in MCP server
3. Convert `teleclaude__send` to async generator (streaming)
4. Add heartbeat mechanism for long-running commands
5. Implement timeout and idle detection
6. Add exit marker detection
7. Test streaming: Long commands (e.g., npm install) stream output

**Deliverables:**
- Real-time streaming of remote command output
- Heartbeats during long pauses
- Proper completion detection

---

### Phase 4: Polish & Production Readiness (Week 4)

**Goals:**
- Error handling, edge cases, documentation
- Performance optimization
- Integration testing

**Tasks:**
1. Add comprehensive error handling (timeouts, disconnections)
2. Implement proper cleanup (topic closing, session cleanup)
3. Add metrics/logging (MCP call counts, latency)
4. Performance testing (multiple concurrent MCP calls)
5. Update docs/architecture.md with MCP architecture
6. Create user guide for multi-computer setup
7. End-to-end testing with 3+ computers
8. Add integration tests for MCP tools

**Deliverables:**
- Production-ready MCP server
- Full documentation
- Comprehensive test coverage

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_mcp_server.py

def test_classify_topic_outgoing():
    server = TeleClaudeMCPServer(config={"computer": {"name": "macbook"}}, ...)
    assert server.classify_topic("# macbook > workstation") == "outgoing_ai"

def test_classify_topic_incoming():
    server = TeleClaudeMCPServer(config={"computer": {"name": "workstation"}}, ...)
    assert server.classify_topic("# macbook > workstation") == "incoming_ai"

def test_classify_topic_human():
    server = TeleClaudeMCPServer(...)
    assert server.classify_topic("My Project") == "human"


# tests/unit/test_computer_registry.py

def test_parse_registry_message():
    """Test parsing computer status message (simple single-line format)."""
    registry = ComputerRegistry(...)

    message_text = "macbook - last seen at 2025-11-04 15:30:45"

    # Simulate parsing logic
    match = re.match(r'^(\w+) - last seen at ([\d\-: ]+)$', message_text.strip())
    assert match is not None
    assert match.group(1) == "macbook"
    assert match.group(2) == "2025-11-04 15:30:45"

def test_offline_detection():
    """Test that computers are marked offline after threshold."""
    registry = ComputerRegistry(...)
    registry.offline_threshold = 60

    # Simulate computer with old heartbeat (70s ago)
    old_time = datetime.now() - timedelta(seconds=70)
    registry.computers["workstation"] = {
        "name": "workstation",
        "last_seen": old_time,
        "status": "online"
    }

    # Refresh should mark it offline
    await registry._refresh_computer_list()
    assert registry.computers["workstation"]["status"] == "offline"

def test_get_online_computers():
    """Test filtering online computers only."""
    registry = ComputerRegistry(...)
    registry.computers = {
        "macbook": {"name": "macbook", "status": "online"},
        "workstation": {"name": "workstation", "status": "offline"},
        "server": {"name": "server", "status": "online"}
    }

    online = registry.get_online_computers()
    assert len(online) == 2
    assert "macbook" in [c["name"] for c in online]
    assert "server" in [c["name"] for c in online]
    assert "workstation" not in [c["name"] for c in online]
```

### Integration Tests

```python
# tests/integration/test_computer_registry.py

@pytest.mark.integration
async def test_registry_heartbeat_updates():
    """Test that registry updates heartbeat in real Telegram topic."""
    daemon1 = await start_test_daemon("macbook")
    daemon2 = await start_test_daemon("workstation")

    # Wait for initial heartbeat
    await asyncio.sleep(2)

    # Check that both daemons see each other
    computers1 = daemon1.computer_registry.get_online_computers()
    computers2 = daemon2.computer_registry.get_online_computers()

    assert len(computers1) >= 2  # At least macbook + workstation
    assert any(c["name"] == "workstation" for c in computers1)
    assert any(c["name"] == "macbook" for c in computers2)

@pytest.mark.integration
async def test_offline_detection_after_crash():
    """Test that crashed daemon is marked offline after threshold."""
    daemon1 = await start_test_daemon("macbook")
    daemon2 = await start_test_daemon("workstation")

    # Wait for discovery
    await asyncio.sleep(2)

    # Kill daemon2 (simulate crash)
    await daemon2.stop()

    # Wait past offline threshold (60s)
    await asyncio.sleep(65)

    # daemon1 should mark daemon2 as offline
    computers = daemon1.computer_registry.get_online_computers()
    assert not any(c["name"] == "workstation" for c in computers)

# tests/integration/test_mcp_ai_to_ai.py

@pytest.mark.integration
async def test_teleclaude_list_discovers_computers():
    """Test that teleclaude__list returns all online computers from registry."""
    result = await mcp_client.call_tool("teleclaude__list", {})
    assert len(result) >= 2
    assert any(c["name"] == "macbook" for c in result)
    assert all(c["status"] == "online" for c in result)  # Should only return online

@pytest.mark.integration
async def test_teleclaude_send_executes_on_remote():
    """Test sending command to remote computer."""
    chunks = []
    async for chunk in mcp_client.call_tool("teleclaude__send", {
        "target": "workstation",
        "message": "echo 'test message'"
    }):
        chunks.append(chunk)

    output = "".join(chunks)
    assert "test message" in output
    assert "exit code: 0" in output.lower()

@pytest.mark.integration
async def test_streaming_long_command():
    """Test that streaming works for long-running commands."""
    chunk_count = 0
    async for chunk in mcp_client.call_tool("teleclaude__send", {
        "target": "workstation",
        "message": "for i in {1..10}; do echo $i; sleep 0.5; done"
    }):
        chunk_count += 1

    assert chunk_count >= 10  # Should receive multiple chunks
```

---

## Security Considerations

### 1. Bot Whitelist

**Threat:** Unauthorized bots joining supergroup and sending commands

**Mitigation:**
- Maintain `trusted_bots` whitelist in config.yml
- Only accept AI-to-AI commands from whitelisted bots
- Validate bot username before executing commands

```python
def _is_message_from_trusted_bot(self, message) -> bool:
    """Check if message is from a trusted bot."""
    if not message.from_user.is_bot:
        return False

    trusted_bots = self.config.get("telegram", {}).get("trusted_bots", [])
    return message.from_user.username in trusted_bots
```

### 2. Command Injection

**Threat:** Malicious commands injected via MCP tools

**Mitigation:**
- Commands are forwarded to tmux exactly as received (no shell expansion by daemon)
- Claude Code itself validates commands before sending to MCP
- Shell execution happens in tmux with user's permissions (not daemon)

**Note:** Trust boundary is Claude Code → MCP, not MCP → tmux. Claude Code is responsible for safe command construction.

### 3. Topic Spoofing

**Threat:** Attacker creates fake AI-to-AI topics to intercept responses

**Mitigation:**
- Only respond to topics created by trusted bots
- Validate topic creator before processing messages
- Pattern matching ensures only proper format accepted

```python
async def _validate_topic_creator(self, topic_id: int) -> bool:
    """Verify topic was created by a trusted bot."""
    topic_info = await self.telegram_adapter.get_topic_info(topic_id)
    creator_username = topic_info.creator.username

    trusted_bots = self.config.get("telegram", {}).get("trusted_bots", [])
    return creator_username in trusted_bots
```

---

## Open Questions / Future Enhancements

### 1. Multi-Hop Communication

**Question:** Should Comp1 → Comp2 → Comp3 be supported?

**Current Design:** Direct communication only (Comp1 → Comp2)

**Future:** Could implement multi-hop by having Comp2's Claude Code call `teleclaude__send` to Comp3

### 2. Session Persistence

**Question:** Should AI-to-AI sessions persist across daemon restarts?

**Current Design:** Sessions stored in DB, but topic polling state is in-memory

**Enhancement:** Store active MCP streaming state in DB for restart resilience

### 3. Rate Limiting

**Question:** Should we limit number of concurrent AI-to-AI sessions?

**Current Design:** No limits

**Enhancement:** Add max_concurrent_ai_sessions config option

### 4. Response Caching

**Question:** Should responses be cached for repeated queries?

**Current Design:** No caching

**Enhancement:** Optional response cache with TTL for idempotent commands

---

## Acceptance Criteria

### Phase 1 Complete When:
- [ ] Computer registry discovers all online daemons via heartbeat
- [ ] Registry correctly marks daemons offline after 60s of no heartbeat
- [ ] `teleclaude__list` returns all online computers from in-memory registry
- [ ] Topic pattern matching correctly identifies outgoing/incoming/human
- [ ] MCP server starts with daemon (no crashes)
- [ ] Unit tests pass for pattern matching and registry parsing

### Phase 2 Complete When:
- [ ] Can send command from Comp1 to Comp2 via MCP tool
- [ ] Comp2 receives and executes command
- [ ] Comp1 receives response (single message)
- [ ] Whitelist security works (rejects untrusted bots)

### Phase 3 Complete When:
- [ ] Long-running commands stream output in real-time
- [ ] Heartbeats appear during idle periods
- [ ] Exit detection properly ends stream
- [ ] Multiple concurrent AI-to-AI sessions work simultaneously

### Phase 4 Complete When:
- [ ] All error cases handled gracefully (timeout, disconnect, etc.)
- [ ] Documentation complete (architecture + user guide)
- [ ] Integration tests pass with 3+ computers
- [ ] Performance tested (10+ concurrent MCP calls)

---

## Success Metrics

**Functionality:**
- ✅ Claude Code on Comp1 can discover all available computers
- ✅ Claude Code on Comp1 can execute commands on Comp2 and receive streaming output
- ✅ AI-to-AI topics correctly routed (no crosstalk)
- ✅ Security whitelist prevents unauthorized commands

**Performance:**
- Response latency < 2s (time from MCP call to first chunk)
- Streaming latency < 1s (delay between chunk generation on Comp2 and delivery to Comp1)
- Supports 10+ concurrent AI-to-AI sessions per computer

**Reliability:**
- Zero crashes during normal operation
- Graceful handling of timeouts, disconnections
- Daemon restart doesn't break active MCP streaming (recoverable)

---

## References

- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)
- [python-telegram-bot Documentation](https://docs.python-telegram-bot.org/)
- [TeleClaude Architecture Docs](../docs/architecture.md)
- [Telegram Bot API - Forum Topics](https://core.telegram.org/bots/api#forum-topics)

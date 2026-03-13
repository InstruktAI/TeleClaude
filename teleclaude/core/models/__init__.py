"""Data models for TeleClaude sessions.

Re-exports all public names from submodules for backward compatibility.
"""

from ._adapter import (
    AdapterType,
    DiscordAdapterMetadata,
    PeerInfo,
    RedisTransportMetadata,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
    TransportAdapterMetadata,
    UiAdapterMetadata,
    WhatsAppAdapterMetadata,
)
from ._context import (
    BaseCommandContext,
    FileContext,
    MessageContext,
    NewSessionContext,
    SessionCommandContext,
    SystemCommandContext,
    VoiceContext,
)
from ._session import (
    FIELD_KIND,
    ChannelMetadata,
    CleanupTrigger,
    MessageMetadata,
    Recording,
    Session,
    SessionField,
    SessionLaunchIntent,
    SessionLaunchKind,
    SessionMetadata,
    TranscriptFormat,
)
from ._snapshot import (
    AgentResumeArgs,
    AgentStartArgs,
    CommandPayload,
    ComputerInfo,
    KillArgs,
    MessagePayload,
    ProjectInfo,
    RedisInboundMessage,
    RunAgentCommandArgs,
    SessionSnapshot,
    StartSessionArgs,
    SystemCommandArgs,
    ThinkingMode,
    TodoInfo,
)
from ._types import (
    JsonDict,
    JsonPrimitive,
    JsonValue,
    asdict_exclude_none,
)

__all__ = [
    "FIELD_KIND",
    # _adapter
    "AdapterType",
    # _snapshot
    "AgentResumeArgs",
    "AgentStartArgs",
    # _context
    "BaseCommandContext",
    # _session
    "ChannelMetadata",
    "CleanupTrigger",
    "CommandPayload",
    "ComputerInfo",
    "DiscordAdapterMetadata",
    "FileContext",
    # _types
    "JsonDict",
    "JsonPrimitive",
    "JsonValue",
    "KillArgs",
    "MessageContext",
    "MessageMetadata",
    "MessagePayload",
    "NewSessionContext",
    "PeerInfo",
    "ProjectInfo",
    "Recording",
    "RedisInboundMessage",
    "RedisTransportMetadata",
    "RunAgentCommandArgs",
    "Session",
    "SessionAdapterMetadata",
    "SessionCommandContext",
    "SessionField",
    "SessionLaunchIntent",
    "SessionLaunchKind",
    "SessionMetadata",
    "SessionSnapshot",
    "StartSessionArgs",
    "SystemCommandArgs",
    "SystemCommandContext",
    "TelegramAdapterMetadata",
    "ThinkingMode",
    "TodoInfo",
    "TranscriptFormat",
    "TransportAdapterMetadata",
    "UiAdapterMetadata",
    "VoiceContext",
    "WhatsAppAdapterMetadata",
    "asdict_exclude_none",
]

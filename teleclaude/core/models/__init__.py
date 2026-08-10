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
from ._human_message import (
    HumanFacingMessage,
    MessageAuthor,
    MessageAuthorKind,
)
from ._session import (
    FIELD_KIND,
    ChannelMetadata,
    CleanupTrigger,
    MessageMetadata,
    OriginRevivalContext,
    Recording,
    Session,
    SessionField,
    SessionLaunchIntent,
    SessionLaunchKind,
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
)
from ._types import (
    JsonDict,
    JsonPrimitive,
    JsonValue,
    SessionOriginMetadata,
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
    # _human_message
    "HumanFacingMessage",
    # _types
    "JsonDict",
    "JsonPrimitive",
    "JsonValue",
    "KillArgs",
    "MessageAuthor",
    "MessageAuthorKind",
    "MessageContext",
    "MessageMetadata",
    "MessagePayload",
    "NewSessionContext",
    "OriginRevivalContext",
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
    "SessionOriginMetadata",
    "SessionSnapshot",
    "StartSessionArgs",
    "SystemCommandArgs",
    "SystemCommandContext",
    "TelegramAdapterMetadata",
    "ThinkingMode",
    "TranscriptFormat",
    "TransportAdapterMetadata",
    "UiAdapterMetadata",
    "VoiceContext",
    "WhatsAppAdapterMetadata",
    "asdict_exclude_none",
]

"""Wire codec for internal commands: rebuild a typed command from its cross-computer payload."""

from collections.abc import Mapping
from enum import Enum
from inspect import signature
from typing import Any, cast

from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.injected_text import InjectedTextSourceFeature, TranscriptEntryKind
from teleclaude.core.models import EndpointStamp, SessionEntryPoint, SessionLaunchIntent
from teleclaude.core.models._types import JsonDict
from teleclaude.docs_subscriptions import SubscriptionAttendance, SubscriptionIdentity
from teleclaude.types.commands import (
    ActivateProcedureCommand,
    CallerProvenance,
    CloseSessionCommand,
    CommandType,
    CreateSessionCommand,
    GetSessionDataCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    HandoffAgentCommand,
    InternalCommand,
    KeysCommand,
    ProcessMessageCommand,
    ResponseMode,
    RestartAgentCommand,
    ResumeAgentCommand,
    ReviveAgentCommand,
    RunAgentCommand,
    SetVoiceFocusCommand,
    StartAgentCommand,
    SystemCommand,
    UnsubscribeSessionCommand,
)
from teleclaude.types.media import MediaRef

# The nested wire blocks a command carries as typed values.
_ENDPOINT_FIELD = "endpoint"
_MEDIA_REF_FIELD = "media_ref"

COMMAND_CLASS_BY_TYPE: dict[CommandType, type[InternalCommand]] = {
    CommandType.CREATE_SESSION: CreateSessionCommand,
    CommandType.HANDLE_VOICE: HandleVoiceCommand,
    CommandType.HANDLE_FILE: HandleFileCommand,
    CommandType.KEYS: KeysCommand,
    CommandType.START_AGENT: StartAgentCommand,
    CommandType.RESUME_AGENT: ResumeAgentCommand,
    CommandType.PROCESS_MESSAGE: ProcessMessageCommand,
    CommandType.RUN_AGENT_COMMAND: RunAgentCommand,
    CommandType.RESTART_AGENT: RestartAgentCommand,
    CommandType.HANDOFF_AGENT: HandoffAgentCommand,
    CommandType.REVIVE_AGENT: ReviveAgentCommand,
    CommandType.UNSUBSCRIBE_SESSION: UnsubscribeSessionCommand,
    CommandType.GET_SESSION_DATA: GetSessionDataCommand,
    CommandType.CLOSE_SESSION: CloseSessionCommand,
    CommandType.SYSTEM: SystemCommand,
    CommandType.SET_VOICE_FOCUS: SetVoiceFocusCommand,
    CommandType.ACTIVATE_PROCEDURE: ActivateProcedureCommand,
}

_WIRE_ENUM_FIELDS: Mapping[str, type[Enum]] = {
    "response_mode": ResponseMode,
    "entry_point": SessionEntryPoint,
    "command_input_mode": CommandInputMode,
    "text_kind": TranscriptEntryKind,
    "source_feature": InjectedTextSourceFeature,
    "identity": SubscriptionIdentity,
    "attendance": SubscriptionAttendance,
}


def command_from_dict(data: JsonDict) -> InternalCommand:
    """Rebuild an internal command from its cross-computer wire payload."""
    raw_command_type = data.get("command_type")
    if not isinstance(raw_command_type, str):
        raise ValueError("command_type is required")
    command_type = CommandType(raw_command_type)
    command_cls = COMMAND_CLASS_BY_TYPE[command_type]

    constructor_params = signature(command_cls).parameters
    kwargs: dict[str, object] = {}  # guard: loose-dict - constructor kwargs rebuilt from a cross-computer wire payload
    for name in constructor_params:
        if name in {"command_type", "computer", "caller"} or name not in data:
            continue
        raw_value: object = data[name]
        value: object = raw_value
        enum_type = _WIRE_ENUM_FIELDS.get(name)
        if enum_type is not None and isinstance(raw_value, str):
            value = enum_type(raw_value)
        elif name == "launch_intent" and isinstance(raw_value, dict):
            value = SessionLaunchIntent.from_dict(raw_value)
        elif name in {"origin_metadata", "data"} and isinstance(raw_value, dict):
            value = dict(raw_value)
        elif name == _ENDPOINT_FIELD and isinstance(raw_value, dict):
            value = EndpointStamp.from_dict(raw_value)
        elif name == _MEDIA_REF_FIELD and isinstance(raw_value, dict):
            value = MediaRef.from_dict(raw_value)
        kwargs[name] = value

    command = cast(InternalCommand, cast(Any, command_cls)(**kwargs))
    command.computer = cast(str | None, data.get("computer"))
    raw_response_mode = data.get("response_mode")
    if isinstance(raw_response_mode, str):
        command.response_mode = ResponseMode(raw_response_mode)
    command.success_event = cast(str | None, data.get("success_event"))
    command.failure_event = cast(str | None, data.get("failure_event"))
    raw_caller = data.get("caller")
    command.caller = CallerProvenance.from_dict(raw_caller) if isinstance(raw_caller, dict) else None
    raw_relayed_principal = data.get("relayed_principal")
    if raw_relayed_principal is not None and not isinstance(raw_relayed_principal, str):
        raise ValueError("relayed_principal must be a string when present")
    command.relayed_principal = raw_relayed_principal
    # A subclass whose hand-written __init__ hardcodes response_mode/events (or,
    # like ProcessMessageCommand, derives `caller` from its own flat kwargs) never
    # installed these post-construction assignments through the biconditional.
    # Re-running it here closes that gap on every deserialized command, remote or
    # local, rather than only on the ones whose __init__ happens to accept them.
    command.__post_init__()
    return command

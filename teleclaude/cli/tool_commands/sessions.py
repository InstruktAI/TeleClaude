"""Sessions subcommand handlers for telec sessions <subcommand>.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Final, TypedDict

from teleclaude.cli.session_send_request import SessionSendUsageError, resolve_session_send
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.addressing import address_computer, project_reference
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import (
    SESSIONS_END,
    SESSIONS_ESCALATE,
    SESSIONS_FILE,
    SESSIONS_LIST,
    SESSIONS_RESTART,
    SESSIONS_RESULT,
    SESSIONS_RUN,
    SESSIONS_RUN_PA,
    SESSIONS_SHOW,
    SESSIONS_START,
    SESSIONS_TAIL,
    SESSIONS_UNSUBSCRIBE,
)
from teleclaude.cli.tool_client import (
    NotAcceptedCause,
    ToolAPIError,
    not_accepted_cause_text,
    print_json,
    print_run_again_when_not_accepted,
    tool_api_call,
    tool_api_request,
)
from teleclaude.cli.tool_commands._receipt import render_receipt
from teleclaude.constants import SESSION_START_TIMEOUT_S, SessionTarget
from teleclaude.session_identity import get_session_id

if TYPE_CHECKING:
    from teleclaude.api_models import SessionDTO

_COORDINATE_SUBCOMMAND = "coordinate"
_COORDINATE_HELP_FLAGS = ("-h", "--help")
_COORDINATE_ENDPOINT = "/sessions/self/coordinate"
_SESSIONS_RUN_PA_SUBCOMMAND: Final[str] = "run-pa"
_SESSIONS_RUN_PA_ENDPOINT: Final[str] = "/sessions/run-pa"
_SESSIONS_RUN_PA_BRIEF_FIELD: Final[str] = "brief"
_SESSIONS_RUN_PA_ARGUMENT_ERROR: Final[str] = "Error: provide at most one brief."
_POST_METHOD = "POST"
_GET_METHOD: Final[str] = "GET"
_SESSIONS_SHOW_ENDPOINT_TEMPLATE: Final[str] = "/sessions/{target}"
_SESSIONS_SHOW_FULL_PARAM: Final[str] = "full"
_SESSIONS_SHOW_COMPUTER_PARAM: Final[str] = "computer"
_QUERY_TRUE: Final[str] = "true"
_UNEXPECTED_ARGUMENT_ERROR_TEMPLATE: Final[str] = "Error: unexpected argument: {argument}"
_BULK_END_TIMEOUT_S = 30.0
_CLOSE_FAILURE_TEMPLATE: Final = "failed to close child session {session_id}: {failure}"
_LIST_FAILURE_TEMPLATE: Final = "Error: failed to list caller child sessions: {failure}"
_BULK_END_FAILURE_TEMPLATE: Final = "Error: caller child cleanup failed: {reason}; residual session IDs: {residuals}"
_BULK_END_POLL_INTERVAL_S = 0.25
_SESSION_END_DUPLICATE_TARGET_ERROR = "Error: do not specify more than one session_id"


class _RestartRequestBody(TypedDict, total=False):
    self_restart: bool
    handoff: bool
    agent: str | None


def handle_sessions(args: list[str]) -> None:
    """Handle telec sessions <subcommand> [args].

    Subcommands:
      list        List sessions (default: spawned by current, --all for all)
      show        Show one session's stored record ('self' or no id for own session)
      start       Start a new agent session
      send        Send a message to a session
      tail        Get recent messages from a session
      run         Run a slash command on a new agent session
      revive      Revive a session by TeleClaude or native session ID
      end         End a session ('self' to end own session)
      restart     Restart a session ('self' to restart own session)
      unsubscribe Stop receiving notifications from a session
      result      Send a formatted result to the user (implicit session)
      file        Send a file to the user (implicit session)
      escalate    Escalate a visitor to everyone in the desk's scope in its escalation thread (implicit session)
      coordinate  Adopt this session as the project's single coordinator (human-directed only; refuses if one is live)
    """
    if not args or args[0] in ("-h", "--help"):
        _sessions_help()
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        handle_sessions_list(rest)
    elif sub == "show":
        handle_sessions_show(rest)
    elif sub == "start":
        handle_sessions_start(rest)
    elif sub == "send":
        handle_sessions_send(rest)
    elif sub == "tail":
        handle_sessions_tail(rest)
    elif sub == "run":
        handle_sessions_run(rest)
    elif sub == _SESSIONS_RUN_PA_SUBCOMMAND:
        handle_sessions_run_pa(rest)
    elif sub == "revive":
        # Keep revive behavior centralized in telec CLI entrypoint since it
        # includes post-revive kick and optional tmux attach semantics.
        importlib.import_module("teleclaude.cli.telec.handlers.misc")._handle_revive(rest)
    elif sub == "end":
        handle_sessions_end(rest)
    elif sub == "unsubscribe":
        handle_sessions_unsubscribe(rest)
    elif sub == "result":
        handle_sessions_result(rest)
    elif sub == "file":
        handle_sessions_file(rest)
    elif sub == "escalate":
        handle_sessions_escalate(rest)
    elif sub == _COORDINATE_SUBCOMMAND:
        handle_sessions_coordinate(rest)
    elif sub == "restart":
        handle_sessions_restart(rest)
    else:
        print(f"Unknown sessions subcommand: {sub}", file=sys.stderr)
        print("Run 'telec sessions --help' for usage.", file=sys.stderr)
        raise SystemExit(1)


def _sessions_help() -> None:
    print(
        """Usage: telec sessions <subcommand> [args]

Subcommands:
  list         List sessions (default: spawned by current, --all for all)
  show         Show one session's stored record ('self' or no id for own session)
  start        Start a new agent session
  send         Send a message to a running session
  tail         Get recent messages from a session
  run          Run a slash command on a new agent session
  revive       Revive session by TeleClaude or native session ID
  end          End (terminate) a session ('self' to end own session)
  restart      Restart an agent session ('self' to restart own session)
  unsubscribe  Stop receiving notifications from a session
  result       Send a formatted result to the user (implicit session)
  file         Send a file to the user (implicit session)
  escalate     Escalate a visitor to everyone in the desk's scope in its escalation thread (implicit session)
  coordinate   Adopt this session as the project's single coordinator (human-directed only; refuses if one is live)

Run 'telec sessions <subcommand> --help' for subcommand-specific help."""
    )


def handle_sessions_list(args: list[str]) -> None:
    """List sessions.

    Usage: telec sessions list [--all] [--closed] [--job <job>] [--computer <name>]

    Without --all, lists only sessions spawned by the current session.
    With --all, lists all sessions on the local computer.
    With --closed, includes closed sessions.
    With --job <job>, filters to sessions whose job field matches.
    With --computer <name>, filters to sessions on a specific computer.

    Examples:
      telec sessions list
      telec sessions list --all
      telec sessions list --all --closed
      telec sessions list --all --job integrator
      telec sessions list --computer remote-macbook
    """
    parsed = parse_command_args(SESSIONS_LIST, args)
    params: dict[str, str] = {}
    if parsed.has(F.FLAG_SESSIONS_LIST_ALL):
        params["all"] = "true"
    if parsed.has(F.FLAG_SESSIONS_LIST_CLOSED):
        params["closed"] = "true"
    job_filter = parsed.value(F.FLAG_SESSIONS_LIST_JOB)
    if job_filter:
        params["job"] = job_filter
    computer = parsed.value(F.FLAG_COMPUTER)
    if computer:
        params["computer"] = computer
    data = tool_api_call("GET", "/sessions", params=params)
    print_json(data)


def handle_sessions_show(args: list[str]) -> None:
    """Show one session's stored record.

    Usage: telec sessions show [<session_id>|self] [--computer <name>] [--full]

    Without a session id, shows the record of the calling session.
    Default output groups the record as identity, origin, role, state, and wiring.
    With --full, shows the complete stored record, decoded.
    A session is shown only when the caller could list it.
    For what a session said, see `telec sessions tail` and `telec history show`;
    for the roster and a session's children, see `telec sessions list`.

    Examples:
      telec sessions show
      telec sessions show abc123
      telec sessions show abc123 --full --computer remote-macbook
    """
    parsed = parse_command_args(SESSIONS_SHOW, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(_UNEXPECTED_ARGUMENT_ERROR_TEMPLATE.format(argument=positionals[1]), file=sys.stderr)
        raise SystemExit(1)
    target = positionals[0] if positionals else SessionTarget.SELF.value
    params: dict[str, str] = {}
    if parsed.has(F.FLAG_SESSIONS_SHOW_FULL):
        params[_SESSIONS_SHOW_FULL_PARAM] = _QUERY_TRUE
    computer = parsed.value(F.FLAG_COMPUTER)
    if computer:
        params[_SESSIONS_SHOW_COMPUTER_PARAM] = computer
    data = tool_api_call(_GET_METHOD, _SESSIONS_SHOW_ENDPOINT_TEMPLATE.format(target=target), params=params)
    print_json(data)


def handle_sessions_start(args: list[str]) -> None:
    """Start a new agent session.

    Usage: telec sessions start --path <path>
                                [--computer <name>]
                                [--agent claude|gemini|codex|deepseek]
                                [--mode fast|med|slow]
                                [--message <text>]
                                [--direct]
                                [--detach]

    Creates a new TeleClaude agent session on the specified computer in the
    given project directory. When --agent is omitted, target-local automatic
    role-aware resolution selects an eligible agent. The agent starts immediately.

    Examples:
      telec sessions start --path /path/to/project
      telec sessions start --path /path/to/project --agent claude --mode slow
      telec sessions start --path /p/to/p --message "Implement feature X"
      telec sessions start --path /path/to/project --computer remote-macbook
    """
    parsed = parse_command_args(SESSIONS_START, args)
    body: dict[str, object] = {"computer": "local", "launch_kind": "agent"}  # guard: loose-dict - JSON request body
    computer = parsed.value(F.FLAG_COMPUTER)
    if computer is not None:
        body["computer"] = computer
    path = parsed.value(F.FLAG_PATH)
    if path is not None:
        body["project_path"] = path
    agent = parsed.value(F.FLAG_AGENT)
    if agent is not None:
        body["agent"] = agent
    mode = parsed.value(F.FLAG_MODE)
    if mode is not None:
        body["thinking_mode"] = mode
    message = parsed.value(F.FLAG_MESSAGE)
    if message is not None:
        body["message"] = message
        body["launch_kind"] = "agent_then_message"
    if parsed.has(F.FLAG_DIRECT_START):
        body["direct"] = True
    if parsed.has(F.FLAG_DETACH):
        body["skip_listener_registration"] = True
    company = parsed.value(F.FLAG_COMPANY)
    if company is not None:
        body["company"] = company

    address_computer(computer)
    if not body.get("project_path"):
        body["project_path"] = project_reference()

    data = tool_api_call("POST", "/sessions", json_body=body, timeout=SESSION_START_TIMEOUT_S)
    print_json(data)


def handle_sessions_send(args: list[str]) -> None:
    """Send a message to a running session.

    Usage: telec sessions send <session_id> [<message>] [--computer <host>] [--direct]
           telec sessions send <session_id> --close-link
           telec sessions send --session <session_id> --message <text> [--direct]  # compatibility

    Delivers a message to the target session.
    --computer names the computer that owns the target session (optional; defaults to local).
    With --direct, create a shared conversation link.
    With --close-link, sever a shared conversation link.

    Examples:
      telec sessions send abc123 "Please implement feature X"
      telec sessions send abc123 "Let's discuss the architecture" --direct
      telec sessions send abc123 --close-link
      telec sessions send abc123 "Please implement feature X" --computer <computer>
    """
    try:
        request = resolve_session_send(args)
    except SessionSendUsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    body: dict[str, str | bool] = {}
    if request.message:
        body["message"] = request.message
    if request.direct:
        body["direct"] = True
    if request.close_link:
        body["close_link"] = True

    data = tool_api_call(
        "POST", f"/sessions/{request.session_id}/message", params={"computer": request.computer}, json_body=body
    )
    print_json(data)


def handle_sessions_tail(args: list[str]) -> None:
    """Get recent messages from a session's transcript.

    Usage: telec sessions tail <session_id> [--since <timestamp>]
                               [--tools] [--thinking] [--full] [--pane]

    Retrieves structured messages from the session's transcript files.
    Useful for inspecting what an agent has done or said recently.

    Options:
      --since <ISO8601>  Only messages after this UTC timestamp
      --tools            Include pre_tool_use/tool_result entries
      --thinking         Include thinking/reasoning blocks
      --full             Show all projected messages instead of the latest user turn
      --pane             Show the current terminal pane instead of transcript messages

    Examples:
      telec sessions tail abc123
      telec sessions tail abc123 --since 2024-01-01T00:00:00Z
      telec sessions tail abc123 --full
      telec sessions tail abc123 --pane
    """
    parsed = parse_command_args(SESSIONS_TAIL, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    session_id = parsed.value(F.FLAG_SESSION) or (positionals[0] if positionals else None)
    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)

    params: dict[str, str] = {}
    since = parsed.value(F.FLAG_TAIL_SINCE)
    explicit_since = since is not None
    if since is not None:
        params["since"] = since
    include_tools = parsed.has(F.FLAG_TAIL_TOOLS)
    if include_tools:
        params["include_tools"] = "true"
    include_thinking = parsed.has(F.FLAG_THINKING)
    if include_thinking:
        params["include_thinking"] = "true"
    show_full = parsed.has(F.FLAG_TAIL_FULL)
    show_pane = parsed.has(F.FLAG_TAIL_PANE)
    transcript_filter_selected = explicit_since or include_tools or include_thinking or show_full
    computer = parsed.value(F.FLAG_COMPUTER)
    if computer is not None:
        params["computer"] = computer

    if show_pane and transcript_filter_selected:
        print("Error: --pane cannot be combined with transcript filtering flags", file=sys.stderr)
        raise SystemExit(1)

    if show_pane:
        data = tool_api_call("GET", f"/sessions/{session_id}/pane", params=params)
    else:
        params["tail_scope"] = "all" if show_full or explicit_since else "latest_turn"
        data = tool_api_call("GET", f"/sessions/{session_id}/messages", params=params)
    print_json(data)


def handle_sessions_run(args: list[str]) -> None:
    """Run a canonical command on a new agent session.

    Usage: telec sessions run --command <cmd>
                              [--path <path>]
                              [--args <args>]
                              [--agent claude|gemini|codex|deepseek]
                              [--mode fast|med|slow]
                              [--computer <name>]
                              [--detach]

    Creates a new session and immediately runs the given bare canonical command with the
    specified arguments. Useful for dispatching worker commands like build.

    Options:
      --command <cmd>    Bare canonical command to run (e.g. build)
      --path <path>      Project directory path (default: cwd)
      --args <args>      Command arguments (e.g. "my-slug")
      --agent <name>     Agent to use (default: automatic role-aware target resolution)
      --mode <mode>      Thinking mode: fast, med, slow (omit to use job policy)
      --computer <name>  Target computer (optional; defaults to local)
      --subfolder <dir>  Subdirectory within the project
    Examples:
      telec sessions run --command build --args my-slug
      telec sessions run --command review-build --args my-slug --agent gemini
    """
    parsed = parse_command_args(SESSIONS_RUN, args)
    body: dict[str, object] = {  # guard: loose-dict - JSON request body
        "computer": "local",
        "args": "",
    }
    command = parsed.value(F.FLAG_RUN_COMMAND)
    if command is not None:
        body["command"] = command
    path = parsed.value(F.FLAG_PATH)
    if path is not None:
        body["project"] = path
    run_args = parsed.value(F.FLAG_RUN_ARGS)
    if run_args is not None:
        body["args"] = run_args
    agent = parsed.value(F.FLAG_AGENT)
    if agent is not None:
        body["agent"] = agent
    mode = parsed.value(F.FLAG_MODE)
    if mode is not None:
        body["thinking_mode"] = mode
    computer = parsed.value(F.FLAG_COMPUTER)
    if computer is not None:
        body["computer"] = computer
    subfolder = parsed.value(F.FLAG_RUN_SUBFOLDER)
    if subfolder is not None:
        body["subfolder"] = subfolder
    if parsed.has(F.FLAG_DETACH):
        body["detach"] = True
    additional_context = parsed.value(F.FLAG_RUN_ADDITIONAL_CONTEXT)
    if additional_context is not None:
        body["additional_context"] = additional_context
    company = parsed.value(F.FLAG_COMPANY)
    if company is not None:
        body["company"] = company
    if not body.get("command"):
        print("Error: --command is required", file=sys.stderr)
        raise SystemExit(1)
    address_computer(computer)
    if not body.get("project"):
        body["project"] = project_reference()

    data = tool_api_call("POST", "/sessions/run", json_body=body, timeout=SESSION_START_TIMEOUT_S)
    print_json(data)


def handle_sessions_run_pa(args: list[str]) -> None:
    """Start the caller's personal assistant.

    Usage: telec sessions run-pa [<brief>]
    """
    parsed = parse_command_args(SESSIONS_RUN_PA, args)
    if len(parsed.positionals) > 1:
        print(_SESSIONS_RUN_PA_ARGUMENT_ERROR, file=sys.stderr)
        raise SystemExit(1)

    body: dict[str, str] = {}
    if parsed.positionals:
        body[_SESSIONS_RUN_PA_BRIEF_FIELD] = parsed.positionals[0]

    data = tool_api_call(_POST_METHOD, _SESSIONS_RUN_PA_ENDPOINT, json_body=body)
    print_json(data)


def handle_sessions_end(args: list[str]) -> None:
    """End (terminate) a session.

    Usage: telec sessions end [<session_id>] [--computer <name>]

    session_id may be 'self' to end the caller's own session
    (resolved from $TMPDIR/teleclaude_identity.json).
    Without a session_id, closes every live direct child of the authenticated
    caller across computers.

    Gracefully terminates the session: kills the tmux session, closes the
    session record (which is retained), and cleans up all resources
    (listeners, workspace dirs).
    Ending a named session prints an operation receipt; the outcome is delivered
    to the calling session.

    Examples:
      telec sessions end
      telec sessions end abc123
      telec sessions end self
      telec sessions end abc123 --computer remote-macbook
    """
    parsed = parse_command_args(SESSIONS_END, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(_SESSION_END_DUPLICATE_TARGET_ERROR, file=sys.stderr)
        raise SystemExit(1)

    positional_session_id = positionals[0] if positionals else None
    if positional_session_id is not None and parsed.has(F.FLAG_SESSION):
        print(_SESSION_END_DUPLICATE_TARGET_ERROR, file=sys.stderr)
        raise SystemExit(1)

    target_specified = positional_session_id is not None or parsed.has(F.FLAG_SESSION)
    session_id = positional_session_id if positional_session_id is not None else parsed.value(F.FLAG_SESSION)

    computer_specified = parsed.has(F.FLAG_COMPUTER)
    computer = parsed.value(F.FLAG_COMPUTER) if computer_specified else "local"

    if not target_specified:
        if computer_specified:
            print("Error: --computer is not supported when ending caller child sessions", file=sys.stderr)
            raise SystemExit(1)
        _end_caller_child_sessions()
        return

    if session_id == "self":
        session_id = get_session_id()
        if not session_id:
            print("Error: could not resolve 'self' — $TMPDIR/teleclaude_identity.json not found", file=sys.stderr)
            raise SystemExit(1)

    render_receipt(tool_api_call("DELETE", f"/sessions/{session_id}", params={"computer": computer}))


def _end_caller_child_sessions() -> None:
    """Close every direct child of the authenticated caller and verify convergence."""
    if not get_session_id():
        print("Error: caller identity is required to end caller child sessions", file=sys.stderr)
        raise SystemExit(1)

    deadline = time.monotonic() + _BULK_END_TIMEOUT_S
    ended_session_ids: set[str] = set()
    residual_session_ids: list[str] = []

    while True:
        children = _list_caller_child_sessions()
        residual_session_ids = [session.session_id for session in children]
        if not children:
            print_json({"status": "success", "closed_session_ids": sorted(ended_session_ids)})
            return

        for child in children:
            try:
                tool_api_request(
                    "DELETE",
                    f"/sessions/{child.session_id}",
                    params={"computer": child.computer},
                )
            except ToolAPIError as exc:
                _fail_bulk_end(
                    _CLOSE_FAILURE_TEMPLATE.format(session_id=child.session_id, failure=_failure_text(exc)),
                    residual_session_ids,
                    cause=exc.not_accepted_cause,
                )
            ended_session_ids.add(child.session_id)

        if time.monotonic() >= deadline:
            _fail_bulk_end("timed out waiting for child sessions to close", residual_session_ids)
        time.sleep(_BULK_END_POLL_INTERVAL_S)


def _list_caller_child_sessions() -> list[SessionDTO]:
    """Read the caller-scoped child projection and reject malformed routing records."""
    from pydantic import TypeAdapter, ValidationError  # noqa: PLC0415 - deferred command-local dependency.

    from teleclaude.api_models import SessionDTO  # noqa: PLC0415 - deferred command-local dependency.

    adapter = TypeAdapter(list[SessionDTO])
    try:
        data = tool_api_request("GET", "/sessions")
        sessions = adapter.validate_python(data)
    except ToolAPIError as exc:
        print(_LIST_FAILURE_TEMPLATE.format(failure=_failure_text(exc)), file=sys.stderr)
        print_run_again_when_not_accepted(exc.not_accepted_cause)
        raise SystemExit(1) from exc
    except ValidationError as exc:
        print(_LIST_FAILURE_TEMPLATE.format(failure=exc), file=sys.stderr)
        raise SystemExit(1) from exc

    session_computers: dict[str, str] = {}
    for session in sessions:
        if not session.computer:
            print(f"Error: caller child session {session.session_id} is missing computer routing", file=sys.stderr)
            raise SystemExit(1)
        existing_computer = session_computers.setdefault(session.session_id, session.computer)
        if existing_computer != session.computer:
            print(f"Error: caller child session {session.session_id} has conflicting computer routing", file=sys.stderr)
            raise SystemExit(1)
    return sessions


def _failure_text(exc: ToolAPIError) -> str:
    """The failure in words; a refusal or an unreachable daemon is described without its response body."""
    cause = exc.not_accepted_cause
    return exc.message if cause is None else not_accepted_cause_text(cause)


def _fail_bulk_end(reason: str, residual_session_ids: list[str], *, cause: NotAcceptedCause | None = None) -> None:
    """Report an incomplete caller-scoped cleanup as a terminal command failure."""
    residuals = ", ".join(sorted(set(residual_session_ids)))
    print(_BULK_END_FAILURE_TEMPLATE.format(reason=reason, residuals=residuals), file=sys.stderr)
    print_run_again_when_not_accepted(cause)
    raise SystemExit(1)


def handle_sessions_restart(args: list[str]) -> None:
    """Restart an agent session.

    Usage: telec sessions restart <session_id>
           telec sessions restart self

    Triggers an agent restart for the target session and prints an operation
    receipt; the outcome is delivered to the calling session. When 'self' is
    given, restarts the caller's own session (resolved from
    $TMPDIR/teleclaude_identity.json).

    Examples:
      telec sessions restart self
      telec sessions restart abc123
    """
    parsed = parse_command_args(SESSIONS_RESTART, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    session_id = positionals[0] if positionals else None
    if not session_id:
        print("Error: session_id required (use 'self' for own session)", file=sys.stderr)
        raise SystemExit(1)
    self_restart = session_id == "self"
    computer = parsed.value(F.FLAG_COMPUTER) or "local"

    if session_id == "self":
        session_id = get_session_id()
        if not session_id:
            print("Error: could not resolve 'self' — $TMPDIR/teleclaude_identity.json not found", file=sys.stderr)
            raise SystemExit(1)

    handoff = parsed.has(F.FLAG_HANDOFF)
    handoff_agent = parsed.value(F.FLAG_HANDOFF)
    body: _RestartRequestBody | None = {"handoff": True, "agent": handoff_agent} if handoff else None
    if self_restart:
        body = {"self_restart": True, "handoff": True, "agent": handoff_agent} if handoff else {"self_restart": True}
    try:
        data = tool_api_call(
            "POST",
            f"/sessions/{session_id}/agent-restart",
            params={"computer": computer},
            json_body=body,
        )
        ok = True
    except Exception:
        data = None
        ok = False
    action = "Agent handoff started" if handoff else "Agent restarting"
    _emit_tmux_feedback(f"{action} ({session_id})..." if ok else f"Restart failed ({session_id})")
    if not ok:
        raise SystemExit(1)
    render_receipt(data)


def _emit_tmux_feedback(message: str) -> None:
    """Surface short status text via ``tmux display-message`` when invoked from tmux.

    ``tmux run-shell`` (used by keybindings like ``bind R``) swallows stdout, so
    the only way to give the operator visible feedback after a CLI action is to
    write back to the tmux UI. Owning this here keeps the keybinding side a
    one-liner and prevents shell logic from accreting in tmux.conf.
    """
    if not os.environ.get("TMUX"):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        return
    subprocess.run(["tmux", "display-message", message], check=False)


def handle_sessions_unsubscribe(args: list[str]) -> None:
    """Stop caring about a session — umbrella verb across both subscription axes.

    Usage: telec sessions unsubscribe <session_id>

    Removes the caller's listener for the target session AND severs any active
    direct link the caller holds with that target. Idempotent for a session that
    exists: empty state returns success with both action flags false. An unknown
    session id is refused as not found. The target session keeps running.

    Response payload reports which axis was actually cleared:
      { status, listener_removed, link_closed, link_id }

    Use `sessions send --close-link` instead if you only want to end the
    direct conversation but keep passive notifications. See
    local/projects/teleclaude/spec/session-subscriptions for the contract.

    Examples:
      telec sessions unsubscribe abc123def456
    """
    parsed = parse_command_args(SESSIONS_UNSUBSCRIBE, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    session_id = positionals[0] if positionals else None
    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)
    computer = parsed.value(F.FLAG_COMPUTER) or "local"

    data = tool_api_call("POST", f"/sessions/{session_id}/unsubscribe", params={"computer": computer})
    print_json(data)


def handle_sessions_result(args: list[str]) -> None:
    """Send a formatted result to the session's user as a separate message.

    Usage: telec sessions result <content> [--format markdown|html]

    Sends formatted content through the session's adapter (Telegram, Discord,
    etc.) as a persistent message visible to the human user. Use this to
    deliver reports, summaries, or structured output to the user.

    The caller's session is resolved automatically from the environment.

    Options:
      --format markdown|html   Output format (default: markdown)

    Examples:
      telec sessions result "## Summary\n\nAll 5 tasks completed."
      telec sessions result "<h2>Done</h2>" --format html
    """
    parsed = parse_command_args(SESSIONS_RESULT, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print(f"Error: unexpected argument: {positionals[1]}", file=sys.stderr)
        raise SystemExit(1)
    content = positionals[0] if positionals else parsed.value(F.FLAG_RESULT_CONTENT_ALIAS)
    output_format = parsed.value(F.FLAG_RESULT_FORMAT) or "markdown"

    if not content:
        print("Error: content required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call(
        "POST",
        "/sessions/self/result",
        json_body={"content": content, "output_format": output_format},
    )
    print_json(data)


def handle_sessions_coordinate(args: list[str]) -> None:
    """Adopt this session as the project's single coordinator (human-directed only; refuses if one is live)"""
    if any(argument in _COORDINATE_HELP_FLAGS for argument in args):
        print(handle_sessions_coordinate.__doc__ or "")
        return
    data = tool_api_call(_POST_METHOD, _COORDINATE_ENDPOINT)
    print_json(data)


def handle_sessions_file(args: list[str]) -> None:
    """Send a file to the session's user.

    Usage: telec sessions file --path <file_path>
                               --filename <name> [--caption <text>]

    Sends a file through the session's adapter. The file must be accessible on
    the daemon's filesystem. The caller's session is resolved automatically
    from the environment.

    Options:
      --path <path>       Absolute path to the file on the daemon host
      --filename <name>   Display filename
      --caption <text>    Optional caption accompanying the file

    Examples:
      telec sessions file --path /tmp/report.pdf --filename report.pdf
      telec sessions file --path /data/img.png --filename img.png --caption "See this"
    """
    parsed = parse_command_args(SESSIONS_FILE, args)
    body: dict[str, object] = {"file_size": 0}  # guard: loose-dict - JSON request body
    file_path = parsed.value(F.FLAG_FILE_PATH)
    if file_path is not None:
        body["file_path"] = file_path
    filename = parsed.value(F.FLAG_FILE_FILENAME)
    if filename is not None:
        body["filename"] = filename
    caption = parsed.value(F.FLAG_FILE_CAPTION)
    if caption is not None:
        body["caption"] = caption

    if not body.get("file_path"):
        print("Error: --path is required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("filename"):
        print("Error: --filename is required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", "/sessions/self/file", json_body=body)
    print_json(data)


def handle_sessions_escalate(args: list[str]) -> None:
    """Escalate a help-desk visitor to everyone in the desk's scope.

    Usage: telec sessions escalate --customer <name> --reason <text>
                                   [--summary <context>]

    Opens a thread in the desk's escalations forum and notifies the desk's
    scope with a link to it. The thread carries the relay: visitor messages
    appear there, replies reach the visitor, and tagging the agent hands the
    conversation back. Accepted only from a help-desk session; the caller's
    session is resolved automatically from the environment.

    Options:
      --customer <name>   The visitor's name, as they gave it
      --reason <text>     Reason for escalation (briefly described)
      --summary <text>    Optional context summary for the people notified

    Examples:
      telec sessions escalate --customer "John Doe" --reason "billing dispute"
      telec sessions escalate --customer "Jane" --reason "urgent bug" --summary "App crashes on login"
    """
    parsed = parse_command_args(SESSIONS_ESCALATE, args)
    body: dict[str, object] = {}  # guard: loose-dict - JSON request body
    customer = parsed.value(F.FLAG_ESCALATE_CUSTOMER)
    if customer is not None:
        body["customer_name"] = customer
    reason = parsed.value(F.FLAG_ESCALATE_REASON)
    if reason is not None:
        body["reason"] = reason
    summary = parsed.value(F.FLAG_ESCALATE_SUMMARY)
    if summary is not None:
        body["context_summary"] = summary

    if not body.get("customer_name"):
        print("Error: --customer is required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("reason"):
        print("Error: --reason is required", file=sys.stderr)
        raise SystemExit(1)

    result = tool_api_call("POST", "/sessions/self/escalate", json_body=body)
    print_json(result)

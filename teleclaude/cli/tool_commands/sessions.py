"""Sessions subcommand handlers for telec sessions <subcommand>.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).
"""

from __future__ import annotations

import sys

from teleclaude.cli.tool_client import _read_caller_session_id, print_json, tool_api_call

__all__ = [
    "handle_sessions",
    "handle_sessions_end",
    "handle_sessions_escalate",
    "handle_sessions_file",
    "handle_sessions_list",
    "handle_sessions_restart",
    "handle_sessions_result",
    "handle_sessions_run",
    "handle_sessions_send",
    "handle_sessions_start",
    "handle_sessions_tail",
    "handle_sessions_unsubscribe",
    "handle_sessions_widget",
]


def handle_sessions(args: list[str]) -> None:
    """Handle telec sessions <subcommand> [args].

    Subcommands:
      list        List sessions (default: spawned by current, --all for all)
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
      widget      Render a widget to the user (implicit session)
      escalate    Escalate to an admin via Discord (implicit session)
    """
    if not args or args[0] in ("-h", "--help"):
        _sessions_help()
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        handle_sessions_list(rest)
    elif sub == "start":
        handle_sessions_start(rest)
    elif sub == "send":
        handle_sessions_send(rest)
    elif sub == "tail":
        handle_sessions_tail(rest)
    elif sub == "run":
        handle_sessions_run(rest)
    elif sub == "revive":
        # Keep revive behavior centralized in telec CLI entrypoint since it
        # includes post-revive kick and optional tmux attach semantics.
        from teleclaude.cli.telec.handlers.misc import _handle_revive

        _handle_revive(rest)
    elif sub == "end":
        handle_sessions_end(rest)
    elif sub == "unsubscribe":
        handle_sessions_unsubscribe(rest)
    elif sub == "result":
        handle_sessions_result(rest)
    elif sub == "file":
        handle_sessions_file(rest)
    elif sub == "widget":
        handle_sessions_widget(rest)
    elif sub == "escalate":
        handle_sessions_escalate(rest)
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
  widget       Render a rich widget to the user (implicit session)
  escalate     Escalate to an admin via Discord (implicit session)

Run 'telec sessions <subcommand> --help' for subcommand-specific help."""
    )


def handle_sessions_list(args: list[str]) -> None:
    """List sessions.

    Usage: telec sessions list [--all] [--closed] [--job <job>]

    Without --all, lists only sessions spawned by the current session.
    With --all, lists all sessions on the local computer.
    With --closed, includes closed sessions.
    With --job <job>, filters to sessions whose session_metadata.job matches.

    Examples:
      telec sessions list
      telec sessions list --all
      telec sessions list --all --closed
      telec sessions list --all --job integrator
    """
    show_all = "--all" in args
    closed = "--closed" in args
    params: dict[str, str] = {}
    if show_all:
        params["all"] = "true"
    if closed:
        params["closed"] = "true"
    job_filter = None
    for i, arg in enumerate(args):
        if arg == "--job" and i + 1 < len(args):
            job_filter = args[i + 1]
            break
    if job_filter:
        params["job"] = job_filter
    data = tool_api_call("GET", "/sessions", params=params)
    print_json(data)


def handle_sessions_start(args: list[str]) -> None:
    """Start a new agent session.

    Usage: telec sessions start --project <path>
                                [--computer <name>]
                                [--agent claude|gemini|codex]
                                [--mode fast|med|slow]
                                [--message <text>]
                                [--title <text>]
                                [--direct]
                                [--detach]

    Creates a new TeleClaude agent session on the specified computer in the
    given project directory. The agent starts immediately.

    Examples:
      telec sessions start --project /path/to/project
      telec sessions start --project /path/to/project --agent claude --mode slow
      telec sessions start --project /p/to/p --message "Implement feature X"
      telec sessions start --project /path/to/project --computer remote-macbook
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_start.__doc__ or "")
        return

    body: dict[str, object] = {"computer": "local", "launch_kind": "agent"}  # guard: loose-dict - JSON request body
    i = 0
    while i < len(args):
        if args[i] == "--computer" and i + 1 < len(args):
            body["computer"] = args[i + 1]
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            body["project_path"] = args[i + 1]
            i += 2
        elif args[i] == "--agent" and i + 1 < len(args):
            body["agent"] = args[i + 1]
            i += 2
        elif args[i] == "--mode" and i + 1 < len(args):
            body["thinking_mode"] = args[i + 1]
            i += 2
        elif args[i] == "--message" and i + 1 < len(args):
            body["message"] = args[i + 1]
            body["launch_kind"] = "agent_then_message"
            i += 2
        elif args[i] == "--title" and i + 1 < len(args):
            body["title"] = args[i + 1]
            i += 2
        elif args[i] == "--direct":
            body["direct"] = True
            i += 1
        elif args[i] == "--detach":
            body["skip_listener_registration"] = True
            i += 1
        else:
            i += 1

    if not body.get("project_path"):
        print("Error: --project is required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", "/sessions", json_body=body)
    print_json(data)


def handle_sessions_send(args: list[str]) -> None:
    """Send a message to a running session.

    Usage: telec sessions send <session_id> [<message>] [--direct]
           telec sessions send <session_id> --close-link
           telec sessions send --session <session_id> --message <text> [--direct]  # compatibility

    Delivers a message to the target session.
    With --direct, create a shared conversation link.
    With --close-link, sever a shared conversation link.

    Examples:
      telec sessions send abc123 "Please implement feature X"
      telec sessions send abc123 "Let's discuss the architecture" --direct
      telec sessions send abc123 --close-link
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_send.__doc__ or "")
        return

    session_id: str | None = None
    message: str | None = None
    direct = False
    close_link = False
    positional_message_parts: list[str] = []

    positional_mode = bool(args and not args[0].startswith("-"))
    if positional_mode:
        session_id = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] in ("--session", "-s") and i + 1 < len(args):
            if positional_mode:
                print("Error: do not combine positional session_id with --session", file=sys.stderr)
                raise SystemExit(1)
            session_id = args[i + 1]
            i += 2
        elif args[i] in ("--message", "-m") and i + 1 < len(args):
            message = args[i + 1]
            i += 2
        elif args[i] == "--direct":
            direct = True
            i += 1
        elif args[i] in ("--close-link", "--close_link"):
            close_link = True
            i += 1
        elif positional_mode:
            positional_message_parts.append(args[i])
            i += 1
        else:
            i += 1

    if positional_message_parts:
        if message is not None:
            print("Error: do not combine positional message with --message", file=sys.stderr)
            raise SystemExit(1)
        message = " ".join(positional_message_parts)

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)
    if not close_link and not message:
        print("Error: message required", file=sys.stderr)
        raise SystemExit(1)

    body: dict[str, str | bool] = {}
    if message:
        body["message"] = message
    if direct:
        body["direct"] = True
    if close_link:
        body["close_link"] = True

    data = tool_api_call("POST", f"/sessions/{session_id}/message", json_body=body)
    print_json(data)


def handle_sessions_tail(args: list[str]) -> None:
    """Get recent messages from a session's transcript.

    Usage: telec sessions tail <session_id> [--since <timestamp>]
                               [--tools] [--thinking]

    Retrieves structured messages from the session's transcript files.
    Useful for inspecting what an agent has done or said recently.

    Options:
      --since <ISO8601>  Only messages after this UTC timestamp
      --tools            Include tool_use/tool_result entries
      --thinking         Include thinking/reasoning blocks

    Examples:
      telec sessions tail abc123
      telec sessions tail abc123 --since 2024-01-01T00:00:00Z
      telec sessions tail abc123 --tools --thinking
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_tail.__doc__ or "")
        return

    session_id: str | None = None
    params: dict[str, str] = {}

    if args and not args[0].startswith("-"):
        session_id = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] == "--since" and i + 1 < len(args):
            params["since"] = args[i + 1]
            i += 2
        elif args[i] == "--tools":
            params["include_tools"] = "true"
            i += 1
        elif args[i] == "--thinking":
            params["include_thinking"] = "true"
            i += 1
        elif args[i] in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        else:
            i += 1

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("GET", f"/sessions/{session_id}/messages", params=params)
    print_json(data)


def handle_sessions_run(args: list[str]) -> None:
    """Run a slash command on a new agent session.

    Usage: telec sessions run --command <cmd> --project <path>
                              [--args <args>]
                              [--agent claude|gemini|codex]
                              [--mode fast|med|slow]
                              [--computer <name>]
                              [--detach]

    Creates a new session and immediately runs the given slash command with the
    specified arguments. Useful for dispatching worker commands like /next-build.

    Options:
      --command <cmd>    Slash command to run (e.g. /next-build)
      --project <path>   Project directory path
      --args <args>      Command arguments (e.g. "my-slug")
      --agent <name>     Agent to use (default: first enabled agent)
      --mode <mode>      Thinking mode: fast, med, slow (default: slow)
      --computer <name>  Target computer (optional; defaults to local)
      --subfolder <dir>  Subdirectory within the project

    Examples:
      telec sessions run --command /next-build --args my-slug --project /path/to/project
      telec sessions run --command /next-review-build --args my-slug --project /p --agent gemini
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_run.__doc__ or "")
        return

    body: dict[str, object] = {  # guard: loose-dict - JSON request body
        "computer": "local",
        "thinking_mode": "slow",
        "args": "",
    }
    i = 0
    while i < len(args):
        if args[i] == "--command" and i + 1 < len(args):
            body["command"] = args[i + 1]
            i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            body["project"] = args[i + 1]
            i += 2
        elif args[i] == "--args" and i + 1 < len(args):
            body["args"] = args[i + 1]
            i += 2
        elif args[i] == "--agent" and i + 1 < len(args):
            body["agent"] = args[i + 1]
            i += 2
        elif args[i] == "--mode" and i + 1 < len(args):
            body["thinking_mode"] = args[i + 1]
            i += 2
        elif args[i] == "--computer" and i + 1 < len(args):
            body["computer"] = args[i + 1]
            i += 2
        elif args[i] == "--subfolder" and i + 1 < len(args):
            body["subfolder"] = args[i + 1]
            i += 2
        elif args[i] == "--detach":
            body["detach"] = True
            i += 1
        elif args[i] == "--additional-context" and i + 1 < len(args):
            body["additional_context"] = args[i + 1]
            i += 2
        else:
            i += 1

    if not body.get("command"):
        print("Error: --command is required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("project"):
        print("Error: --project is required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", "/sessions/run", json_body=body)
    print_json(data)


def handle_sessions_end(args: list[str]) -> None:
    """End (terminate) a session.

    Usage: telec sessions end <session_id> [--computer <name>]

    session_id may be 'self' to end the caller's own session
    (resolved from $TMPDIR/teleclaude_session_id).

    Gracefully terminates the session: kills the tmux session, deletes the
    session record, and cleans up all resources (listeners, workspace dirs).

    Examples:
      telec sessions end abc123
      telec sessions end self
      telec sessions end abc123 --computer remote-macbook
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_end.__doc__ or "")
        return

    session_id: str | None = None
    computer = "local"

    if args and not args[0].startswith("-"):
        session_id = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--computer" and i + 1 < len(args):
            computer = args[i + 1]
            i += 2
        else:
            i += 1

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)

    if session_id == "self":
        session_id = _read_caller_session_id()
        if not session_id:
            print("Error: could not resolve 'self' — $TMPDIR/teleclaude_session_id not found", file=sys.stderr)
            raise SystemExit(1)

    data = tool_api_call("DELETE", f"/sessions/{session_id}", params={"computer": computer})
    print_json(data)


def handle_sessions_restart(args: list[str]) -> None:
    """Restart an agent session.

    Usage: telec sessions restart <session_id>
           telec sessions restart self

    Triggers an agent restart for the target session. When 'self' is given,
    restarts the caller's own session (resolved from
    $TMPDIR/teleclaude_session_id).

    Examples:
      telec sessions restart self
      telec sessions restart abc123
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_restart.__doc__ or "")
        return

    session_id: str | None = None

    if args and not args[0].startswith("-"):
        session_id = args[0]

    if not session_id:
        print("Error: session_id required (use 'self' for own session)", file=sys.stderr)
        raise SystemExit(1)

    if session_id == "self":
        session_id = _read_caller_session_id()
        if not session_id:
            print("Error: could not resolve 'self' — $TMPDIR/teleclaude_session_id not found", file=sys.stderr)
            raise SystemExit(1)

    data = tool_api_call("POST", f"/sessions/{session_id}/agent-restart")
    print_json(data)


def handle_sessions_unsubscribe(args: list[str]) -> None:
    """Stop receiving notifications from a session without ending it.

    Usage: telec sessions unsubscribe <session_id>

    Removes the caller's listener for the target session. The session continues
    running, but the caller no longer receives events from it. Use this to
    detach from a monitored session while leaving it running.

    This requires a valid session identity (X-Caller-Session-Id header). The
    daemon will verify that the caller has an active listener for the target.

    Examples:
      telec sessions unsubscribe abc123def456
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_unsubscribe.__doc__ or "")
        return

    session_id: str | None = None
    if args and not args[0].startswith("-"):
        session_id = args[0]

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", f"/sessions/{session_id}/unsubscribe")
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
    if "--help" in args or "-h" in args:
        print(handle_sessions_result.__doc__ or "")
        return

    content: str | None = None
    output_format = "markdown"

    if args and not args[0].startswith("-"):
        content = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] == "--content" and i + 1 < len(args):
            content = args[i + 1]
            i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        else:
            i += 1

    if not content:
        print("Error: content required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call(
        "POST",
        "/sessions/self/result",
        json_body={"content": content, "output_format": output_format},
    )
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
    if "--help" in args or "-h" in args:
        print(handle_sessions_file.__doc__ or "")
        return

    body: dict[str, object] = {"file_size": 0}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if args[i] == "--path" and i + 1 < len(args):
            body["file_path"] = args[i + 1]
            i += 2
        elif args[i] == "--filename" and i + 1 < len(args):
            body["filename"] = args[i + 1]
            i += 2
        elif args[i] == "--caption" and i + 1 < len(args):
            body["caption"] = args[i + 1]
            i += 2
        else:
            i += 1

    if not body.get("file_path"):
        print("Error: --path is required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("filename"):
        print("Error: --filename is required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", "/sessions/self/file", json_body=body)
    print_json(data)


def handle_sessions_widget(args: list[str]) -> None:
    """Render a rich widget expression to the session's user.

    Usage: telec sessions widget --data <json>

    Renders a widget expression: generates a text summary and sends it to the
    session's adapter (Telegram, Discord). Named widgets are stored for later
    retrieval. The caller's session is resolved automatically from the
    environment.

    Widget sections: text, input, actions, image, table, file, code, divider.

    Options:
      --data <json>   Widget expression as a JSON string

    Examples:
      telec sessions widget --data '{"title":"Done","sections":[{"type":"text","content":"OK"}]}'
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_widget.__doc__ or "")
        return

    import json

    data_str: str | None = None

    i = 0
    while i < len(args):
        if args[i] == "--data" and i + 1 < len(args):
            data_str = args[i + 1]
            i += 2
        else:
            i += 1

    if not data_str:
        print("Error: --data is required", file=sys.stderr)
        raise SystemExit(1)

    try:
        widget_data = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON for --data: {e}", file=sys.stderr)
        raise SystemExit(1)

    result = tool_api_call("POST", "/sessions/self/widget", json_body={"data": widget_data})
    print_json(result)


def handle_sessions_escalate(args: list[str]) -> None:
    """Escalate a customer session to an admin via Discord.

    Usage: telec sessions escalate --customer <name> --reason <text>
                                   [--summary <context>]

    Creates a Discord thread in the escalation forum channel, notifies admins,
    and activates relay mode on the session so admin messages are forwarded to
    the customer. The caller's session is resolved automatically from the
    environment.

    Options:
      --customer <name>   Customer name for the escalation thread
      --reason <text>     Reason for escalation (briefly described)
      --summary <text>    Optional context summary for the admin

    Examples:
      telec sessions escalate --customer "John Doe" --reason "billing dispute"
      telec sessions escalate --customer "Jane" --reason "urgent bug" --summary "App crashes on login"
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_escalate.__doc__ or "")
        return

    body: dict[str, object] = {}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if args[i] == "--customer" and i + 1 < len(args):
            body["customer_name"] = args[i + 1]
            i += 2
        elif args[i] == "--reason" and i + 1 < len(args):
            body["reason"] = args[i + 1]
            i += 2
        elif args[i] == "--summary" and i + 1 < len(args):
            body["context_summary"] = args[i + 1]
            i += 2
        else:
            i += 1

    if not body.get("customer_name"):
        print("Error: --customer is required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("reason"):
        print("Error: --reason is required", file=sys.stderr)
        raise SystemExit(1)

    result = tool_api_call("POST", "/sessions/self/escalate", json_body=body)
    print_json(result)

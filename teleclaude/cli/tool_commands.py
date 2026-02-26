"""CLI subcommand handlers for telec tool subcommands.

All commands call the daemon REST API via tool_api_call() and print JSON to stdout.
Errors go to stderr with exit code 1 (handled by tool_api_call).

Handler naming: handle_{group}_{subcommand} for grouped commands,
handle_{command} for top-level commands.
"""

from __future__ import annotations

import sys

from teleclaude.cli.tool_client import print_json, tool_api_call

# =============================================================================
# Sessions group
# =============================================================================


def handle_sessions(args: list[str]) -> None:
    """Handle telec sessions <subcommand> [args].

    Subcommands:
      list        List sessions (default: spawned by current, --all for all)
      start       Start a new agent session
      send        Send a message to a session
      tail        Get recent messages from a session
      run         Run a slash command on a new agent session
      end         End a session
      unsubscribe Stop receiving notifications from a session
      result      Send a formatted result to the session's user
      file        Send a file to the session
      widget      Render a widget to the session's user
      escalate    Escalate a customer session via Discord
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
  end          End (terminate) a session
  unsubscribe  Stop receiving notifications from a session
  result       Send a formatted result message to the session's user
  file         Send a file to a session
  widget       Render a rich widget to the session's user
  escalate     Escalate a customer session to an admin via Discord

Run 'telec sessions <subcommand> --help' for subcommand-specific help."""
    )


def handle_sessions_list(args: list[str]) -> None:
    """List sessions.

    Usage: telec sessions list [--all] [--closed]

    Without --all, lists only sessions spawned by the current session.
    With --all, lists all sessions on the local computer.
    With --closed, includes closed sessions.

    Examples:
      telec sessions list
      telec sessions list --all
      telec sessions list --all --closed
    """
    show_all = "--all" in args
    closed = "--closed" in args
    params: dict[str, str] = {}
    if show_all:
        params["all"] = "true"
    if closed:
        params["closed"] = "true"
    data = tool_api_call("GET", "/sessions", params=params)
    print_json(data)


def handle_sessions_start(args: list[str]) -> None:
    """Start a new agent session.

    Usage: telec sessions start --computer <name> --project <path>
                                [--agent claude|gemini|codex]
                                [--mode fast|med|slow]
                                [--message <text>]
                                [--title <text>]

    Creates a new TeleClaude agent session on the specified computer in the
    given project directory. The agent starts immediately.

    Examples:
      telec sessions start --computer local --project /path/to/project
      telec sessions start --computer local --project /path/to/project --agent claude --mode slow
      telec sessions start --computer local --project /p/to/p --message "Implement feature X"
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
        else:
            i += 1

    if not body.get("project_path"):
        print("Error: --project is required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", "/sessions", json_body=body)
    print_json(data)


def handle_sessions_send(args: list[str]) -> None:
    """Send a message to a running session.

    Usage: telec sessions send <session_id> <message>
                               OR
           telec sessions send --session <session_id> --message <text>

    Delivers a text message to the agent running in the target session.
    The agent will process the message as user input.

    Examples:
      telec sessions send abc123 "Please implement feature X"
      telec sessions send --session abc123 --message "Please review this code"
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_send.__doc__ or "")
        return

    session_id: str | None = None
    message: str | None = None

    # Positional: telec sessions send <session_id> <message>
    if args and not args[0].startswith("-"):
        session_id = args[0]
        message = " ".join(args[1:]) if len(args) > 1 else None
    else:
        i = 0
        while i < len(args):
            if args[i] in ("--session", "-s") and i + 1 < len(args):
                session_id = args[i + 1]
                i += 2
            elif args[i] == "--message" and i + 1 < len(args):
                message = args[i + 1]
                i += 2
            else:
                i += 1

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)
    if not message:
        print("Error: message required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", f"/sessions/{session_id}/message", json_body={"message": message})
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
                              [--computer local]

    Creates a new session and immediately runs the given slash command with the
    specified arguments. Useful for dispatching worker commands like /next-build.

    Options:
      --command <cmd>    Slash command to run (e.g. /next-build)
      --project <path>   Project directory path
      --args <args>      Command arguments (e.g. "my-slug")
      --agent <name>     Agent to use (default: first enabled agent)
      --mode <mode>      Thinking mode: fast, med, slow (default: slow)
      --computer <name>  Target computer (default: local)
      --subfolder <dir>  Subdirectory within the project

    Examples:
      telec sessions run --command /next-build --args my-slug --project /path/to/project
      telec sessions run --command /next-review --args my-slug --project /p --agent gemini
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

    Usage: telec sessions end <session_id> [--computer local]

    Gracefully terminates the session: kills the tmux session, deletes the
    session record, and cleans up all resources (listeners, workspace dirs).

    Examples:
      telec sessions end abc123
      telec sessions end abc123 --computer local
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

    data = tool_api_call("DELETE", f"/sessions/{session_id}", params={"computer": computer})
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

    Usage: telec sessions result <session_id> <content>
                                 [--format markdown|html]

    Sends formatted content through the session's adapter (Telegram, Discord,
    etc.) as a persistent message visible to the human user. Use this to
    deliver reports, summaries, or structured output to the user.

    The content is sent as a separate message from the agent's conversation
    flow, clearly marked as a result. Supports markdown and HTML formatting.

    Options:
      --format markdown|html   Output format (default: markdown)

    Examples:
      telec sessions result abc123 "## Summary\n\nAll 5 tasks completed."
      telec sessions result abc123 "<h2>Done</h2>" --format html
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_result.__doc__ or "")
        return

    session_id: str | None = None
    content: str | None = None
    output_format = "markdown"

    if args and not args[0].startswith("-"):
        session_id = args[0]
        args = args[1:]
        if args and not args[0].startswith("-"):
            content = args[0]
            args = args[1:]

    i = 0
    while i < len(args):
        if args[i] in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--content" and i + 1 < len(args):
            content = args[i + 1]
            i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        else:
            i += 1

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)
    if not content:
        print("Error: content required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call(
        "POST",
        f"/sessions/{session_id}/result",
        json_body={"content": content, "output_format": output_format},
    )
    print_json(data)


def handle_sessions_file(args: list[str]) -> None:
    """Send a file to a session.

    Usage: telec sessions file <session_id> --path <file_path>
                               --filename <name> [--caption <text>]

    Sends a file as input to the session. The file must be accessible on the
    daemon's filesystem. Used to provide documents, images, or data files to
    the agent for processing.

    Options:
      --path <path>       Absolute path to the file on the daemon host
      --filename <name>   Display filename
      --caption <text>    Optional caption accompanying the file

    Examples:
      telec sessions file abc123 --path /tmp/report.pdf --filename report.pdf
      telec sessions file abc123 --path /data/img.png --filename img.png --caption "See this"
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_file.__doc__ or "")
        return

    session_id: str | None = None
    body: dict[str, object] = {"file_size": 0}  # guard: loose-dict - JSON request body

    if args and not args[0].startswith("-"):
        session_id = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--path" and i + 1 < len(args):
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

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("file_path"):
        print("Error: --path is required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("filename"):
        print("Error: --filename is required", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", f"/sessions/{session_id}/file", json_body=body)
    print_json(data)


def handle_sessions_widget(args: list[str]) -> None:
    """Render a rich widget expression to the session's user.

    Usage: telec sessions widget <session_id> --data <json>

    Renders a widget expression: generates a text summary and sends it to the
    session's adapter (Telegram, Discord). Named widgets are stored for later
    retrieval. The data must be a valid widget expression JSON object.

    Widget sections: text, input, actions, image, table, file, code, divider.
    See the TeleClaude tool API documentation for the full widget schema.

    Options:
      --data <json>   Widget expression as a JSON string

    Examples:
      telec sessions widget abc123 --data '{"title":"Done","sections":[{"type":"text","content":"OK"}]}'
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_widget.__doc__ or "")
        return

    import json

    session_id: str | None = None
    data_str: str | None = None

    if args and not args[0].startswith("-"):
        session_id = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--data" and i + 1 < len(args):
            data_str = args[i + 1]
            i += 2
        else:
            i += 1

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)
    if not data_str:
        print("Error: --data is required", file=sys.stderr)
        raise SystemExit(1)

    try:
        widget_data = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON for --data: {e}", file=sys.stderr)
        raise SystemExit(1)

    result = tool_api_call("POST", f"/sessions/{session_id}/widget", json_body={"data": widget_data})
    print_json(result)


def handle_sessions_escalate(args: list[str]) -> None:
    """Escalate a customer session to an admin via Discord.

    Usage: telec sessions escalate <session_id> --customer <name> --reason <text>
                                   [--summary <context>]

    Creates a Discord thread in the escalation forum channel, notifies admins,
    and activates relay mode on the session so admin messages are forwarded to
    the customer. Only available for sessions with human_role='customer'.

    Requires Discord adapter to be configured and active. The session must be
    a customer session (human_role='customer').

    Options:
      --customer <name>   Customer name for the escalation thread
      --reason <text>     Reason for escalation (briefly described)
      --summary <text>    Optional context summary for the admin

    Examples:
      telec sessions escalate abc123 --customer "John Doe" --reason "billing dispute"
      telec sessions escalate abc123 --customer "Jane" --reason "urgent bug" --summary "App crashes on login"
    """
    if "--help" in args or "-h" in args:
        print(handle_sessions_escalate.__doc__ or "")
        return

    session_id: str | None = None
    body: dict[str, object] = {}  # guard: loose-dict - JSON request body

    if args and not args[0].startswith("-"):
        session_id = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--customer" and i + 1 < len(args):
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

    if not session_id:
        print("Error: session_id required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("customer_name"):
        print("Error: --customer is required", file=sys.stderr)
        raise SystemExit(1)
    if not body.get("reason"):
        print("Error: --reason is required", file=sys.stderr)
        raise SystemExit(1)

    result = tool_api_call("POST", f"/sessions/{session_id}/escalate", json_body=body)
    print_json(result)


# =============================================================================
# Todo workflow subcommands (extend existing "telec todo" group)
# =============================================================================


def handle_todo_prepare(args: list[str]) -> None:
    """Run the Phase A (prepare) state machine.

    Usage: telec todo prepare [<slug>] [--cwd <dir>] [--no-hitl]

    Checks preparation state for the given slug and returns instructions for
    the next action: draft artifacts (if not started), gate review (if draft
    complete), or signal already prepared (if gate passed).

    When called without a slug, selects the next unprepared work item from the
    roadmap. Requires orchestrator clearance (not available to workers).

    Options:
      <slug>       Work item slug (optional; auto-selects if omitted)
      --cwd <dir>  Project root directory (default: daemon's default_working_dir)
      --no-hitl    Disable human-in-the-loop gate prompts

    Examples:
      telec todo prepare
      telec todo prepare my-feature
      telec todo prepare my-feature --cwd /path/to/project
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_prepare.__doc__ or "")
        return

    body: dict[str, object] = {"hitl": True}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if args[i] == "--cwd" and i + 1 < len(args):
            body["cwd"] = args[i + 1]
            i += 2
        elif args[i] == "--no-hitl":
            body["hitl"] = False
            i += 1
        elif not args[i].startswith("-"):
            body["slug"] = args[i]
            i += 1
        else:
            i += 1

    data = tool_api_call("POST", "/todos/prepare", json_body=body)
    print_json(data)


def handle_todo_work(args: list[str]) -> None:
    """Run the Phase B (work) state machine.

    Usage: telec todo work [<slug>] --cwd <dir>

    Executes the build/review/fix cycle on prepared work items. Dispatches
    worker agents for build, review, or fix-review phases as determined by the
    current state of the slug.

    Requires orchestrator clearance — workers cannot invoke this on themselves.
    The --cwd flag is required and must point to the project root.

    Options:
      <slug>       Work item slug (optional; auto-selects next ready item)
      --cwd <dir>  Project root directory (REQUIRED)

    Examples:
      telec todo work --cwd /path/to/project
      telec todo work my-feature --cwd /path/to/project
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_work.__doc__ or "")
        return

    body: dict[str, object] = {}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if args[i] == "--cwd" and i + 1 < len(args):
            body["cwd"] = args[i + 1]
            i += 2
        elif not args[i].startswith("-"):
            body["slug"] = args[i]
            i += 1
        else:
            i += 1

    if not body.get("cwd"):
        print("Error: --cwd is required for todo work", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", "/todos/work", json_body=body)
    print_json(data)


def handle_todo_maintain(args: list[str]) -> None:
    """Run the Phase D (maintain) state machine.

    Usage: telec todo maintain --cwd <dir>

    Executes maintenance steps for infrastructure upkeep. Currently returns a
    stub message indicating maintenance procedures are not yet defined.

    Options:
      --cwd <dir>  Project root directory (REQUIRED)

    Examples:
      telec todo maintain --cwd /path/to/project
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_maintain.__doc__ or "")
        return

    body: dict[str, object] = {}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if args[i] == "--cwd" and i + 1 < len(args):
            body["cwd"] = args[i + 1]
            i += 2
        else:
            i += 1

    if not body.get("cwd"):
        print("Error: --cwd is required for todo maintain", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", "/todos/maintain", json_body=body)
    print_json(data)


def handle_todo_mark_phase(args: list[str]) -> None:
    """Mark a work phase as complete/approved in state.yaml.

    Usage: telec todo mark-phase <slug> --phase <phase> --status <status>
                                  --cwd <dir>

    Updates the phase status for the given slug in its state.yaml file.
    For terminal statuses (complete, approved), the worktree must have no
    uncommitted changes and no stash debt.

    Options:
      <slug>          Work item slug
      --phase <p>     Phase to mark: build or review
      --status <s>    New status: pending, started, complete, approved,
                      or changes_requested
      --cwd <dir>     Project root directory (REQUIRED)

    Examples:
      telec todo mark-phase my-slug --phase build --status complete --cwd /path/to/project
      telec todo mark-phase my-slug --phase review --status approved --cwd /path/to/project
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_mark_phase.__doc__ or "")
        return

    body: dict[str, object] = {}  # guard: loose-dict - JSON request body

    i = 0
    while i < len(args):
        if args[i] == "--phase" and i + 1 < len(args):
            body["phase"] = args[i + 1]
            i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            body["status"] = args[i + 1]
            i += 2
        elif args[i] == "--cwd" and i + 1 < len(args):
            body["cwd"] = args[i + 1]
            i += 2
        elif not args[i].startswith("-"):
            body["slug"] = args[i]
            i += 1
        else:
            i += 1

    for req in ("slug", "phase", "status", "cwd"):
        if not body.get(req):
            print(f"Error: --{req} is required" if req != "slug" else "Error: slug is required", file=sys.stderr)
            raise SystemExit(1)

    data = tool_api_call("POST", "/todos/mark-phase", json_body=body)
    print_json(data)


def handle_todo_set_deps(args: list[str]) -> None:
    """Set dependencies for a work item in the roadmap.

    Usage: telec todo set-deps <slug> --after <dep1> [<dep2> ...] --cwd <dir>
                               OR
           telec todo set-deps <slug> --cwd <dir>   (clears all dependencies)

    Replaces all existing dependencies for the slug with the given list.
    Pass no --after flags to clear all dependencies. Validates all slugs
    against roadmap.yaml and detects circular dependencies.

    Options:
      <slug>           Work item slug
      --after <slug>   Dependency slug (can be repeated for multiple deps)
      --cwd <dir>      Project root directory (REQUIRED)

    Examples:
      telec todo set-deps my-feature --after auth-setup --cwd /path/to/project
      telec todo set-deps my-feature --after dep1 --after dep2 --cwd /path/to/project
      telec todo set-deps my-feature --cwd /path/to/project   (clears deps)
    """
    if "--help" in args or "-h" in args:
        print(handle_todo_set_deps.__doc__ or "")
        return

    slug: str | None = None
    after: list[str] = []
    cwd: str | None = None

    i = 0
    while i < len(args):
        if args[i] == "--after" and i + 1 < len(args):
            after.append(args[i + 1])
            i += 2
        elif args[i] == "--cwd" and i + 1 < len(args):
            cwd = args[i + 1]
            i += 2
        elif not args[i].startswith("-"):
            slug = args[i]
            i += 1
        else:
            i += 1

    if not slug:
        print("Error: slug is required", file=sys.stderr)
        raise SystemExit(1)
    if not cwd:
        print("Error: --cwd is required", file=sys.stderr)
        raise SystemExit(1)

    body: dict[str, object] = {"slug": slug, "after": after, "cwd": cwd}  # guard: loose-dict - JSON request body
    data = tool_api_call("POST", "/todos/set-deps", json_body=body)
    print_json(data)


# =============================================================================
# Top-level commands: computers, projects, deploy
# =============================================================================


def handle_computers(args: list[str]) -> None:
    """List available computers (local + cached remote computers).

    Usage: telec computers

    Returns all known computers with their status, user, host, and whether
    they are the local computer. Remote computers are populated from the
    Redis peer cache and may be stale if connectivity is lost.

    Examples:
      telec computers
    """
    if "--help" in args or "-h" in args:
        print(handle_computers.__doc__ or "")
        return

    data = tool_api_call("GET", "/computers")
    print_json(data)


def handle_projects(args: list[str]) -> None:
    """List projects (local + cached remote projects).

    Usage: telec projects [--computer <name>]

    Returns all known projects with their name, path, description, and
    which computer they are on. Local projects are served from cache when
    available (warmed at startup). Remote projects come from the Redis cache.

    Options:
      --computer <name>  Filter to a specific computer (optional)

    Examples:
      telec projects
      telec projects --computer macbook
    """
    if "--help" in args or "-h" in args:
        print(handle_projects.__doc__ or "")
        return

    params: dict[str, str] = {}
    i = 0
    while i < len(args):
        if args[i] == "--computer" and i + 1 < len(args):
            params["computer"] = args[i + 1]
            i += 2
        else:
            i += 1

    data = tool_api_call("GET", "/projects", params=params)
    print_json(data)


def handle_deploy(args: list[str]) -> None:
    """Deploy latest code to remote computers via Redis.

    Usage: telec deploy [<computer> ...]

    Sends a deploy command to the specified computers (or all online remote
    computers if none are specified) and waits up to 60 seconds for each
    to complete. Reports status per computer.

    Deployment triggers: git pull on the remote + service restart.
    Requires admin clearance.

    Positional args:
      <computer>   Computer name(s) to deploy to (optional, repeatable)

    Examples:
      telec deploy
      telec deploy raspi
      telec deploy raspi server1
    """
    if "--help" in args or "-h" in args:
        print(handle_deploy.__doc__ or "")
        return

    computers = [a for a in args if not a.startswith("-")]
    body: dict[str, object] = {"computers": computers if computers else None}  # guard: loose-dict - JSON request body
    data = tool_api_call("POST", "/deploy", json_body=body, timeout=90.0)
    print_json(data)


# =============================================================================
# Agents group
# =============================================================================


def handle_agents(args: list[str]) -> None:
    """Manage agent dispatch status and availability.

    Usage: telec agents <subcommand> [args]

    Subcommands:
      availability  Get current availability for all agents
      status        Set dispatch status for a specific agent

    Examples:
      telec agents availability
      telec agents status claude --status unavailable --reason rate_limited
    """
    if not args or args[0] in ("-h", "--help"):
        print(handle_agents.__doc__ or "")
        return

    sub = args[0]
    rest = args[1:]

    if sub == "availability":
        handle_agents_availability(rest)
    elif sub == "status":
        handle_agents_status(rest)
    else:
        print(f"Unknown agents subcommand: {sub}", file=sys.stderr)
        print("Run 'telec agents --help' for usage.", file=sys.stderr)
        raise SystemExit(1)


def handle_agents_availability(args: list[str]) -> None:
    """Get current availability for all agents.

    Usage: telec agents availability

    Returns availability status for claude, gemini, and codex, including
    whether each is available, its current status, the reason for any
    unavailability, and when it becomes available again.

    Examples:
      telec agents availability
    """
    if "--help" in args or "-h" in args:
        print(handle_agents_availability.__doc__ or "")
        return

    data = tool_api_call("GET", "/agents/availability")
    print_json(data)


def handle_agents_status(args: list[str]) -> None:
    """Set agent dispatch status (available/unavailable/degraded).

    Usage: telec agents status <agent> --status <status>
                               [--reason <text>]
                               [--until <ISO8601>]
                               OR
           telec agents status <agent> --clear

    Marks an agent as available, unavailable (temporarily blocked from
    dispatch), or degraded (excluded from automatic fallback selection).
    Use --clear to reset to available immediately.

    Options:
      <agent>          Agent name: claude, gemini, codex
      --status <s>     Status: available, unavailable, degraded
      --reason <text>  Reason (required for unavailable)
      --until <ts>     ISO8601 UTC expiry for unavailable status
      --clear          Reset to available immediately

    Examples:
      telec agents status claude --status unavailable --reason rate_limited
      telec agents status claude --status unavailable --reason quota_exhausted --until 2024-01-01T12:00:00Z
      telec agents status claude --status degraded --reason "slow responses"
      telec agents status claude --clear
    """
    if "--help" in args or "-h" in args:
        print(handle_agents_status.__doc__ or "")
        return

    agent: str | None = None
    body: dict[str, object] = {}  # guard: loose-dict - JSON request body

    if args and not args[0].startswith("-"):
        agent = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] == "--status" and i + 1 < len(args):
            body["status"] = args[i + 1]
            i += 2
        elif args[i] == "--reason" and i + 1 < len(args):
            body["reason"] = args[i + 1]
            i += 2
        elif args[i] == "--until" and i + 1 < len(args):
            body["unavailable_until"] = args[i + 1]
            i += 2
        elif args[i] == "--clear":
            body["clear"] = True
            i += 1
        else:
            i += 1

    if not agent:
        print("Error: agent name required (claude, gemini, codex)", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call("POST", f"/agents/{agent}/status", json_body=body)
    print_json(data)


# =============================================================================
# Channels group
# =============================================================================


def handle_channels(args: list[str]) -> None:
    """Manage internal Redis Stream channels.

    Usage: telec channels <subcommand> [args]

    Subcommands:
      list     List active channels (optionally filtered by project)
      publish  Publish a message to a channel

    Examples:
      telec channels list
      telec channels list --project myproject
      telec channels publish channel:myproject:events --data '{"type":"update"}'
    """
    if not args or args[0] in ("-h", "--help"):
        print(handle_channels.__doc__ or "")
        return

    sub = args[0]
    rest = args[1:]

    if sub == "list":
        handle_channels_list(rest)
    elif sub == "publish":
        handle_channels_publish(rest)
    else:
        print(f"Unknown channels subcommand: {sub}", file=sys.stderr)
        print("Run 'telec channels --help' for usage.", file=sys.stderr)
        raise SystemExit(1)


def handle_channels_list(args: list[str]) -> None:
    """List active internal Redis Stream channels.

    Usage: telec channels list [--project <name>]

    Returns all active channels, optionally filtered by project name.
    Channel names follow the convention: channel:{project}:{topic}

    Options:
      --project <name>   Filter by project name

    Examples:
      telec channels list
      telec channels list --project myproject
    """
    if "--help" in args or "-h" in args:
        print(handle_channels_list.__doc__ or "")
        return

    params: dict[str, str] = {}
    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            params["project"] = args[i + 1]
            i += 2
        else:
            i += 1

    data = tool_api_call("GET", "/api/channels/", params=params)
    print_json(data)


def handle_channels_publish(args: list[str]) -> None:
    """Publish a message to an internal Redis Stream channel.

    Usage: telec channels publish <channel> --data <json>

    Publishes a JSON payload to the specified channel. Publishing to a
    non-existent channel creates it automatically.

    Channel naming convention: channel:{project}:{topic}

    Options:
      <channel>      Full channel key (e.g. channel:myproject:events)
      --data <json>  JSON payload to publish

    Examples:
      telec channels publish channel:myproject:events --data '{"type":"update"}'
      telec channels publish channel:ai:notifications --data '{"msg":"done"}'
    """
    if "--help" in args or "-h" in args:
        print(handle_channels_publish.__doc__ or "")
        return

    import json

    channel: str | None = None
    payload_str: str | None = None

    if args and not args[0].startswith("-"):
        channel = args[0]
        args = args[1:]

    i = 0
    while i < len(args):
        if args[i] == "--data" and i + 1 < len(args):
            payload_str = args[i + 1]
            i += 2
        elif args[i] == "--channel" and i + 1 < len(args):
            channel = args[i + 1]
            i += 2
        else:
            i += 1

    if not channel:
        print("Error: channel name required", file=sys.stderr)
        raise SystemExit(1)
    if not payload_str:
        print("Error: --data is required", file=sys.stderr)
        raise SystemExit(1)

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON for --data: {e}", file=sys.stderr)
        raise SystemExit(1)

    data = tool_api_call(
        "POST",
        f"/api/channels/{channel}/publish",
        json_body={"payload": payload},
    )
    print_json(data)

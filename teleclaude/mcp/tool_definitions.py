"""MCP tool definitions for TeleClaude.

This module contains all MCP tool definitions exposed by the TeleClaude server.
Extracted from mcp_server.py for maintainability.
"""

# mypy: disable-error-code="misc"
# JSON schemas inherently contain Any types - this is expected for MCP tool inputSchema definitions

from mcp.types import Tool

# Reusable instruction for AI-to-AI session management (appended to tool descriptions)
REMOTE_AI_TIMER_INSTRUCTION = (
    "**After dispatching:** "
    '1) Start a 5-minute background timer: `Bash(command="sleep 300", run_in_background=true)`. '
    "2) STOP responding and wait for the notification when the worker completes. "
    "3) If you send another message to this agent, cancel the old timer with `KillShell(shell_id=<task_id>)` "
    "and start a new 5-minute timer. "
    "4) If the timer completes with no notification, use `teleclaude__get_session_data` to check status."
)


def get_tool_definitions() -> list[Tool]:
    """Get the list of MCP tool definitions.

    Returns the tool definitions that are registered with the MCP server.
    """
    return [
        Tool(
            name="teleclaude__get_context",
            title="TeleClaude: Get Context",
            description=(
                "Two-phase snippet retrieval. "
                "You will use this tool to get important context before starting any work. "
                "Phase 1: pass an empty corpus to return a filtered snippet index (frontmatter only). "
                "Phase 2: pass selected snippet ids (as a JSON list or newline list) to receive full snippets. "
                "Always start with phase 1 when you are unsure which snippets apply. ALWAYS use phase 2 when you found interesting snippets! "
                "Use when you need policy/procedure/role/checklist/reference context beyond what you already have."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "corpus": {
                        "type": "string",
                        "description": "Phase 1: empty string to return index. Phase 2: JSON list or newline list of snippet ids.",
                    },
                    "areas": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "policy",
                                "standard",
                                "guide",
                                "procedure",
                                "role",
                                "checklist",
                                "reference",
                                "concept",
                                "architecture",
                                "decision",
                                "example",
                                "incident",
                                "timeline",
                                "faq",
                                "principles",
                            ],
                        },
                        "description": "Taxonomy types to include in the index (leave empty for all).",
                    },
                },
                "required": ["corpus", "areas"],
            },
        ),
        Tool(
            name="teleclaude__help",
            title="TeleClaude: Help",
            description="Return a short, human-readable description of TeleClaude capabilities and local helper scripts.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="teleclaude__list_computers",
            title="TeleClaude: List Computers",
            description=(
                "List all available TeleClaude computers in the network with detailed information: "
                "role, system stats (memory, disk, CPU), and active sessions. "
                "Optionally filter by specific computer names."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: Only return these computers (e.g., ['raspi', 'macbook'])",
                    },
                },
            },
        ),
        Tool(
            name="teleclaude__list_projects",
            title="TeleClaude: List Projects",
            description=(
                "**CRITICAL: Call this FIRST before teleclaude__start_session** "
                "List available project directories on a target computer (from trusted_dirs config). "
                "Returns structured data with name, desc, and path for each directory. "
                "Use the 'path' field in teleclaude__start_session. "
                "Always use this to discover and match the correct project before starting a session."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": "string",
                        "description": "Target computer name (e.g., 'workstation', 'server')",
                    }
                },
                "required": ["computer"],
            },
        ),
        Tool(
            name="teleclaude__list_sessions",
            title="TeleClaude: List Sessions",
            description=(
                "List active sessions from local or remote computer(s). "
                "Defaults to local sessions only. Set computer=None to query ALL computers, "
                "or computer='name' to query a specific remote computer."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": ["string", "null"],
                        "description": (
                            "Which computer(s) to query: "
                            "'local' (default) = this computer only, "
                            "None = all computers, "
                            "'name' = specific remote computer"
                        ),
                        "default": "local",
                    }
                },
            },
        ),
        Tool(
            name="teleclaude__start_session",
            title="TeleClaude: Start Session",
            description=(
                "Start a new session (Claude, Gemini, or Codex) on a remote computer in a specific project. "
                "**REQUIRED WORKFLOW:** "
                "1) Call teleclaude__list_projects FIRST to discover available projects "
                "2) Match and select the correct project from the results "
                "3) Use the exact project path from list_projects in the project_path parameter here. "
                f"Returns session_id. {REMOTE_AI_TIMER_INSTRUCTION}"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": "string",
                        "description": "Target computer name (e.g., 'workstation', 'server')",
                    },
                    "agent": {
                        "type": "string",
                        "enum": ["claude", "gemini", "codex"],
                        "default": "claude",
                        "description": "Which AI agent to start in the session. Defaults to 'claude'.",
                    },
                    "thinking_mode": {
                        "type": "string",
                        "description": (
                            "Model tier: 'fast' (cheapest), 'med' (balanced), 'slow' (most capable). Default: slow"
                        ),
                        "enum": ["fast", "med", "slow"],
                        "default": "slow",
                    },
                    "project_path": {
                        "type": "string",
                        "description": (
                            "**MUST come from teleclaude__list_projects output** "
                            "Absolute path to project directory (e.g., '/home/user/apps/TeleClaude'). "
                            "Do NOT guess or construct paths - always use teleclaude__list_projects first."
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": (
                            "Session title describing the task (e.g., 'Debug auth flow', 'Review PR #123'). "
                            "Use 'TEST: {description}' prefix for testing sessions."
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": (
                            "Optional initial task or prompt to send to the agent "
                            "(e.g., 'Read README and summarize', 'Trace message flow from Telegram to session'). "
                            "If provided, session starts immediately processing this message. "
                            "If omitted, starts an interactive session waiting for user input."
                        ),
                    },
                },
                "required": ["computer", "project_path", "title"],
            },
        ),
        Tool(
            name="teleclaude__send_message",
            title="TeleClaude: Send Message",
            description=(
                "Send message to an existing AI Agent session. "
                "Use teleclaude__list_sessions to find session IDs. "
                "For slash commands, prefer teleclaude__run_agent_command instead. "
                f"{REMOTE_AI_TIMER_INSTRUCTION}"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": "string",
                        "description": "Target computer name. Use 'local' for sessions on this computer.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Target session ID (from teleclaude__list_sessions or teleclaude__start_session)"
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": "Message or command to send to Claude Code",
                    },
                },
                "required": ["computer", "session_id", "message"],
            },
        ),
        Tool(
            name="teleclaude__run_agent_command",
            title="TeleClaude: Run Agent Command",
            description=(
                "Run a slash command on an AI agent session. "
                "Two modes: (1) If session_id provided, sends command to existing session. "
                "(2) If session_id not provided, starts a new session with the command. "
                "Supports all agent types (Claude, Gemini, Codex) and worktree subfolders. "
                "Commands are for AI slash commands (e.g., 'compact', 'next-work'), not shell commands. "
                f"{REMOTE_AI_TIMER_INSTRUCTION}"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": "string",
                        "description": "Target computer name",
                    },
                    "command": {
                        "type": "string",
                        "description": ("Command name without leading / (e.g., 'next-work', 'compact', 'help')"),
                    },
                    "args": {
                        "type": "string",
                        "description": "Optional arguments for the command",
                        "default": "",
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Optional: send command to existing session. "
                            "If omitted, starts a new session with the command."
                        ),
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Project directory path. Required when starting new session (no session_id). "
                            "Use teleclaude__list_projects to discover available projects."
                        ),
                    },
                    "subfolder": {
                        "type": "string",
                        "description": (
                            "Optional subfolder within project (e.g., 'worktrees/my-feature'). "
                            "Working directory becomes project/subfolder."
                        ),
                        "default": "",
                    },
                    "agent": {
                        "type": "string",
                        "enum": ["claude", "gemini", "codex"],
                        "default": "claude",
                        "description": "Agent type for new sessions. Default: claude",
                    },
                    "thinking_mode": {
                        "type": "string",
                        "description": (
                            "Model tier: 'fast' (cheapest), 'med' (balanced), 'slow' (most capable). Default: slow"
                        ),
                        "enum": ["fast", "med", "slow"],
                        "default": "slow",
                    },
                },
                "required": ["computer", "command"],
            },
        ),
        Tool(
            name="teleclaude__get_session_data",
            title="TeleClaude: Get Session Data",
            description=(
                "Retrieve session data from a remote computer's Claude Code session. "
                "Reads from the claude_session_file which contains complete session history. "
                "By default returns last 2000 chars. Start with the default; increase tail_chars only when needed. "
                "Use timestamp filters (inclusive) to scrub through history; ISO 8601 UTC "
                "(e.g., 2025-11-11T04:25:33.890Z). "
                "Returns `status: 'error'` if session has ended or is missing (no transcript returned). "
                "**Use this to check on delegated work**. "
                "**Reason gate:** Only call with a concrete reason: "
                "(1) the 5-minute wait timer elapsed with no notification, "
                "(2) the user explicitly asked for a check/re-check, "
                "or (3) you must verify a specific hypothesis. "
                "**Cadence gate:** Do not call successively without a new signal; "
                "minimum wait between calls is 5 minutes unless the user requests faster checks. "
                "If calling again, use `since_timestamp` and keep the window minimal. "
                "**Stop condition:** If no new activity is found, stop and wait. "
                "**Supervising Worker AI Sessions:** "
                "Responses are capped at 48,000 chars to keep MCP transport stable. "
                "Use `since_timestamp` / `until_timestamp` to page through history. "
                "If you need full coverage, repeatedly call with a time window and stitch results. "
                "The tail only shows recent activity; use timestamps for the full decision trail."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": "string",
                        "description": "Target computer name where session is running",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to retrieve data for",
                    },
                    "since_timestamp": {
                        "type": "string",
                        "description": (
                            "Optional ISO 8601 UTC timestamp. Returns only messages since this time. "
                            "Example: '2025-11-28T10:30:00Z'"
                        ),
                    },
                    "until_timestamp": {
                        "type": "string",
                        "description": (
                            "Optional ISO 8601 UTC timestamp. Returns only messages until this time. "
                            "Use with since_timestamp to get a time window."
                        ),
                    },
                    "tail_chars": {
                        "type": "integer",
                        "description": (
                            "Max characters to return from end of transcript. Default: 2000. "
                            "Keep the default unless you need more context; use timestamps for paging. "
                            "Set to 0 for unlimited request, but responses are capped at 48,000 chars. "
                            "Use since_timestamp / until_timestamp to fetch more."
                        ),
                    },
                },
                "required": ["computer", "session_id"],
            },
        ),
        Tool(
            name="teleclaude__deploy",
            title="TeleClaude: Deploy",
            description=(
                "Deploy latest code to remote computers (git pull + restart). "
                "Provide an optional list of computers; if omitted or empty, deploys to all remote "
                "computers except self. Use this after committing changes to update machines. "
                "**Workflow**: commit changes -> push to GitHub -> call this tool. "
                "Returns deployment status for each computer (success, deploying, error)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of target computers. Omit/empty for all remotes.",
                    },
                },
            },
        ),
        Tool(
            name="teleclaude__send_file",
            title="TeleClaude: Send File",
            description=(
                "Send a file to the specified TeleClaude session. "
                "Use this to send files for download (logs, reports, screenshots, etc.). "
                "Get session_id from TMPDIR/teleclaude_session_id (injected by mcp-wrapper)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "TeleClaude session UUID (from TMPDIR/teleclaude_session_id)",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to file to send",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional caption for the file",
                    },
                },
                "required": ["session_id", "file_path"],
            },
        ),
        Tool(
            name="teleclaude__send_result",
            title="TeleClaude: Send Result",
            description=(
                "Send formatted results to the user as a separate message "
                "(not in the streaming tmux output).\n\n"
                "Use this tool when the user explicitly asks to send results.\n\n"
                "Content can be markdown or html."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "TeleClaude session UUID (from TMPDIR/teleclaude_session_id)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to display",
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["markdown", "html"],
                        "default": "markdown",
                        "description": "Content format. Defaults to 'markdown'.",
                    },
                },
                "required": ["session_id", "content"],
            },
        ),
        Tool(
            name="teleclaude__stop_notifications",
            title="TeleClaude: Stop Notifications",
            description=(
                "Unsubscribe from a session's stop/notification events without ending it. "
                "Removes the caller's listener for the target session. "
                "The target session continues running, but the caller no longer receives events from it. "
                "Use this when a master AI no longer needs to monitor a specific worker session."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": "string",
                        "description": "Target computer name. Use 'local' for sessions on this computer.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to stop receiving notifications from",
                    },
                },
                "required": ["computer", "session_id"],
            },
        ),
        Tool(
            name="teleclaude__end_session",
            title="TeleClaude: End Session",
            description=(
                "Gracefully end a Claude Code session (local or remote). "
                "Kills the tmux session, deletes the session record, and cleans up all resources "
                "(listeners, workspace directories, channels). "
                "Use this when a master AI wants to terminate a worker session that has completed "
                "its work or needs to be replaced (e.g., due to context exhaustion)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "computer": {
                        "type": "string",
                        "description": "Target computer name. Use 'local' for sessions on this computer.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to end",
                    },
                },
                "required": ["computer", "session_id"],
            },
        ),
        Tool(
            name="teleclaude__handle_agent_event",
            title="TeleClaude: Handle Agent Event (internal)",
            description="Internal: receive agent hook events from Claude Code sessions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "event_type": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["session_id", "event_type", "payload"],
            },
        ),
        Tool(
            name="teleclaude__next_prepare",
            title="TeleClaude: Next Prepare",
            description=(
                "Phase A state machine: Check preparation state and return instructions. "
                "Checks for requirements.md and implementation-plan.md, returns exact command to dispatch. "
                "If roadmap is empty, dispatches roadmap grooming. "
                "Call this to prepare a work item before building. "
                'Use slug "input" to capture the latest session into a new todos/*/input.md.'
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Optional work item slug. If not provided, resolves from roadmap.",
                    },
                    "hitl": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "Human-in-the-loop mode. When true (default), returns guidance for the "
                            "calling AI to work interactively with the user. When false, dispatches "
                            "to another AI for autonomous collaboration."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="teleclaude__next_work",
            title="TeleClaude: Next Work",
            description=(
                "Phase B state machine: Check build state and return instructions. "
                "Handles bugs -> build -> review -> fix -> finalize cycle. "
                "Returns exact command to dispatch based on state.json. "
                "Call this to progress a prepared work item through the build cycle."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Optional work item slug. If not provided, resolves from roadmap.",
                    },
                },
            },
        ),
        Tool(
            name="teleclaude__next_maintain",
            title="TeleClaude: Next Maintain",
            description=("Phase D state machine: Maintenance stub. Returns a message until procedures are defined."),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="teleclaude__mark_phase",
            title="TeleClaude: Mark Phase",
            description=(
                "Mark a work phase as complete/approved in state.json. "
                "Updates trees/{slug}/todos/{slug}/state.json and commits the change. "
                "Call this after a worker completes build or review phases."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Work item slug",
                    },
                    "phase": {
                        "type": "string",
                        "enum": ["build", "review", "docstrings", "snippets"],
                        "description": "Phase to update",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "complete", "approved", "changes_requested"],
                        "description": "New status for the phase",
                    },
                },
                "required": ["slug", "phase", "status"],
            },
        ),
        Tool(
            name="teleclaude__set_dependencies",
            title="TeleClaude: Set Dependencies",
            description="Set dependencies for a work item. Replaces all dependencies. Use after=[] to clear.",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Work item slug",
                    },
                    "after": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of slugs that must complete before this item can be worked on",
                    },
                },
                "required": ["slug", "after"],
            },
        ),
        Tool(
            name="teleclaude__mark_agent_unavailable",
            title="TeleClaude: Mark Agent Unavailable",
            description=(
                "Mark an agent as temporarily unavailable for task assignment, "
                "or clear its unavailable state. Used when dispatch fails due to rate limits, "
                "quota exhaustion, or outages. The agent will be skipped in fallback selection "
                "until the specified time. If clear is true, the agent becomes available immediately "
                "and other fields are ignored."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": "Agent name (e.g., 'claude', 'gemini', 'codex')",
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "Reason for marking unavailable (e.g., 'rate_limited', 'quota_exhausted'). "
                            "Required unless clear is true."
                        ),
                    },
                    "unavailable_until": {
                        "type": "string",
                        "description": (
                            "ISO 8601 UTC datetime when agent becomes available "
                            "(e.g., '2025-01-01T12:30:00Z'). If omitted, defaults to 30 minutes from now."
                        ),
                    },
                    "clear": {
                        "type": "boolean",
                        "description": "Set true to clear unavailable state and mark the agent available.",
                    },
                },
                "required": ["agent"],
            },
        ),
    ]

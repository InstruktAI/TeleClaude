"""MCP tool definitions for TeleClaude.

This module contains all MCP tool definitions exposed by the TeleClaude server.
Extracted from mcp_server.py for maintainability.
"""

# mypy: disable-error-code="misc"
# JSON schemas inherently contain Any types - this is expected for MCP tool inputSchema definitions

from mcp.types import Tool

from teleclaude.constants import TAXONOMY_TYPES

# --- Widget expression JSON Schema building blocks ---

_SECTION_COMMON: dict[str, object] = {  # guard: loose-dict - JSON Schema properties
    "label": {"type": "string", "description": "Section heading above content."},
    "variant": {
        "type": "string",
        "enum": ["default", "info", "success", "warning", "error", "muted"],
        "description": "Visual treatment.",
    },
    "id": {"type": "string", "description": "Section reference ID."},
}

_INPUT_FIELD_SCHEMA: dict[str, object] = {  # guard: loose-dict - JSON Schema
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Field identifier."},
        "label": {"type": "string", "description": "Display label."},
        "input": {
            "type": "string",
            "enum": ["text", "select", "checkbox", "number", "date"],
            "description": "Input type.",
        },
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Options for select inputs.",
        },
        "required": {"type": "boolean"},
        "placeholder": {"type": "string"},
        "default": {"type": "string"},
        "helpText": {"type": "string"},
        "disabled": {"type": "boolean"},
        "readonly": {"type": "boolean"},
        "width": {"type": "string", "enum": ["half", "full"]},
    },
    "required": ["name", "label", "input"],
}

_BUTTON_SCHEMA: dict[str, object] = {  # guard: loose-dict - JSON Schema
    "type": "object",
    "properties": {
        "label": {"type": "string", "description": "Button text."},
        "action": {"type": "string", "description": "Action identifier sent on click."},
        "style": {"type": "string", "enum": ["primary", "secondary", "destructive"]},
        "icon": {"type": "string"},
        "disabled": {"type": "boolean"},
        "confirm": {"type": "string", "description": "Confirmation prompt before action."},
    },
    "required": ["label", "action"],
}


def _section_variant(
    const_type: str,
    extra_props: dict[str, object],  # guard: loose-dict - JSON Schema properties
    extra_required: list[str] | None = None,
) -> dict[str, object]:  # guard: loose-dict - JSON Schema object
    """Build a oneOf variant for a section type with common fields."""
    props: dict[str, object] = {  # guard: loose-dict - JSON Schema properties
        "type": {"type": "string", "const": const_type},
        **_SECTION_COMMON,
        **extra_props,
    }
    required = ["type"] + (extra_required or [])
    return {"type": "object", "properties": props, "required": required}


_SECTION_ITEMS_SCHEMA: dict[str, object] = {  # guard: loose-dict - JSON Schema oneOf discriminator
    "oneOf": [
        _section_variant(
            "text",
            {
                "content": {"type": "string", "description": "Markdown text content."},
            },
            ["content"],
        ),
        _section_variant(
            "input",
            {
                "fields": {"type": "array", "items": _INPUT_FIELD_SCHEMA, "description": "Form fields."},
            },
            ["fields"],
        ),
        _section_variant(
            "actions",
            {
                "buttons": {"type": "array", "items": _BUTTON_SCHEMA, "description": "Action buttons."},
                "layout": {
                    "type": "string",
                    "enum": ["horizontal", "vertical"],
                    "description": "Button layout direction.",
                },
            },
            ["buttons"],
        ),
        _section_variant(
            "image",
            {
                "src": {"type": "string", "description": "Image source path."},
                "alt": {"type": "string", "description": "Alt text."},
                "width": {"type": "number"},
                "height": {"type": "number"},
                "caption": {"type": "string"},
            },
            ["src"],
        ),
        _section_variant(
            "table",
            {
                "headers": {"type": "array", "items": {"type": "string"}, "description": "Column headers."},
                "rows": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": ["string", "number"]}},
                    "description": "Table data rows.",
                },
                "caption": {"type": "string"},
                "sortable": {"type": "boolean"},
                "filterable": {"type": "boolean"},
                "maxRows": {"type": "number"},
            },
            ["headers", "rows"],
        ),
        _section_variant(
            "file",
            {
                "path": {"type": "string", "description": "File path within session workspace."},
                "size": {"type": "number"},
                "mime": {"type": "string"},
                "preview": {"type": "boolean"},
            },
            ["path"],
        ),
        _section_variant(
            "code",
            {
                "content": {"type": "string", "description": "Code content."},
                "language": {"type": "string", "description": "Programming language."},
                "title": {"type": "string"},
                "collapsible": {"type": "boolean"},
                "lineNumbers": {"type": "boolean"},
            },
            ["content"],
        ),
        _section_variant("divider", {}),
    ],
}

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
                "You will use this tool to get important context before starting work TO AVOID MISTAKES BASED IN ASSUMPTIONS! "
                "Phase 1: Call with no parameters (or with areas filter) to return snippet index with IDs and descriptions. "
                "Phase 2: Call with snippet_ids parameter to retrieve full snippet content. "
                "Always start with phase 1 when you are unsure which snippets apply. ALWAYS use phase 2 when you found interesting snippets! "
                "Use teleclaude__get_context by default when information is incomplete. "
                "If you do not have full, current, and confident visibility into repo rules, workflows, or relevant local knowledge, "
                "you must call teleclaude__get_context before acting. Treat any uncertainty as a hard trigger. "
                "This applies to skaffolding, planning, troubleshooting, editing, or answering when local constraints might matter. "
                "Only skip the tool if the user explicitly says not to or the request is purely mechanical with zero dependency on local guidance. "
                "If unsure, assume the tool is required. "
                "Use when you need context beyond what you already have, like policy/procedure/spec/etc. "
                "Example triggers: "
                "- Take the role of / act as orchestrator/architect/builder/reviewer/maintainer. "
                "- Write/update doc snippets. "
                "- Put on your architect/reviewer/researcher hat. "
                "- Let's do some troubleshooting. "
                "- Use our third-party docs."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "areas": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": TAXONOMY_TYPES,
                        },
                        "description": (
                            "Phase 1 only: Filter by taxonomy type. "
                            "Allowed types: policy, procedure, principle, concept, design, spec. "
                            'Example: {"areas":["policy","procedure","spec"]}. '
                            "Ignored in Phase 2."
                        ),
                    },
                    "snippet_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Phase 2 only: Array of snippet IDs to retrieve full content for.",
                    },
                    "baseline_only": {
                        "type": "boolean",
                        "description": (
                            "Filter to ONLY baseline snippets (those auto-loaded at session start). "
                            "Useful for authoring/editing baseline content. When false (default), "
                            "all snippets including baseline are shown in the index."
                        ),
                    },
                    "include_third_party": {
                        "type": "boolean",
                        "description": (
                            "Include third-party documentation in the index and allow selection. "
                            "Third-party docs are separate from the taxonomy (no type field) and "
                            "are not filtered by areas. Use when you need library/framework docs "
                            "and want to see what exists locally (preferable) before searching the web."
                        ),
                    },
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Filter by domain (e.g., 'software-development', 'general'). "
                            "Overrides project teleclaude.yml config. If not specified, uses project "
                            "config or defaults to 'software-development'. 'general' snippets are "
                            "always included regardless of this filter."
                        ),
                    },
                    "project_root": {
                        "type": "string",
                        "description": (
                            "Absolute path to project root. Use to query docs from a different project "
                            "than the current working directory. Defaults to cwd if not specified."
                        ),
                    },
                },
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
                            "'local' (default) or a specific computer name. "
                            "Omit this field to query all computers."
                        ),
                        "default": "local",
                    },
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
                    "direct": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "When true, skip automatic notification subscription. "
                            "Use for peer-to-peer agent communication where neither agent supervises the other."
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
                "For agent commands, prefer teleclaude__run_agent_command instead. "
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
                        "description": "Message to send to the agent session",
                    },
                    "direct": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "When true, skip automatic notification subscription. "
                            "Use for peer-to-peer agent communication where neither agent supervises the other."
                        ),
                    },
                },
                "required": ["computer", "session_id", "message"],
            },
        ),
        Tool(
            name="teleclaude__run_agent_command",
            title="TeleClaude: Run Agent Command",
            description=(
                "Start a new AI agent session and give it a slash command to execute. "
                "Supports all agent types (Claude, Gemini, Codex) and worktree subfolders. "
                "Commands are agent commands, not shell commands. "
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
                        "description": "Agent command with leading '/' (e.g., '/next-work')",
                    },
                    "args": {
                        "type": "string",
                        "description": "Optional arguments for the command",
                        "default": "",
                    },
                    "project": {
                        "type": "string",
                        "description": (
                            "Project directory path for the new agent session. "
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
                "Retrieve session data from a local or remote agent session. "
                "Reads from the claude_session_file which contains complete session history. "
                "By default returns last 2000 chars. Start with the default; increase tail_chars only when needed. "
                "Use timestamp filters (inclusive) to scrub through history; ISO 8601 UTC "
                "(e.g., 2025-11-11T04:25:33.890Z). "
                "Returns `status: 'error'` if session has ended or is missing. "
                "When native transcript files are not yet available, this returns a tmux-pane tail snapshot "
                "instead of waiting for a completed turn. "
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
                            "Use a small value first, then increase if needed. "
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
                "Returns deployment status for each computer (success, deploying, error). "
                "If deploy fails due to remote local changes, assume stale rsync artifacts and perform a clean checkout on the remote before retrying."
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
                "(not in the streaming terminal output).\n\n"
                "Content can be markdown or html.\n\n"
                "ONLY use this tool when the user explicitly asks to send results!"
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
                "Returns exact command to dispatch based on state.yaml. "
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
                "Mark a work phase as complete/approved in state.yaml. "
                "Updates trees/{slug}/todos/{slug}/state.yaml and syncs it back to main todos/{slug}/state.yaml. "
                "Call this after a worker completes build or review phases. "
                "Use after a phase completes to keep state in sync."
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
                        "enum": ["build", "review"],
                        "description": "Phase to update",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "started", "complete", "approved", "changes_requested"],
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
            name="teleclaude__mark_agent_status",
            title="TeleClaude: Mark Agent Status",
            description=(
                "Set agent dispatch status. "
                "`status='unavailable'` temporarily removes the agent from fallback selection until expiry. "
                "`status='degraded'` keeps it installed but excludes it from automatic selection. "
                "`status='available'` clears restrictions. "
                "If clear=true, status is reset to available immediately."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "agent": {
                        "type": "string",
                        "description": "Agent name (e.g., 'claude', 'gemini', 'codex')",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["available", "unavailable", "degraded"],
                        "description": (
                            "Dispatch status to apply. 'degraded' excludes the agent from automatic fallback selection."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": (
                            "Reason for marking unavailable (e.g., 'rate_limited', 'quota_exhausted'). "
                            "Required for unavailable status; optional for degraded."
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
        Tool(
            name="teleclaude__publish",
            title="Publish to Channel",
            description=(
                "Publish a message to an internal Redis Stream channel. "
                "Channels use the naming convention channel:{project}:{topic}. "
                "Publishing to a non-existent channel creates it automatically."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "Full channel key, e.g. 'channel:myproject:events'.",
                    },
                    "payload": {
                        "type": "object",
                        "description": "JSON-serialisable payload to publish.",
                    },
                },
                "required": ["channel", "payload"],
            },
        ),
        Tool(
            name="teleclaude__channels_list",
            title="List Channels",
            description="List active internal Redis Stream channels, optionally filtered by project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project": {
                        "type": "string",
                        "description": "Optional project name to filter channels.",
                    },
                },
            },
        ),
        Tool(
            name="teleclaude__render_widget",
            title="TeleClaude: Render Widget",
            description=(
                "Render a rich widget expression in the user's interface. "
                "The expression format is a universal JSON structure that adapters translate into native UI. "
                "Web renders rich interactive components; Telegram receives a text summary + file attachments; "
                "terminal gets a text summary.\n\n"
                "**Expression format:**\n"
                "`data` is an object with:\n"
                "- `name` (string, optional): library slug for storage/discovery (e.g., 'person-details-form'). "
                "Triggers automatic library storage.\n"
                "- `title` (string, optional): display heading.\n"
                "- `description` (string, optional): agent-facing description (not rendered).\n"
                "- `hints` (object, optional): freeform rendering hints (animation, theme, compact, etc.).\n"
                "- `sections` (array, required): ordered content sections.\n"
                "- `footer` (string, optional): closing text.\n"
                "- `status` (string, optional): visual treatment: info, success, warning, error.\n\n"
                "**Section types:**\n"
                "- `text`: `{ type: 'text', content: string }` — markdown text block.\n"
                "- `input`: `{ type: 'input', fields: [{ name, label, input: 'text'|'select'|'checkbox'|'number'|'date', "
                "options?: string[], required?: boolean }] }` — dynamic form.\n"
                "- `actions`: `{ type: 'actions', layout?: 'horizontal'|'vertical', "
                "buttons: [{ label, style?: 'primary'|'secondary'|'destructive', action: string }] }` — action buttons.\n"
                "- `image`: `{ type: 'image', src: string, alt?: string }` — inline image.\n"
                "- `table`: `{ type: 'table', headers: string[], rows: (string|number)[][] }` — data table.\n"
                "- `file`: `{ type: 'file', path: string, label?: string }` — file download.\n"
                "- `code`: `{ type: 'code', language?: string, content: string }` — syntax-highlighted code.\n"
                "- `divider`: `{ type: 'divider' }` — horizontal separator.\n\n"
                "All section types support optional `label` (heading), `variant` (info/success/warning/error/muted), "
                "and `id` (reference) fields.\n"
                "Unknown section types are rendered as collapsed JSON in web, skipped in text summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "TeleClaude session UUID",
                    },
                    "data": {
                        "type": "object",
                        "description": "The widget expression object.",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": (
                                    "Library slug for storage/discovery (e.g., 'person-details-form'). "
                                    "Triggers automatic library storage."
                                ),
                            },
                            "title": {
                                "type": "string",
                                "description": "Display heading for the widget card.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Agent-facing description (not rendered). Stored with library entries.",
                            },
                            "hints": {
                                "type": "object",
                                "description": "Freeform rendering hints. Renderers pick what they support: animation, theme, compact, collapsible, etc.",
                            },
                            "sections": {
                                "type": "array",
                                "description": "Ordered content sections. Each section is discriminated by its 'type' field.",
                                "items": _SECTION_ITEMS_SCHEMA,
                            },
                            "footer": {
                                "type": "string",
                                "description": "Closing text below all sections.",
                            },
                            "status": {
                                "type": "string",
                                "enum": ["info", "success", "warning", "error"],
                                "description": "Visual treatment for the whole card.",
                            },
                        },
                        "required": ["sections"],
                    },
                },
                "required": ["session_id", "data"],
            },
        ),
        Tool(
            name="teleclaude__escalate",
            title="Escalate to Admin",
            description=(
                "Escalate a customer conversation to a human admin. "
                "Creates a Discord thread in the escalation forum, notifies admins, "
                "and activates relay mode so admin messages are forwarded to the customer. "
                "Only available in customer sessions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_name": {
                        "type": "string",
                        "description": "Display name of the customer requesting escalation.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the escalation.",
                    },
                    "context_summary": {
                        "type": "string",
                        "description": "Optional summary of the conversation context for the admin.",
                    },
                },
                "required": ["customer_name", "reason"],
            },
        ),
    ]

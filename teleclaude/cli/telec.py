"""telec: TUI client for TeleClaude."""

import asyncio
import os
import subprocess
import sys
import time as _t
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_BOOT = _t.monotonic()

from instrukt_ai_logging import get_logger  # noqa: E402

from teleclaude import __version__  # noqa: E402
from teleclaude.cli.api_client import APIError, TelecAPIClient  # noqa: E402
from teleclaude.cli.models import CreateSessionResult  # noqa: E402
from teleclaude.cli.session_auth import (  # noqa: E402
    clear_current_session_email,
    get_current_session_context,
    read_current_session_email,
    write_current_session_email,
)
from teleclaude.cli.tool_commands import (  # noqa: E402
    handle_agents,
    handle_channels,
    handle_computers,
    handle_projects,
    handle_sessions,
    handle_todo_mark_phase,
    handle_todo_prepare,
    handle_todo_set_deps,
    handle_todo_work,
)
from teleclaude.constants import ENV_ENABLE, MAIN_MODULE  # noqa: E402
from teleclaude.logging_config import setup_logging  # noqa: E402
from teleclaude.project_setup import init_project  # noqa: E402
from teleclaude.todo_scaffold import create_bug_skeleton, create_todo_skeleton  # noqa: E402

TMUX_ENV_KEY = "TMUX"
TUI_ENV_KEY = "TELEC_TUI_SESSION"
TUI_AUTH_EMAIL_ENV_KEY = "TELEC_AUTH_EMAIL"
TUI_SESSION_NAME = "tc_tui"


class _ConfigProxy:
    """Lazily resolve runtime config on first attribute access.

    This keeps low-dependency commands (for example `telec todo demo validate`)
    usable even when runtime config loading would fail.
    """

    def __getattr__(self, name: str) -> Any:
        from teleclaude.config import config as runtime_config

        return getattr(runtime_config, name)


config = _ConfigProxy()


class TelecCommand(str, Enum):
    """Supported telec CLI commands."""

    SESSIONS = "sessions"
    COMPUTERS = "computers"
    PROJECTS = "projects"
    AGENTS = "agents"
    CHANNELS = "channels"
    INIT = "init"
    VERSION = "version"
    SYNC = "sync"
    WATCH = "watch"
    DOCS = "docs"
    TODO = "todo"
    ROADMAP = "roadmap"
    BUGS = "bugs"
    EVENTS = "events"
    AUTH = "auth"
    CONFIG = "config"


# =============================================================================
# CLI Surface Schema — single source of truth for help, completion, and docs
# =============================================================================


@dataclass
class Flag:
    long: str
    short: str | None = None
    desc: str = ""
    hidden: bool = False  # hidden from main help overview, visible in subcommand help

    def as_tuple(self) -> tuple[str | None, str, str]:
        """Backward-compat tuple for completion helpers."""
        return (self.short, self.long, self.desc)


@dataclass
class CommandDef:
    desc: str
    args: str = ""  # e.g., "<slug>", "[mode] [prompt]"
    flags: list[Flag] = field(default_factory=list)
    subcommands: dict[str, "CommandDef"] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # extra lines for subcommand help
    examples: list[str] = field(default_factory=list)  # explicit examples when auto-generation is misleading
    hidden: bool = False  # hide from help output and completion
    standalone: bool = False  # bare invocation has behavior (not just help text)

    @property
    def visible_flags(self) -> list[Flag]:
        """Flags shown in main help overview."""
        return [f for f in self.flags if not f.hidden]

    @property
    def flag_tuples(self) -> list[tuple[str | None, str, str]]:
        """All flags as tuples for completion."""
        return [f.as_tuple() for f in self.flags]

    @property
    def subcmd_tuples(self) -> list[tuple[str, str]]:
        """Subcommands as (name, desc) tuples for completion."""
        return [(name, sub.desc) for name, sub in self.subcommands.items()]


_H = Flag("--help", "-h", "Show usage information", hidden=True)

CLI_SURFACE: dict[str, CommandDef] = {
    "sessions": CommandDef(
        desc="Manage agent sessions",
        subcommands={
            "list": CommandDef(
                desc="List sessions (default: spawned by current, --all for all)",
                flags=[
                    _H,
                    Flag("--all", desc="Show all sessions"),
                    Flag("--closed", desc="Include closed sessions"),
                ],
            ),
            "start": CommandDef(
                desc="Start a new agent session",
                args="--project <path>",
                flags=[
                    _H,
                    Flag("--computer", desc="Target computer (optional; defaults to local)"),
                    Flag("--project", desc="Project directory path"),
                    Flag("--agent", desc="Agent: claude, gemini, codex"),
                    Flag("--mode", desc="Thinking mode: fast, med, slow"),
                    Flag("--message", desc="Initial message to send"),
                    Flag("--title", desc="Session title"),
                    Flag("--direct", desc="Conversation mode: create direct link with caller and bypass listeners"),
                ],
                notes=[
                    "--project is required.",
                    "Use --direct for peer conversation mode when you want shared linked output instead of worker supervision notifications.",
                ],
                examples=[
                    "telec sessions start --project /tmp/project",
                    "telec sessions start --project /tmp/project --agent claude --mode slow",
                    'telec sessions start --project /tmp/project --message "Implement feature X"',
                    "telec sessions start --project /tmp/project --direct",
                ],
            ),
            "send": CommandDef(
                desc="Send a message to a running session",
                args="<session_id> [<message>]",
                flags=[
                    _H,
                    Flag("--session", "-s", "Session ID (compatibility form)"),
                    Flag("--message", "-m", "Message text (compatibility form)"),
                    Flag("--direct", desc="Conversation mode: create/reuse shared direct link"),
                    Flag("--close-link", desc="Close direct link with target session (alias: --close_link)"),
                ],
                notes=[
                    "Positional form is canonical: telec sessions send <session_id> <message>.",
                    "One-time ignition: sending once with --direct establishes/reuses the link.",
                    "After link creation, turn-complete outputs from linked peers are cross-shared automatically.",
                    "Only one party needs to send with --direct to establish the link.",
                    "Use --close-link to sever the direct link for all members.",
                    "Compatibility flags (--session/--message) are accepted for scripts and older clients.",
                ],
                examples=[
                    'telec sessions send sess-123 "Please implement feature X"',
                    'telec sessions send sess-123 "Let\'s discuss the architecture" --direct',
                    "telec sessions send sess-123 --close-link",
                ],
            ),
            "tail": CommandDef(
                desc="Get recent messages from a session's transcript",
                args="<session_id>",
                flags=[
                    _H,
                    Flag("--session", "-s", "Session ID"),
                    Flag("--since", desc="ISO8601 timestamp filter"),
                    Flag("--tools", desc="Include tool use entries"),
                    Flag("--thinking", desc="Include thinking blocks"),
                ],
            ),
            "run": CommandDef(
                desc="Run a slash command on a new agent session",
                flags=[
                    _H,
                    Flag("--command", desc="Slash command (e.g. /next-build)"),
                    Flag("--project", desc="Project directory path"),
                    Flag("--args", desc="Command arguments"),
                    Flag("--agent", desc="Agent: claude, gemini, codex"),
                    Flag("--mode", desc="Thinking mode: fast, med, slow"),
                    Flag("--computer", desc="Target computer (optional; defaults to local)"),
                    Flag("--subfolder", desc="Subdirectory within the project"),
                ],
                notes=[
                    "Creates a fresh session and runs the slash command as the first agent message.",
                    "Worker lifecycle commands: /next-build, /next-review, /next-fix-review, /next-finalize.",
                    "Example: telec sessions run --command /next-build --args my-slug --project /repo/path",
                ],
            ),
            "revive": CommandDef(
                desc="Revive session by TeleClaude session ID",
                args="<session_id>",
                flags=[_H, Flag("--attach", desc="Attach to tmux session after revive")],
            ),
            "end": CommandDef(
                desc="End (terminate) a session",
                args="<session_id>",
                flags=[
                    _H,
                    Flag("--session", "-s", "Session ID"),
                    Flag("--computer", desc="Target computer (optional; defaults to local)"),
                ],
            ),
            "unsubscribe": CommandDef(
                desc="Stop receiving notifications from a session",
                args="<session_id>",
                flags=[_H],
            ),
            "result": CommandDef(
                desc="Send a formatted result to the session's user",
                args="<session_id> <content>",
                flags=[_H, Flag("--format", desc="Output format: markdown, html")],
            ),
            "file": CommandDef(
                desc="Send a file to a session",
                args="<session_id>",
                flags=[
                    _H,
                    Flag("--path", desc="File path on the daemon host"),
                    Flag("--filename", desc="Display filename"),
                    Flag("--caption", desc="Optional caption"),
                ],
            ),
            "widget": CommandDef(
                desc="Render a rich widget to the session's user",
                args="<session_id>",
                flags=[_H, Flag("--data", desc="Widget expression as JSON")],
            ),
            "escalate": CommandDef(
                desc="Escalate a customer session to an admin via Discord",
                args="<session_id>",
                flags=[
                    _H,
                    Flag("--customer", desc="Customer name"),
                    Flag("--reason", desc="Reason for escalation"),
                    Flag("--summary", desc="Context summary for the admin"),
                ],
            ),
        },
    ),
    "computers": CommandDef(
        desc="Manage computer inventory",
        subcommands={
            "list": CommandDef(
                desc="List available computers (local + cached remote)",
                flags=[_H],
            ),
        },
    ),
    "projects": CommandDef(
        desc="Manage project inventory",
        subcommands={
            "list": CommandDef(
                desc="List projects on local and remote computers",
                flags=[_H, Flag("--computer", desc="Filter to a specific computer")],
            ),
        },
    ),
    "agents": CommandDef(
        desc="Manage agent dispatch status and availability",
        subcommands={
            "availability": CommandDef(desc="Get current availability for all agents"),
            "status": CommandDef(
                desc="Set dispatch status for a specific agent",
                args="<agent>",
                flags=[
                    _H,
                    Flag("--status", desc="Status: available, unavailable, degraded"),
                    Flag("--reason", desc="Reason for status change"),
                    Flag("--until", desc="ISO8601 UTC expiry for unavailable"),
                    Flag("--clear", desc="Reset to available immediately"),
                ],
            ),
        },
    ),
    "channels": CommandDef(
        desc="Manage internal Redis Stream channels",
        subcommands={
            "list": CommandDef(
                desc="List active channels",
                flags=[_H, Flag("--project", desc="Filter by project name")],
            ),
            "publish": CommandDef(
                desc="Publish a message to a channel",
                args="<channel>",
                flags=[_H, Flag("--data", desc="JSON payload to publish")],
            ),
        },
    ),
    "init": CommandDef(desc="Initialize docs sync and auto-rebuild watcher"),
    "version": CommandDef(desc="Print version, channel, and commit"),
    "sync": CommandDef(
        desc="Validate, build indexes, and deploy artifacts",
        flags=[
            _H,
            Flag("--warn-only", desc="Warn but don't fail"),
            Flag("--validate-only", desc="Validate without building"),
        ],
    ),
    "watch": CommandDef(
        desc="Watch project for changes and auto-sync",
        flags=[_H],
        hidden=True,
    ),
    "docs": CommandDef(
        desc="Query documentation snippets",
        subcommands={
            "index": CommandDef(
                desc="List snippet IDs and metadata (phase 1)",
                flags=[
                    _H,
                    Flag("--baseline-only", "-b", "Show only baseline snippets"),
                    Flag("--third-party", "-t", "Include third-party docs"),
                    Flag("--areas", "-a", "Filter by taxonomy type"),
                    Flag("--domains", "-d", "Filter by domain"),
                ],
            ),
            "get": CommandDef(
                desc="Fetch full snippet content by ID (phase 2)",
                args="<id> [id...]",
                flags=[_H],
            ),
        },
        notes=[
            "Two-phase flow: use 'telec docs index' to discover IDs, then 'telec docs get <id...>' to fetch content.",
            "Example phase 1: telec docs index --areas policy,procedure --domains software-development",
            "Example phase 2: telec docs get software-development/policy/testing project/spec/command-surface",
        ],
    ),
    "todo": CommandDef(
        desc="Manage work items",
        subcommands={
            "create": CommandDef(
                desc="Scaffold todo files for a slug",
                args="<slug>",
                flags=[
                    Flag("--after", desc="Comma-separated dependency slugs"),
                ],
                notes=["Also registers the entry in roadmap.yaml when --after is provided."],
            ),
            "remove": CommandDef(
                desc="Remove a todo and its roadmap entry",
                args="<slug>",
                flags=[],
            ),
            "validate": CommandDef(
                desc="Validate todo files and state.yaml schema",
                args="[slug]",
                flags=[],
                notes=["If slug is omitted, all active todos are checked."],
            ),
            "demo": CommandDef(
                desc="Manage and run demo artifacts",
                args="<list|validate|run|create> [slug]",
                flags=[],
                notes=[
                    "Use 'list' explicitly to list available demos.",
                    "validate <slug>: check todos/{slug}/demo.md has executable bash blocks.",
                    "run <slug>: execute bash blocks from demos/{slug}/demo.md.",
                    "create <slug>: promote todos/{slug}/demo.md to demos/{slug}/demo.md.",
                    "list: show all available demos.",
                ],
            ),
            "prepare": CommandDef(
                desc="Run the Phase A (prepare) state machine",
                args="[<slug>]",
                flags=[
                    _H,
                    Flag("--no-hitl", desc="Disable human-in-the-loop gate"),
                ],
            ),
            "work": CommandDef(
                desc="Run the Phase B (work) state machine",
                args="[<slug>]",
                flags=[_H],
            ),
            "mark-phase": CommandDef(
                desc="Mark a work phase as complete/approved in state.yaml",
                args="<slug>",
                flags=[
                    _H,
                    Flag("--phase", desc="Phase: build or review"),
                    Flag("--status", desc="Status: pending, started, complete, approved, changes_requested"),
                ],
            ),
            "set-deps": CommandDef(
                desc="Set dependencies for a work item in the roadmap",
                args="<slug>",
                flags=[
                    _H,
                    Flag("--after", desc="Dependency slug (repeatable)"),
                ],
            ),
            "verify-artifacts": CommandDef(
                desc="Mechanically verify artifacts for a phase (build or review)",
                args="<slug>",
                flags=[
                    _H,
                    Flag("--phase", desc="Phase: build or review"),
                ],
                notes=[
                    "Exits 0 on pass, 1 on failure.",
                    "Checks artifact presence and consistency — does not run tests or demo.",
                    "Integrated into next_work() before dispatching review.",
                ],
            ),
        },
    ),
    "roadmap": CommandDef(
        desc="Manage the work item roadmap",
        subcommands={
            "list": CommandDef(
                desc="List roadmap entries (source of truth for todo status)",
                flags=[
                    Flag("--include-icebox", "-i", "Include icebox items"),
                    Flag("--icebox-only", "-o", "Show only icebox items"),
                    Flag("--include-delivered", "-d", "Include delivered items"),
                    Flag("--delivered-only", desc="Show only delivered items"),
                    Flag("--json", desc="Output as JSON"),
                ],
            ),
            "add": CommandDef(
                desc="Add entry to the roadmap",
                args="<slug>",
                flags=[
                    Flag("--group", desc="Visual grouping label"),
                    Flag("--after", desc="Comma-separated dependency slugs"),
                    Flag("--before", desc="Insert before this slug (default: append)"),
                    Flag("--description", desc="Summary description"),
                ],
            ),
            "remove": CommandDef(
                desc="Remove entry from the roadmap",
                args="<slug>",
                flags=[],
            ),
            "move": CommandDef(
                desc="Reorder an entry in the roadmap",
                args="<slug>",
                flags=[
                    Flag("--before", desc="Move before this slug"),
                    Flag("--after", desc="Move after this slug"),
                ],
            ),
            "deps": CommandDef(
                desc="Set dependencies for an entry",
                args="<slug>",
                flags=[
                    Flag("--after", desc="Comma-separated dependency slugs"),
                ],
            ),
            "freeze": CommandDef(
                desc="Move entry to icebox",
                args="<slug>",
                flags=[],
            ),
            "deliver": CommandDef(
                desc="Move entry to delivered",
                args="<slug>",
                flags=[
                    Flag("--commit", desc="Commit hash"),
                    Flag("--title", desc="Delivery title (default: entry description)"),
                ],
            ),
        },
    ),
    "bugs": CommandDef(
        desc="Bug reporting and tracking",
        subcommands={
            "report": CommandDef(
                desc="Report a bug, scaffold, and dispatch fix",
                args="<description>",
                flags=[
                    Flag("--slug", desc="Custom slug (default: auto-generated)"),
                ],
            ),
            "create": CommandDef(
                desc="Scaffold bug files for a slug",
                args="<slug>",
                flags=[],
            ),
            "list": CommandDef(
                desc="List in-flight bug fixes with status",
                flags=[],
            ),
        },
    ),
    "events": CommandDef(
        desc="Event catalog and platform commands",
        subcommands={
            "list": CommandDef(
                desc="List event schemas: type, level, domain, visibility, description, actionable",
                flags=[
                    Flag("--domain", desc="Filter by domain"),
                ],
            ),
        },
    ),
    "auth": CommandDef(
        desc="Terminal login identity commands",
        subcommands={
            "login": CommandDef(
                desc="Set terminal login identity for this TTY",
                args="<email>",
                notes=[
                    "Stores auth state in a TTY-scoped file.",
                    "Running login again on the same TTY overwrites the existing file.",
                ],
            ),
            "whoami": CommandDef(
                desc="Show terminal login identity for this TTY",
            ),
            "logout": CommandDef(
                desc="Clear terminal login identity for this TTY",
            ),
        },
    ),
    "config": CommandDef(
        desc="Manage configuration",
        subcommands={
            "wizard": CommandDef(desc="Open the interactive configuration wizard"),
            "get": CommandDef(desc="Get config values", args="[paths...]"),
            "patch": CommandDef(desc="Patch config values", args="[--yaml '...']"),
            "validate": CommandDef(desc="Full validation"),
            "people": CommandDef(
                desc="Manage people (list/add/edit/remove)",
                notes=[
                    "To edit people's subscriptions, modify the person config: ~/.teleclaude/people/{name}/teleclaude.yml"
                ],
            ),
            "env": CommandDef(desc="Manage environment variables (list/set)"),
            "notify": CommandDef(desc="Toggle notification settings"),
            "invite": CommandDef(desc="Generate invite links for a person"),
        },
    ),
}

# Help-only expansion for second-level action groups.
# This keeps runtime dispatch unchanged while making `telec -h` explicit.
HELP_SUBCOMMAND_EXPANSIONS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "config": {
        "people": [
            ("list", "List people"),
            ("add", "Add a person"),
            ("edit", "Edit a person"),
            ("remove", "Remove a person"),
        ],
        "env": [
            ("list", "List environment variables"),
            ("set", "Set environment variables"),
        ],
    }
}

# Derived constants for completion (from schema)
_COMMANDS = [name for name, cmd in CLI_SURFACE.items() if not cmd.hidden]
_COMMAND_DESCRIPTIONS = {name: cmd.desc for name, cmd in CLI_SURFACE.items() if not cmd.hidden}

# =============================================================================
# Help Generation — built from CLI_SURFACE schema
# =============================================================================


def _usage(command: str | None = None, subcommand: str | None = None) -> str:
    """Generate help text from CLI_SURFACE schema.

    Args:
        command: Top-level command name. None for main overview.
        subcommand: If provided with command, show help for that specific subcommand.
    """
    if command is None:
        return _usage_main()
    if subcommand is not None:
        return _usage_leaf(command, subcommand)
    return _usage_subcmd(command)


def _maybe_show_help(cmd: str, args: list[str]) -> bool:
    """If -h/--help appears anywhere in args, show contextual help and return True."""
    if "-h" not in args and "--help" not in args:
        return False
    positionals = []
    for a in args:
        if a in ("-h", "--help"):
            break
        if not a.startswith("-"):
            positionals.append(a)
    print(_usage(cmd, positionals[0] if positionals else None))
    return True


def _usage_main() -> str:
    """Generate main help overview. Hidden flags are excluded."""
    col = 42
    lines = ["Usage:"]
    lines.append(f"  {'telec':<{col}}# Open TUI (Sessions view)")
    for name, cmd in CLI_SURFACE.items():
        if cmd.hidden:
            continue
        visible_flags = cmd.visible_flags
        flag_str = ""
        if visible_flags:
            parts = [f.short if f.short else f.long for f in visible_flags]
            flag_str = " [" + "|".join(parts) + "]"

        args_str = f" {cmd.args}" if cmd.args else ""

        if cmd.subcommands:
            if cmd.standalone:
                entry = f"telec {name}"
                lines.append(f"  {entry:<{col}}# {cmd.desc}")
            for sub_name, sub_cmd in cmd.subcommands.items():
                expanded = HELP_SUBCOMMAND_EXPANSIONS.get(name, {}).get(sub_name)
                if expanded:
                    for child_name, child_desc in expanded:
                        entry = f"telec {name} {sub_name} {child_name}"
                        lines.append(f"  {entry:<{col}}# {child_desc}")
                    continue
                sub_args = f" {sub_cmd.args}" if sub_cmd.args else ""
                sub_flag_str = " [options]" if sub_cmd.visible_flags else ""
                entry = f"telec {name} {sub_name}{sub_args}{sub_flag_str}"
                lines.append(f"  {entry:<{col}}# {sub_cmd.desc}")
        else:
            entry = f"telec {name}{args_str}{flag_str}"
            lines.append(f"  {entry:<{col}}# {cmd.desc}")
    return "\n".join(lines) + "\n"


def _sample_positional_value(token: str) -> str:
    """Return a practical sample value for a positional argument token."""
    key = token.strip("<>[]").rstrip(".,").lower()
    if "email" in key:
        return "person@example.com"
    if "session" in key:
        return "sess-123"
    if "slug" in key:
        return "my-slug"
    if "project" in key or "cwd" in key or "root" in key:
        return "/tmp/project"
    if "path" in key or "file" in key:
        return "/tmp/example.txt"
    if "agent" in key:
        return "claude"
    if "phase" in key:
        return "build"
    if "status" in key:
        return "complete"
    if "channel" in key:
        return "channel:demo:events"
    if "json" in key or "data" in key:
        return '\'{"key":"value"}\''
    if "id" in key:
        return "item-1"
    if "description" in key or "message" in key or "content" in key:
        return '"example"'
    return "value"


def _sample_flag_value(flag: Flag) -> str | None:
    """Return a sample value for a flag, or None for boolean/toggle flags."""
    if flag.long in {
        "--all",
        "--closed",
        "--clear",
        "--attach",
        "--direct",
        "--close-link",
        "--baseline-only",
        "--third-party",
        "--validate-only",
        "--warn-only",
        "--no-hitl",
    }:
        return None

    long_key = flag.long.lstrip("-").lower()
    desc = flag.desc.lower()
    if "json" in desc or "payload" in desc or "widget expression" in desc:
        return '\'{"key":"value"}\''
    if "iso8601" in desc or "iso 8601" in desc or "utc" in desc or "expiry" in desc:
        return "2026-01-01T00:00:00Z"
    if "project root" in desc or "project directory" in desc or "directory" in desc:
        return "/tmp/project"
    if "path" in desc or "file" in desc:
        return "/tmp/example.txt"
    if "agent" in desc:
        return "claude"
    if "thinking mode" in desc:
        return "slow"
    if "phase" in desc:
        return "build"
    if "status" in desc:
        return "degraded"
    if "format" in desc:
        return "markdown"
    if "reason" in desc:
        return '"example reason"'
    if "summary" in desc:
        return '"example summary"'
    if "customer" in desc:
        return '"Jane Doe"'
    if "channel" in desc:
        return "channel:demo:events"

    if "session" in long_key:
        return "sess-123"
    if "slug" in long_key:
        return "my-slug"
    if "project" in long_key or "cwd" in long_key or "root" in long_key:
        return "/tmp/project"
    if "path" in long_key or "file" in long_key:
        return "/tmp/example.txt"
    if "agent" in long_key:
        return "claude"
    if "mode" in long_key:
        return "slow"
    if "phase" in long_key:
        return "build"
    if "status" in long_key:
        return "degraded"
    if "format" in long_key:
        return "markdown"
    if "until" in long_key or "date" in long_key:
        return "2026-01-01T00:00:00Z"
    if "data" in long_key:
        return '\'{"key":"value"}\''
    if "after" in long_key:
        return "dep-a"
    if "before" in long_key:
        return "target-slug"
    if "title" in long_key:
        return '"Example Title"'
    if "description" in long_key or "message" in long_key or "content" in long_key:
        return '"example"'
    return "value"


def _example_positionals(args_spec: str) -> list[str]:
    """Build sample positional arguments from a usage args spec string."""
    values: list[str] = []
    for raw in args_spec.split():
        token = raw.strip()
        if not token:
            continue
        if token.startswith("-"):
            continue
        values.append(_sample_positional_value(token))
    return values


def _example_commands(command_parts: list[str], args_spec: str, flags: list[Flag]) -> list[str]:
    """Generate example command lines that touch positional args and each flag."""
    base = ["telec", *command_parts, *_example_positionals(args_spec)]
    examples: list[str] = [" ".join(base).strip()]
    seen: set[str] = set(examples)

    for flag in flags:
        if flag.long == "--help":
            continue
        value = _sample_flag_value(flag)
        parts = [*base, flag.long]
        if value is not None:
            parts.append(value)
        line = " ".join(parts).strip()
        if line not in seen:
            seen.add(line)
            examples.append(line)

    return examples


def _usage_subcmd(cmd_name: str) -> str:
    """Generate detailed subcommand help. All flags shown."""
    cmd = CLI_SURFACE[cmd_name]
    col = 49
    lines = ["Usage:"]

    if cmd.subcommands:
        if cmd.standalone:
            args_str = f" {cmd.args}" if cmd.args else ""
            flag_hints = " [options]" if cmd.flags else ""
            entry = f"telec {cmd_name}{args_str}{flag_hints}"
            lines.append(f"  {entry:<{col}}# {cmd.desc}")

            visible_cmd_flags = [f for f in cmd.flags if f.long != "--help"] if cmd.flags else []
            if visible_cmd_flags:
                lines.append("\nOptions:")
                for f in visible_cmd_flags:
                    flag_label = f"  {f.short}, {f.long}" if f.short else f"  {f.long}"
                    lines.append(f"{flag_label:<25s}{f.desc}")
                examples = _example_commands([cmd_name], cmd.args, visible_cmd_flags)
                if examples:
                    lines.append("\nExamples:")
                    for example in examples:
                        lines.append(f"  {example}")

        for sub_name, sub_cmd in cmd.subcommands.items():
            expanded = HELP_SUBCOMMAND_EXPANSIONS.get(cmd_name, {}).get(sub_name)
            if expanded:
                for child_name, child_desc in expanded:
                    entry = f"telec {cmd_name} {sub_name} {child_name}"
                    lines.append(f"  {entry:<{col}}# {child_desc}")
                continue
            args_str = f" {sub_cmd.args}" if sub_cmd.args else ""
            flag_hints = " [options]" if sub_cmd.flags else ""
            entry = f"telec {cmd_name} {sub_name}{args_str}{flag_hints}"
            lines.append(f"  {entry:<{col}}# {sub_cmd.desc}")

        # Group flags by shared flag set for compact display
        seen_groups: dict[str, list[tuple[str, list[Flag]]]] = {}
        for sub_name, sub_cmd in cmd.subcommands.items():
            if not sub_cmd.flags:
                continue
            key = "|".join(f.long for f in sub_cmd.flags)
            seen_groups.setdefault(key, []).append((sub_name, sub_cmd.flags))

        for _key, group in seen_groups.items():
            names = [n for n, _ in group]
            flags = group[0][1]
            label = "Options" if len(names) == len(cmd.subcommands) else f"{'/'.join(names)} options"
            lines.append(f"\n{label}:")
            for f in flags:
                flag_label = f"  {f.short}, {f.long}" if f.short else f"  {f.long}"
                lines.append(f"{flag_label:<25s}{f.desc}")
    else:
        args_str = f" {cmd.args}" if cmd.args else ""
        lines.append(f"  telec {cmd_name}{args_str}")
        visible = [f for f in cmd.flags if f.long != "--help"] if cmd.flags else []
        if cmd.flags:
            if visible:
                lines.append("\nOptions:")
                for f in visible:
                    flag_label = f"  {f.short}, {f.long}" if f.short else f"  {f.long}"
                    lines.append(f"{flag_label:<25s}{f.desc}")

        notes = cmd.notes or [f"Use this command to {cmd.desc.lower()}."]
        lines.append("\nNotes:")
        for note in notes:
            lines.append(f"  {note}")

        examples = cmd.examples or _example_commands([cmd_name], cmd.args, visible)
        if examples:
            lines.append("\nExamples:")
            for example in examples:
                lines.append(f"  {example}")

    # Collect notes only for grouped commands (leaf commands already render notes above).
    if cmd.subcommands:
        all_notes: list[str] = []
        for _sub_name, sub_cmd in cmd.subcommands.items():
            all_notes.extend(sub_cmd.notes)
        all_notes.extend(cmd.notes)
        unique_notes = list(dict.fromkeys(all_notes))
        if unique_notes:
            lines.append("\nNotes:")
            for note in unique_notes:
                lines.append(f"  {note}")

    return "\n".join(lines) + "\n"


def _usage_leaf(cmd_name: str, sub_name: str) -> str:
    """Generate help for a specific subcommand (e.g. 'roadmap add')."""
    cmd = CLI_SURFACE[cmd_name]
    sub = cmd.subcommands.get(sub_name)
    if not sub:
        return _usage_subcmd(cmd_name)

    args_str = f" {sub.args}" if sub.args else ""
    lines = ["Usage:", f"  telec {cmd_name} {sub_name}{args_str}"]
    lines.append(f"\n  {sub.desc}")

    visible = [f for f in sub.flags if f.long != "--help"] if sub.flags else []
    if visible:
        lines.append("\nOptions:")
        for f in visible:
            flag_label = f"  {f.short}, {f.long}" if f.short else f"  {f.long}"
            lines.append(f"{flag_label:<25s}{f.desc}")

    notes = sub.notes or [f"Use this command to {sub.desc.lower()}."]
    lines.append("\nNotes:")
    for note in notes:
        lines.append(f"  {note}")

    examples = sub.examples or _example_commands([cmd_name, sub_name], sub.args, visible)
    if examples:
        lines.append("\nExamples:")
        for example in examples:
            lines.append(f"  {example}")

    return "\n".join(lines) + "\n"


def _print_completion(value: str, description: str) -> None:
    """Print completion in value<TAB>description format for zsh."""
    print(f"{value}\t{description}")


def _handle_completion() -> None:
    """Handle shell completion requests."""
    comp_line = os.environ.get("COMP_LINE", "")
    parts = comp_line.split()

    # Remove "telec" from parts if present
    if parts and parts[0] == "telec":
        parts = parts[1:]

    # No command yet - complete commands
    if not parts:
        for cmd in _COMMANDS:
            _print_completion(cmd, _COMMAND_DESCRIPTIONS.get(cmd, ""))
        return

    cmd = parts[0]
    rest = parts[1:]
    current = parts[-1] if parts else ""
    is_partial = not comp_line.endswith(" ")

    # Completing the command itself
    if len(parts) == 1 and is_partial:
        for c in _COMMANDS:
            if c.startswith(current):
                _print_completion(c, _COMMAND_DESCRIPTIONS.get(c, ""))
        return

    # Command-specific completions
    if cmd in ("sync", "watch"):
        if cmd in CLI_SURFACE:
            _complete_flags(CLI_SURFACE[cmd].flag_tuples, rest, current, is_partial)
    elif cmd in (
        "todo",
        "roadmap",
        "config",
        "sessions",
        "agents",
        "channels",
        "docs",
        "computers",
        "projects",
        "bugs",
        "auth",
    ):
        _complete_subcmd(cmd, rest, current, is_partial)


def _flag_used(flag_tuple: tuple[str | None, str, str], used: set[str]) -> bool:
    """Check if a flag (short or long form) was already used."""
    short, long, _ = flag_tuple
    return (short and short in used) or (long in used)


def _flag_matches(flag_tuple: tuple[str | None, str, str], prefix: str) -> bool:
    """Check if a flag matches the current prefix."""
    short, long, _ = flag_tuple
    return (short and short.startswith(prefix)) or long.startswith(prefix)


def _print_flag(flag_tuple: tuple[str | None, str, str]) -> None:
    """Print a flag completion with optional short form."""
    short, long, desc = flag_tuple
    if short:
        _print_completion(f"{short}, {long}", desc)
    else:
        _print_completion(long, desc)


def _complete_flags(
    flags: list[tuple[str | None, str, str]], rest: list[str], current: str, is_partial: bool, args: str = ""
) -> None:
    """Complete commands with flags and optional positional arg hints."""
    used_flags = set(rest)
    if is_partial and current.startswith("-"):
        for flag in flags:
            if _flag_matches(flag, current) and not _flag_used(flag, used_flags):
                _print_flag(flag)
        return

    # Show positional arg hints for args not yet provided
    if args:
        positional_rest = [a for a in rest if not a.startswith("-")]
        for i, arg_hint in enumerate(args.split()):
            if i >= len(positional_rest):
                _print_completion(arg_hint, "required" if arg_hint.startswith("<") else "optional")

    for flag in flags:
        if not _flag_used(flag, used_flags):
            _print_flag(flag)


def _complete_subcmd(cmd_name: str, rest: list[str], current: str, is_partial: bool) -> None:
    """Complete commands with subcommands (todo, roadmap, config, etc.)."""
    cmd_def = CLI_SURFACE[cmd_name]

    # Subcommand completion: no args yet, or partially typing subcommand name
    if not rest or (len(rest) == 1 and is_partial):
        for subcommand, desc in cmd_def.subcmd_tuples:
            if not is_partial or subcommand.startswith(current):
                _print_completion(subcommand, desc)
        return

    # Subcommand-level completion: positional args + flags
    subcmd = rest[0]
    sub_def = cmd_def.subcommands.get(subcmd)
    flags = sub_def.flag_tuples if sub_def and sub_def.flags else cmd_def.flag_tuples

    # Count non-flag args provided after the subcommand
    positional_rest = [a for a in rest[1:] if not a.startswith("-")]
    expected_positionals = sub_def.args.split() if sub_def and sub_def.args else []

    used = set(rest[1:])
    if is_partial and current.startswith("-"):
        for flag in flags:
            if _flag_matches(flag, current) and not _flag_used(flag, used):
                _print_flag(flag)
        return

    # Show positional arg hints for args not yet provided
    for i, arg_hint in enumerate(expected_positionals):
        if i >= len(positional_rest):
            _print_completion(arg_hint, "required" if arg_hint.startswith("<") else "optional")

    for flag in flags:
        if not _flag_used(flag, used):
            _print_flag(flag)


def main() -> None:
    """Main entry point for telec CLI."""
    # Handle shell completion before any other setup
    if os.environ.get("TELEC_COMPLETE"):
        _handle_completion()
        return

    setup_logging()
    logger = get_logger(__name__)
    logger.trace("[PERF] main() imports done dt=%.3f", _t.monotonic() - _BOOT)
    argv = sys.argv[1:]

    # Handle --help / -h
    if argv and argv[0] in ("--help", "-h"):
        print(_usage())
        return

    if argv:
        token = argv[0].lstrip("/")
        if token in {cmd.value for cmd in TelecCommand}:
            _handle_cli_command(argv)
            return
        if argv[0].startswith("/"):
            _handle_cli_command(argv)
            return
        print(f"Unknown command: {argv[0]}")
        print(_usage())
        raise SystemExit(1)

    # TUI mode - ensure we're in tmux for pane preview
    if not os.environ.get(TMUX_ENV_KEY):
        # Bridge outer-shell login identity into the trusted tc_tui session.
        terminal_email = read_current_session_email()
        if _requires_tui_login() and not terminal_email:
            print("Error: telec auth login is required before starting the TUI in multi-user mode.")
            print("Run: telec auth login <email>")
            raise SystemExit(1)
        # Always restart the TUI session to avoid adopting stale panes
        tmux = config.computer.tmux_binary
        result = subprocess.run(
            [tmux, "has-session", "-t", TUI_SESSION_NAME],
            capture_output=True,
        )
        if result.returncode == 0:
            subprocess.run(
                [tmux, "kill-session", "-t", TUI_SESSION_NAME],
                check=False,
                capture_output=True,
            )
        # Create new named session and mark it as telec-managed
        tmux_args = [tmux, "new-session", "-s", TUI_SESSION_NAME, "-e", f"{TUI_ENV_KEY}={ENV_ENABLE}"]
        if terminal_email:
            tmux_args.extend(["-e", f"{TUI_AUTH_EMAIL_ENV_KEY}={terminal_email}"])
        for key, value in os.environ.items():
            if key in {TUI_ENV_KEY, TUI_AUTH_EMAIL_ENV_KEY}:
                continue
            tmux_args.extend(["-e", f"{key}={value}"])
        tmux_args.append("telec")
        os.execlp(tmux, *tmux_args)

    try:
        _run_tui()
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    except Exception:
        logger.exception("telec TUI crashed during startup")


def _run_tui(start_view: int = 1, config_guided: bool = False) -> None:
    """Run TUI application.

    On SIGUSR2 the app exits with RELOAD_EXIT. We skip tmux session
    cleanup and os.execvp to restart the process, reloading all Python
    modules from disk.
    """
    logger = get_logger(__name__)
    _t0 = _t.monotonic()
    from teleclaude.cli.tui.app import RELOAD_EXIT, TelecApp

    logger.trace("[PERF] _run_tui import TelecApp dt=%.3f", _t.monotonic() - _t0)
    api = TelecAPIClient()
    app = TelecApp(api, start_view=start_view)
    logger.trace("[PERF] _run_tui TelecApp created dt=%.3f", _t.monotonic() - _t0)

    reload_requested = False

    try:
        _ensure_tmux_status_hidden_for_tui()
        _ensure_tmux_mouse_on()
        logger.trace("[PERF] _run_tui pre-app.run dt=%.3f", _t.monotonic() - _t0)
        result = app.run()
        reload_requested = result == RELOAD_EXIT
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    except Exception:
        logger.exception("telec TUI crashed")
    finally:
        if not reload_requested:
            _maybe_kill_tui_session()

    if reload_requested:
        # Re-exec via the Python interpreter + module flag, not sys.argv[0]
        # (which may be a .py file path without execute permission).
        # Mark as reload so the new process skips re-applying pane layout.
        os.environ["TELEC_RELOAD"] = "1"
        python = sys.executable
        os.execvp(python, [python, "-m", "teleclaude.cli.telec"])


def _run_tui_config_mode(guided: bool = False) -> None:
    """Run TUI in configuration mode."""
    _run_tui(start_view=3, config_guided=guided)


def _handle_cli_command(argv: list[str]) -> None:
    """Handle CLI shortcuts like /list, /claude, etc.

    Args:
        argv: Command-line arguments
    """
    cmd = argv[0].lstrip("/")
    args = argv[1:]

    # Centralized -h handling for all commands
    if _maybe_show_help(cmd, args):
        return

    try:
        cmd_enum = TelecCommand(cmd)
    except ValueError:
        cmd_enum = None

    cmd_def = CLI_SURFACE.get(cmd)
    if cmd_def and cmd_def.subcommands and not cmd_def.standalone and not args:
        print(_usage(cmd))
        return

    if cmd_enum is TelecCommand.SESSIONS:
        if args and args[0] == "revive":
            _handle_revive(args[1:])
        else:
            handle_sessions(args)
    elif cmd_enum is TelecCommand.COMPUTERS:
        _handle_computers(args)
    elif cmd_enum is TelecCommand.PROJECTS:
        _handle_projects(args)
    elif cmd_enum is TelecCommand.AGENTS:
        handle_agents(args)
    elif cmd_enum is TelecCommand.CHANNELS:
        handle_channels(args)
    elif cmd_enum is TelecCommand.INIT:
        init_project(Path.cwd())
    elif cmd_enum is TelecCommand.VERSION:
        _handle_version()
    elif cmd_enum is TelecCommand.SYNC:
        _handle_sync(args)
    elif cmd_enum is TelecCommand.WATCH:
        _handle_watch(args)
    elif cmd_enum is TelecCommand.DOCS:
        _handle_docs(args)
    elif cmd_enum is TelecCommand.TODO:
        _handle_todo(args)
    elif cmd_enum is TelecCommand.ROADMAP:
        _handle_roadmap(args)
    elif cmd_enum is TelecCommand.BUGS:
        _handle_bugs(args)
    elif cmd_enum is TelecCommand.EVENTS:
        _handle_events(args)
    elif cmd_enum is TelecCommand.AUTH:
        _handle_auth(args)
    elif cmd_enum is TelecCommand.CONFIG:
        _handle_config(args)
    else:
        print(f"Unknown command: /{cmd}")
        print(_usage())


def _git_short_commit_hash() -> str:
    """Return HEAD short hash, or 'unknown' when unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"

    if result.returncode != 0:
        return "unknown"

    commit_hash = result.stdout.strip()
    return commit_hash if commit_hash else "unknown"


def _handle_version() -> None:
    """Print runtime version metadata."""
    from teleclaude.config.loader import load_project_config
    from teleclaude.utils import resolve_project_config_path

    commit_hash = _git_short_commit_hash()
    project_root = Path(__file__).resolve().parents[2]
    try:
        project_cfg_path = resolve_project_config_path(project_root)
        project_config = load_project_config(project_cfg_path)
        channel = project_config.deployment.channel
        pinned_minor = project_config.deployment.pinned_minor
    except Exception:
        channel = "alpha"
        pinned_minor = ""

    channel_str = f"{channel} ({pinned_minor})" if channel == "stable" and pinned_minor else channel
    print(f"TeleClaude v{__version__} (channel: {channel_str}, commit: {commit_hash})")


def _maybe_kill_tui_session() -> None:
    """Kill the tc_tui tmux session if telec created it."""
    if os.environ.get(TUI_ENV_KEY) != ENV_ENABLE:
        return
    if not os.environ.get(TMUX_ENV_KEY):
        return

    tmux = config.computer.tmux_binary
    try:
        result = subprocess.run(
            [tmux, "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip() != TUI_SESSION_NAME:
            return
        subprocess.run(
            [tmux, "kill-session", "-t", TUI_SESSION_NAME],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


def _ensure_tmux_mouse_on() -> None:
    """Ensure tmux mouse is enabled for the current window."""
    if not os.environ.get(TMUX_ENV_KEY):
        return
    tmux = config.computer.tmux_binary
    try:
        subprocess.run(
            [tmux, "set-option", "-w", "mouse", "on"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


def _ensure_tmux_status_hidden_for_tui() -> None:
    """Hide tmux status bar for the dedicated tc_tui session."""
    if not os.environ.get(TMUX_ENV_KEY):
        return
    tmux = config.computer.tmux_binary
    try:
        current = subprocess.run(
            [tmux, "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            check=False,
        )
        if current.stdout.strip() != TUI_SESSION_NAME:
            return
        subprocess.run(
            [tmux, "set-option", "-t", TUI_SESSION_NAME, "status", "off"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


def _handle_revive(args: list[str]) -> None:
    """Handle telec sessions revive command."""
    if not args:
        print(_usage("sessions", "revive"))
        return

    attach = False
    session_id: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--attach":
            attach = True
            i += 1
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("sessions", "revive"))
            raise SystemExit(1)
        else:
            if session_id is not None:
                print("Only one session_id is allowed.")
                print(_usage("sessions", "revive"))
                raise SystemExit(1)
            session_id = arg
            i += 1

    if not session_id:
        print("Missing required session_id.")
        print(_usage("sessions", "revive"))
        raise SystemExit(1)

    _revive_session(session_id, attach)


def _revive_session(session_id: str, attach: bool) -> None:
    """Revive a session by TeleClaude session ID."""
    try:
        result = asyncio.run(_revive_session_via_api(session_id))
    except APIError as e:
        print(f"Error: {e}")
        return

    if result.status != "success":
        print(result.error or "Revive failed")
        return

    print(f"Revived session {result.session_id[:8]}")
    try:
        asyncio.run(_send_revive_enter_via_api(result.session_id))
    except APIError as e:
        print(f"Warning: revive kick failed: {e}")
    if attach and result.tmux_session_name:
        _attach_tmux_session(result.tmux_session_name)


async def _revive_session_via_api(session_id: str) -> CreateSessionResult:
    """Revive a session via API and return the response."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.revive_session(session_id)
    finally:
        await api.close()


async def _send_revive_enter_via_api(session_id: str) -> bool:
    """Send an enter key after revive so headless activity resumes immediately."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.send_keys(
            session_id=session_id,
            computer=config.computer.name,
            key="enter",
            count=1,
        )
    finally:
        await api.close()


def _attach_tmux_session(tmux_session_name: str) -> None:
    """Attach or switch to a tmux session."""
    tmux = config.computer.tmux_binary
    if os.environ.get("TMUX"):
        subprocess.run([tmux, "switch-client", "-t", tmux_session_name], check=False)
        return

    os.execlp(tmux, tmux, "attach-session", "-t", tmux_session_name)


def _handle_sync(args: list[str]) -> None:
    """Handle telec sync command."""
    from teleclaude.sync import sync

    project_root = Path.cwd()
    warn_only = False
    validate_only = False

    i = 0
    while i < len(args):
        if args[i] == "--warn-only":
            warn_only = True
            i += 1
        elif args[i] == "--validate-only":
            validate_only = True
            i += 1
        else:
            i += 1

    ok = sync(project_root, validate_only=validate_only, warn_only=warn_only)
    if not ok:
        raise SystemExit(1)


def _handle_watch(args: list[str]) -> None:
    """Handle telec watch command."""
    from teleclaude.cli.watch import run_watch

    run_watch(Path.cwd())


def _handle_docs(args: list[str]) -> None:
    """Handle telec docs commands."""
    if not args:
        print(_usage("docs"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("docs"))
        return

    subcommand = args[0]
    if subcommand == "index":
        _handle_docs_index(args[1:])
    elif subcommand == "get":
        _handle_docs_get(args[1:])
    else:
        print(f"Unknown docs subcommand: {subcommand}")
        print(_usage("docs"))
        raise SystemExit(1)


def _handle_computers(args: list[str]) -> None:
    """Handle telec computers commands."""
    if not args:
        print(_usage("computers"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("computers"))
        return

    subcommand = args[0]
    if subcommand == "list":
        handle_computers(args[1:])
    else:
        print(f"Unknown computers subcommand: {subcommand}")
        print(_usage("computers"))
        raise SystemExit(1)


def _handle_projects(args: list[str]) -> None:
    """Handle telec projects commands."""
    if not args:
        print(_usage("projects"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("projects"))
        return

    subcommand = args[0]
    if subcommand == "list":
        handle_projects(args[1:])
    else:
        print(f"Unknown projects subcommand: {subcommand}")
        print(_usage("projects"))
        raise SystemExit(1)


def _handle_docs_index(args: list[str]) -> None:
    """Handle telec docs index."""
    from teleclaude.context_selector import build_context_output

    project_root = Path.cwd()
    baseline_only = False
    third_party = False
    areas: list[str] = []
    domains: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--baseline-only", "-b"):
            baseline_only = True
            i += 1
        elif arg in ("--third-party", "-t"):
            third_party = True
            i += 1
        elif arg in ("--areas", "-a") and i + 1 < len(args):
            areas = [a.strip() for a in args[i + 1].split(",") if a.strip()]
            i += 2
        elif arg in ("--areas", "-a"):
            print("Missing value for --areas.")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        elif arg in ("--domains", "-d") and i + 1 < len(args):
            domains = [d.strip() for d in args[i + 1].split(",") if d.strip()]
            i += 2
        elif arg in ("--domains", "-d"):
            print("Missing value for --domains.")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("docs", "index"))
            raise SystemExit(1)
        else:
            print(f"Unexpected positional argument for docs index: {arg}")
            print(_usage("docs", "index"))
            raise SystemExit(1)

    output = build_context_output(
        areas=areas,
        project_root=project_root,
        snippet_ids=None,
        baseline_only=baseline_only,
        include_third_party=third_party,
        domains=domains,
    )
    print(output)


def _handle_docs_get(args: list[str]) -> None:
    """Handle telec docs get."""
    from teleclaude.context_selector import build_context_output

    project_root = Path.cwd()
    snippet_ids: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("docs", "get"))
            raise SystemExit(1)
        else:
            for part in arg.split(","):
                part = part.strip()
                if part:
                    snippet_ids.append(part)
            i += 1

    if not snippet_ids:
        print("At least one snippet ID is required.")
        print(_usage("docs", "get"))
        raise SystemExit(1)

    output = build_context_output(
        areas=[],
        project_root=project_root,
        snippet_ids=snippet_ids,
        baseline_only=False,
        include_third_party=False,
        domains=None,
    )
    print(output)


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    if not args:
        print(_usage("todo"))
        return

    subcommand = args[0]
    if subcommand == "create":
        _handle_todo_create(args[1:])
    elif subcommand == "remove":
        _handle_todo_remove(args[1:])
    elif subcommand == "validate":
        _handle_todo_validate(args[1:])
    elif subcommand == "demo":
        _handle_todo_demo(args[1:])
    elif subcommand == "prepare":
        handle_todo_prepare(args[1:])
    elif subcommand == "work":
        handle_todo_work(args[1:])
    elif subcommand == "mark-phase":
        handle_todo_mark_phase(args[1:])
    elif subcommand == "set-deps":
        handle_todo_set_deps(args[1:])
    elif subcommand == "verify-artifacts":
        _handle_todo_verify_artifacts(args[1:])
    else:
        print(f"Unknown todo subcommand: {subcommand}")
        print(_usage("todo"))
        raise SystemExit(1)


def _handle_todo_validate(args: list[str]) -> None:
    """Handle telec todo validate."""

    from teleclaude.resource_validation import validate_all_todos, validate_todo

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "validate"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed for validation.")
                print(_usage("todo", "validate"))
                raise SystemExit(1)
            slug = arg
            i += 1

    errors = []
    if slug:
        errors = validate_todo(slug, project_root)
    else:
        errors = validate_all_todos(project_root)

    if errors:
        print("Todo validation failed:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if slug:
        print(f"✓ Todo {slug} is valid")
    else:
        print("✓ All active todos are valid")


def _extract_demo_blocks(content: str) -> list[tuple[int, str, bool, str]]:
    """Extract bash blocks from demo.md with skip-validation metadata.

    Returns tuples of (line_number, block_text, skipped, skip_reason).
    """
    import re

    blocks: list[tuple[int, str, bool, str]] = []
    skip_pattern = re.compile(r"<!--\s*skip-validation:\s*(.+?)\s*-->")
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        skip_match = skip_pattern.search(line)
        if skip_match:
            skip_reason = skip_match.group(1)
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip().startswith("```bash"):
                block_start = j + 1
                block_lines: list[str] = []
                k = block_start
                while k < len(lines) and lines[k].strip() != "```":
                    block_lines.append(lines[k])
                    k += 1
                blocks.append((j + 1, "\n".join(block_lines), True, skip_reason))
                i = k + 1
                continue
            i += 1
            continue

        if line.strip().startswith("```bash"):
            block_start = i + 1
            block_lines: list[str] = []
            k = block_start
            while k < len(lines) and lines[k].strip() != "```":
                block_lines.append(lines[k])
                k += 1
            blocks.append((i + 1, "\n".join(block_lines), False, ""))
            i = k + 1
            continue

        i += 1

    return blocks


def _find_demo_md(slug: str, project_root: Path) -> Path | None:
    """Find demo.md for a slug. Searches todos/ first, then demos/."""
    for candidate in [
        project_root / "todos" / slug / "demo.md",
        project_root / "demos" / slug / "demo.md",
    ]:
        if candidate.exists():
            return candidate
    return None


def _check_no_demo_marker(content: str) -> str | None:
    """Check for <!-- no-demo: reason --> marker in first 10 lines.

    Returns reason string if found, None otherwise.
    """
    import re

    pattern = re.compile(r"<!--\s*no-demo:\s*(.+?)\s*-->")
    for line in content.split("\n")[:10]:
        match = pattern.search(line)
        if match:
            return match.group(1)
    return None


def _demo_list(project_root: Path) -> None:
    """List available demos from demos/ directory."""
    import json

    demos_dir = project_root / "demos"
    if not demos_dir.exists():
        print("No demos available")
        raise SystemExit(0)

    demo_entries = []
    for demo_path in sorted(demos_dir.iterdir()):
        if not demo_path.is_dir() or demo_path.name.startswith("."):
            continue
        snapshot_path = demo_path / "snapshot.json"
        if snapshot_path.exists():
            try:
                snapshot = json.loads(snapshot_path.read_text())
                demo_entries.append((demo_path.name, snapshot))
            except (json.JSONDecodeError, OSError):
                continue

    if not demo_entries:
        print("No demos available")
        raise SystemExit(0)

    print(f"Available demos ({len(demo_entries)}):\n")
    print(f"{'Slug':<30} {'Title':<50} {'Version':<10} {'Delivered'}")
    print("-" * 110)
    for demo_slug, snapshot in demo_entries:
        title = snapshot.get("title", "")
        version = snapshot.get("version", "")
        delivered = snapshot.get("delivered_date", snapshot.get("delivered", ""))
        print(f"{demo_slug:<30} {title:<50} {version:<10} {delivered}")
    raise SystemExit(0)


def _demo_validate(slug: str, project_root: Path) -> None:
    """Structural validation of demo.md — checks blocks exist and content diverges from skeleton."""
    demo_md_path = _find_demo_md(slug, project_root)
    if demo_md_path is None:
        print(f"Error: No demo.md found for '{slug}'")
        raise SystemExit(1)

    print(f"Validating demo: {slug}")
    print(f"Source: {demo_md_path.relative_to(project_root)}\n")

    content = demo_md_path.read_text(encoding="utf-8")

    # Check for no-demo escape hatch
    no_demo_reason = _check_no_demo_marker(content)
    if no_demo_reason is not None:
        print(f"No-demo marker found: {no_demo_reason}")
        raise SystemExit(0)

    # Check that demo.md diverges from the skeleton template.
    # Strip the {slug} placeholder before comparing so a scaffolded-but-unmodified
    # demo.md is caught regardless of the actual slug value.
    skeleton_path = project_root / "templates" / "todos" / "demo.md"
    if skeleton_path.exists():
        skeleton = skeleton_path.read_text(encoding="utf-8").replace("{slug}", slug)
        if content.strip() == skeleton.strip():
            print("Validation failed: demo.md is unchanged from the skeleton template — no demo implemented")
            raise SystemExit(1)

    blocks = _extract_demo_blocks(content)
    executable = [b for b in blocks if not b[2]]

    if not executable:
        print("Validation failed: no executable bash blocks found")
        raise SystemExit(1)

    print(f"Validation passed: {len(executable)} executable block(s) found")
    if len(blocks) > len(executable):
        print(f"Skipped: {len(blocks) - len(executable)} block(s)")
    raise SystemExit(0)


def _demo_run(slug: str, project_root: Path) -> None:
    """Execute bash blocks from demo.md."""
    demo_md_path = _find_demo_md(slug, project_root)

    if demo_md_path is not None:
        print(f"Running demo: {slug}\n")
        print(f"Source: {demo_md_path.relative_to(project_root)}\n")

        content = demo_md_path.read_text(encoding="utf-8")

        # Check for no-demo escape hatch
        no_demo_reason = _check_no_demo_marker(content)
        if no_demo_reason is not None:
            print(f"No-demo marker found: {no_demo_reason}")
            raise SystemExit(0)

        blocks = _extract_demo_blocks(content)

        if not blocks:
            print("Error: no executable blocks found in demo.md")
            raise SystemExit(1)

        executable = [(ln, blk, reason) for ln, blk, skipped, reason in blocks if not skipped]
        skipped = [(ln, blk, reason) for ln, blk, skipped, reason in blocks if skipped]

        if skipped:
            for ln, _blk, reason in skipped:
                print(f"  SKIP  block at line {ln}: {reason}")
            print()

        if not executable:
            print("Error: all code blocks skipped, no executable blocks")
            raise SystemExit(1)

        # Prepend project venv to PATH so demo blocks use the correct Python
        env = os.environ.copy()
        venv_bin = project_root / ".venv" / "bin"
        if venv_bin.is_dir():
            env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = str(project_root / ".venv")

        passed = 0
        for ln, block, _reason in executable:
            preview = block.strip().split("\n")[0][:60]
            print(f"  RUN   block at line {ln}: {preview}")
            result = subprocess.run(block, shell=True, cwd=project_root, env=env)
            if result.returncode != 0:
                print(f"  FAIL  block at line {ln} exited with {result.returncode}")
                raise SystemExit(1)
            print(f"  PASS  block at line {ln}")
            passed += 1

        print(f"\nDemo passed: {passed}/{len(executable)} blocks")
        if skipped:
            print(f"Skipped: {len(skipped)} blocks")
        raise SystemExit(0)

    # Fallback: snapshot.json demo field (backward compatibility)
    import json
    import re

    pyproject_path = project_root / "pyproject.toml"
    current_version = "0.0.0"
    if pyproject_path.exists():
        pyproject_content = pyproject_path.read_text()
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject_content)
        if match:
            current_version = match.group(1)
    current_major = int(current_version.split(".")[0])

    demos_dir = project_root / "demos"
    demo_path = demos_dir / slug
    snapshot_path = demo_path / "snapshot.json"

    if not demo_path.exists() or not snapshot_path.exists():
        print(f"Error: Demo '{slug}' not found")
        raise SystemExit(1)

    try:
        snapshot = json.loads(snapshot_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Error reading snapshot for '{slug}': {exc}")
        raise SystemExit(1) from exc

    demo_version = snapshot.get("version", "0.0.0")
    demo_major = int(demo_version.split(".")[0])

    if demo_major != current_major:
        print(
            f"Demo from v{demo_version} is incompatible with current v{current_version} "
            f"(major version mismatch). Skipping."
        )
        raise SystemExit(0)

    demo_command = snapshot.get("demo")
    if not demo_command:
        print(f"Warning: Demo '{slug}' has no demo.md or 'demo' field. Skipping execution.")
        raise SystemExit(0)

    print(f"Running demo: {slug} (v{demo_version})\n")
    result = subprocess.run(demo_command, shell=True, cwd=demo_path)
    raise SystemExit(result.returncode)


def _demo_create(slug: str, project_root: Path) -> None:
    """Promote demo.md to demos/{slug}/ with minimal snapshot.json."""
    import json
    import re

    source = _find_demo_md(slug, project_root)
    if source is None:
        print(f"Error: No demo.md found for '{slug}'")
        raise SystemExit(1)

    # Read title from demo.md H1
    content = source.read_text(encoding="utf-8")
    title = slug
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            title = line[2:].strip()
            # Strip "Demo: " prefix if present
            if title.lower().startswith("demo:"):
                title = title[5:].strip()
            break

    # Read version from pyproject.toml
    pyproject_path = project_root / "pyproject.toml"
    version = "0.0.0"
    if pyproject_path.exists():
        pyproject_content = pyproject_path.read_text()
        match = re.search(r'version\s*=\s*"([^"]+)"', pyproject_content)
        if match:
            version = match.group(1)

    # Create demos/{slug}/ and copy demo.md
    demos_dir = project_root / "demos" / slug
    demos_dir.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(source, demos_dir / "demo.md")

    # Generate minimal snapshot.json
    snapshot = {"slug": slug, "title": title, "version": version}
    (demos_dir / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")

    print(f"Demo promoted: {source.relative_to(project_root)} -> demos/{slug}/")
    print(f"Snapshot: {json.dumps(snapshot)}")
    raise SystemExit(0)


def _handle_todo_verify_artifacts(args: list[str]) -> None:
    """Handle telec todo verify-artifacts <slug> --phase <build|review>."""
    from teleclaude.core.next_machine.core import verify_artifacts

    slug: str | None = None
    phase: str | None = None
    cwd = str(Path.cwd())

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--phase",) and i + 1 < len(args):
            phase = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "verify-artifacts"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "verify-artifacts"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if slug is None:
        print("Missing required argument: <slug>")
        print(_usage("todo", "verify-artifacts"))
        raise SystemExit(1)
    if phase is None:
        print("Missing required flag: --phase <build|review>")
        print(_usage("todo", "verify-artifacts"))
        raise SystemExit(1)
    if phase not in ("build", "review"):
        print(f"Invalid phase: {phase!r} (expected 'build' or 'review')")
        raise SystemExit(1)

    passed, report = verify_artifacts(cwd, slug, phase)
    print(report)
    raise SystemExit(0 if passed else 1)


def _handle_todo_demo(args: list[str]) -> None:
    """Handle telec todo demo subcommands: list, validate, run, create."""
    _DEMO_SUBCOMMANDS = {"list", "validate", "run", "create"}
    # Backward compatibility:
    # - `telec todo demo` lists demos
    # - `telec todo demo <slug>` runs demo for slug
    project_root = Path.cwd()
    if not args:
        subcommand = "list"
        remaining_args: list[str] = []
    else:
        subcommand = args[0]
        remaining_args = args[1:]
    slug: str | None = None

    # Backward compatibility: `telec todo demo <slug>` behaves like
    # `telec todo demo run <slug>`.
    if subcommand not in _DEMO_SUBCOMMANDS:
        if subcommand.startswith("-"):
            print(f"Unknown option: {subcommand}")
            print(_usage("todo", "demo"))
            raise SystemExit(1)
        slug = subcommand
        subcommand = "run"

    i = 0
    while i < len(remaining_args):
        arg = remaining_args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "demo"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "demo"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if subcommand == "list":
        if slug is not None:
            print("The 'list' subcommand does not take a slug.")
            print(_usage("todo", "demo"))
            raise SystemExit(1)
        _demo_list(project_root)
        return

    # validate/run/create require slug
    if slug is None:
        print(f"Missing required slug for 'demo {subcommand}'.")
        print(_usage("todo", "demo"))
        raise SystemExit(1)

    if subcommand == "validate":
        _demo_validate(slug, project_root)
    elif subcommand == "run":
        _demo_run(slug, project_root)
    elif subcommand == "create":
        _demo_create(slug, project_root)


def _handle_todo_create(args: list[str]) -> None:
    """Handle telec todo create."""
    if not args:
        print(_usage("todo", "create"))
        return

    slug: str | None = None
    project_root = Path.cwd()
    after: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "create"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "create"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "create"))
        raise SystemExit(1)

    try:
        todo_dir = create_todo_skeleton(project_root, slug, after=after)
    except (ValueError, FileExistsError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Created todo skeleton: {todo_dir}")
    if after:
        print(f"Updated dependencies for {slug}: {', '.join(after)}")


def _handle_todo_remove(args: list[str]) -> None:
    """Handle telec todo remove."""
    from teleclaude.todo_scaffold import remove_todo

    if not args:
        print(_usage("todo", "remove"))
        return

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("todo", "remove"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("todo", "remove"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("todo", "remove"))
        raise SystemExit(1)

    try:
        remove_todo(project_root, slug)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Removed todo: {slug}")


def _handle_roadmap(args: list[str]) -> None:
    """Handle telec roadmap commands."""

    if not args:
        print(_usage("roadmap"))
        return

    subcommand = args[0]
    if subcommand == "list":
        _handle_roadmap_show(args[1:])
    elif subcommand == "add":
        _handle_roadmap_add(args[1:])
    elif subcommand == "remove":
        _handle_roadmap_remove(args[1:])
    elif subcommand == "move":
        _handle_roadmap_move(args[1:])
    elif subcommand == "deps":
        _handle_roadmap_deps(args[1:])
    elif subcommand == "freeze":
        _handle_roadmap_freeze(args[1:])
    elif subcommand == "deliver":
        _handle_roadmap_deliver(args[1:])
    else:
        print(f"Unknown roadmap subcommand: {subcommand}")
        print(_usage("roadmap"))
        raise SystemExit(1)


def _handle_roadmap_show(args: list[str]) -> None:
    """Display the roadmap grouped by group, with deps and state."""
    import json

    from teleclaude.core.models import TodoInfo
    from teleclaude.core.roadmap import assemble_roadmap

    project_root = Path.cwd()
    include_icebox = False
    icebox_only = False
    include_delivered = False
    delivered_only = False
    json_output = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--include-icebox", "-i"):
            include_icebox = True
            i += 1
        elif arg in ("--icebox-only", "-o"):
            icebox_only = True
            i += 1
        elif arg in ("--include-delivered", "-d"):
            include_delivered = True
            i += 1
        elif arg == "--delivered-only":
            delivered_only = True
            i += 1
        elif arg == "--json":
            json_output = True
            i += 1
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "list"))
            raise SystemExit(1)
        else:
            print(f"Unknown argument: {arg}")
            print(_usage("roadmap", "list"))
            raise SystemExit(1)

    todos = assemble_roadmap(
        str(project_root),
        include_icebox=include_icebox,
        icebox_only=icebox_only,
        include_delivered=include_delivered,
        delivered_only=delivered_only,
    )

    if not todos:
        if json_output:
            print("[]")
        else:
            print("Roadmap is empty.")
        return

    if json_output:
        print(json.dumps([t.to_dict() for t in todos], indent=2))
        return

    # Group todos preserving order
    groups: dict[str, list[TodoInfo]] = {}
    for todo in todos:
        key = todo.group or ""
        groups.setdefault(key, []).append(todo)

    first = True
    for group_name, group_todos in groups.items():
        if not first:
            print()
        first = False

        if group_name:
            print(f"  {group_name}")
            print(f"  {'─' * len(group_name)}")
        else:
            # If default group is not empty and not the only group, add spacing
            if len(groups) > 1:
                print()

        for todo in group_todos:
            phase = todo.status

            extras = []
            if todo.dor_score is not None:
                extras.append(f"DOR:{todo.dor_score}")
            if todo.findings_count > 0:
                extras.append(f"Findings:{todo.findings_count}")
            if todo.build_status and todo.build_status != "pending":
                extras.append(f"Build:{todo.build_status}")
            if todo.review_status and todo.review_status != "pending":
                extras.append(f"Review:{todo.review_status}")
            if todo.delivered_at:
                extras.append(f"Delivered:{todo.delivered_at}")

            extras_str = f" [{', '.join(extras)}]" if extras else ""

            deps_str = ""
            if todo.after:
                deps_str = f" (after: {', '.join(todo.after)})"

            print(f"    {todo.slug} [{phase}]{extras_str}{deps_str}")


def _handle_roadmap_add(args: list[str]) -> None:
    """Handle telec roadmap add <slug> [--group <slug>] [--after d1,d2] [--description T] [--before S]."""
    from teleclaude.core.next_machine.core import add_to_roadmap

    if not args:
        print(_usage("roadmap", "add"))
        return

    slug: str | None = None
    project_root = Path.cwd()
    group: str | None = None
    after: list[str] | None = None
    description: str | None = None
    before: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--group" and i + 1 < len(args):
            group = args[i + 1]
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            after = [p.strip() for p in args[i + 1].split(",") if p.strip()]
            i += 2
        elif arg == "--description" and i + 1 < len(args):
            description = args[i + 1]
            i += 2
        elif arg == "--before" and i + 1 < len(args):
            before = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "add"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_usage("roadmap", "add"))
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "add"))
        raise SystemExit(1)

    if add_to_roadmap(str(project_root), slug, group=group, after=after, description=description, before=before):
        print(f"Added {slug} to roadmap.")
    else:
        print(f"Slug already exists in roadmap: {slug}")


def _handle_roadmap_remove(args: list[str]) -> None:
    """Handle telec roadmap remove <slug>."""
    from teleclaude.core.next_machine.core import remove_from_roadmap

    if not args:
        print(_usage("roadmap", "remove"))
        return

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "remove"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "remove"))
        raise SystemExit(1)

    if remove_from_roadmap(str(project_root), slug):
        print(f"Removed {slug} from roadmap.")
    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_move(args: list[str]) -> None:
    """Handle telec roadmap move <slug> --before <s> | --after <s>."""
    from teleclaude.core.next_machine.core import move_in_roadmap

    if not args:
        print(_usage("roadmap", "move"))
        return

    slug: str | None = None
    project_root = Path.cwd()
    before: str | None = None
    after: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--before" and i + 1 < len(args):
            before = args[i + 1]
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            after = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "move"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "move"))
        raise SystemExit(1)

    if not before and not after:
        print("Either --before or --after is required.")
        print(_usage("roadmap", "move"))
        raise SystemExit(1)

    if move_in_roadmap(str(project_root), slug, before=before, after=after):
        target = before or after
        direction = "before" if before else "after"
        print(f"Moved {slug} {direction} {target}.")
    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_deps(args: list[str]) -> None:
    """Handle telec roadmap deps <slug> --after dep1,dep2."""
    from teleclaude.core.next_machine.core import load_roadmap, save_roadmap

    if not args:
        print(_usage("roadmap", "deps"))
        return

    slug: str | None = None
    project_root = Path.cwd()
    after: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--after" and i + 1 < len(args):
            after = [p.strip() for p in args[i + 1].split(",") if p.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "deps"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "deps"))
        raise SystemExit(1)

    if after is None:
        print("--after is required.")
        print(_usage("roadmap", "deps"))
        raise SystemExit(1)

    cwd = str(project_root)
    entries = load_roadmap(cwd)
    found = False
    for entry in entries:
        if entry.slug == slug:
            entry.after = after
            found = True
            break

    if not found:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)

    save_roadmap(cwd, entries)
    if after:
        print(f"Set dependencies for {slug}: {', '.join(after)}")
    else:
        print(f"Cleared dependencies for {slug}.")


def _handle_roadmap_freeze(args: list[str]) -> None:
    """Handle telec roadmap freeze <slug>."""
    from teleclaude.core.next_machine.core import freeze_to_icebox

    if not args:
        print(_usage("roadmap", "freeze"))
        return

    slug: str | None = None
    project_root = Path.cwd()
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "freeze"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "freeze"))
        raise SystemExit(1)

    if freeze_to_icebox(str(project_root), slug):
        print(f"Froze {slug} → icebox.yaml")
    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_deliver(args: list[str]) -> None:
    """Handle telec roadmap deliver <slug> [--commit SHA] [--title TEXT]."""
    from teleclaude.core.next_machine.core import deliver_to_delivered

    if not args:
        print(_usage("roadmap", "deliver"))
        return

    slug: str | None = None
    project_root = Path.cwd()
    commit: str | None = None
    title: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--commit" and i + 1 < len(args):
            commit = args[i + 1]
            i += 2
        elif arg == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("roadmap", "deliver"))
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_usage("roadmap", "deliver"))
        raise SystemExit(1)

    if deliver_to_delivered(str(project_root), slug, commit=commit, title=title):
        print(f"Delivered {slug} → delivered.yaml")
    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_bugs(args: list[str]) -> None:
    """Handle telec bugs commands."""
    if not args:
        print(_usage("bugs"))
        return

    subcommand = args[0]
    if subcommand == "report":
        _handle_bugs_report(args[1:])
    elif subcommand == "create":
        _handle_bugs_create(args[1:])
    elif subcommand == "list":
        _handle_bugs_list(args[1:])
    else:
        print(f"Unknown bugs subcommand: {subcommand}")
        print(_usage("bugs"))
        raise SystemExit(1)


def _handle_bugs_create(args: list[str]) -> None:
    """Handle telec bugs create <slug>."""
    if not args:
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print("Usage: telec bugs create <slug>")
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print("Usage: telec bugs create <slug>")
                raise SystemExit(1)
            slug = arg
            i += 1

    if slug is None:
        print("Error: slug is required")
        print("Usage: telec bugs create <slug>")
        raise SystemExit(1)

    try:
        bug_dir = create_bug_skeleton(
            project_root=project_root,
            slug=slug,
            description="",
        )
        print(f"Created bug skeleton: {bug_dir}")
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)
    except FileExistsError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1)


def _handle_bugs_report(args: list[str]) -> None:
    """Handle telec bugs report <description> [--slug <slug>]."""
    import re
    import shutil

    if not args:
        print(_usage("bugs", "report"))
        return

    description: str | None = None
    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "report"))
            raise SystemExit(1)
        else:
            if description is not None:
                print("Only one description is allowed.")
                print(_usage("bugs", "report"))
                raise SystemExit(1)
            description = arg
            i += 1

    if not description:
        print("Missing required description.")
        print(_usage("bugs", "report"))
        raise SystemExit(1)

    # Auto-generate slug if not provided
    if not slug:
        slug_base = re.sub(r"[^a-z0-9]+", "-", description.lower()).strip("-")
        slug_base = re.sub(r"-+", "-", slug_base)
        if len(slug_base) > 40:
            slug_base = slug_base[:40].rstrip("-")
        slug = f"fix-{slug_base}"

    try:
        todo_dir = create_bug_skeleton(
            project_root,
            slug,
            description,
        )
    except (ValueError, FileExistsError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    # Create git branch from main
    try:
        subprocess.run(
            ["git", "branch", slug, "main"],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
    except subprocess.CalledProcessError as exc:
        print(f"Error creating branch: {exc.stderr}")
        print(f"Bug scaffold created at {todo_dir}, but branch creation failed.")
        print(f"Create branch manually: git branch {slug} main")
        raise SystemExit(1) from exc

    # Create worktree
    worktree_path = project_root / "trees" / slug
    try:
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), slug],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
    except subprocess.CalledProcessError as exc:
        print(f"Error creating worktree: {exc.stderr}")
        print(f"Bug scaffold created at {todo_dir}, branch created, but worktree failed.")
        print(f"Create worktree manually: git worktree add trees/{slug} {slug}")
        # Clean up branch
        subprocess.run(["git", "branch", "-D", slug], check=False, cwd=str(project_root))
        raise SystemExit(1) from exc

    # Copy bug.md and state.yaml to worktree
    worktree_todo_dir = worktree_path / "todos" / slug
    worktree_todo_dir.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(todo_dir / "bug.md", worktree_todo_dir / "bug.md")
        shutil.copy2(todo_dir / "state.yaml", worktree_todo_dir / "state.yaml")
    except Exception as exc:
        print(f"Error copying files to worktree: {exc}")
        print("Bug scaffold created, branch and worktree created, but file copy failed.")
        print(f"Copy files manually to {worktree_todo_dir}")
        raise SystemExit(1) from exc

    # Dispatch orchestrator
    async def _dispatch_bug_fix() -> "CreateSessionResult":
        api = TelecAPIClient()
        await api.connect()
        try:
            return await api.create_session(
                computer="local",
                project_path=str(project_root),
                subdir=f"trees/{slug}",
                agent="claude",
                thinking_mode="slow",
                title=f"Bug fix: {slug}",
                message=f"Run telec todo work {slug} and follow output verbatim until done.",
                skip_listener_registration=True,
            )
        finally:
            await api.close()

    try:
        result = asyncio.run(_dispatch_bug_fix())
        print(f"Created bug todo: {todo_dir}")
        print(f"Bug slug: {slug}")
        print(f"Branch: {slug}")
        print(f"Worktree: {worktree_path}")
        print(f"Orchestrator session: {result.session_id}")
    except Exception as exc:
        print(f"Error dispatching orchestrator: {exc}")
        print("Bug scaffold, branch, and worktree created successfully.")
        print("Start orchestrator manually from worktree directory:")
        print(f"  cd {worktree_path}")
        print(f"  telec claude 'Run telec todo work {slug} and follow output verbatim until done.'")


def _handle_bugs_list(args: list[str]) -> None:
    """Handle telec bugs list."""
    import yaml

    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)
        else:
            print(f"Unexpected argument: {arg}")
            print(_usage("bugs", "list"))
            raise SystemExit(1)

    todos_dir = project_root / "todos"
    if not todos_dir.exists():
        print("No bugs found")
        return

    bugs = []
    for todo_dir in sorted(todos_dir.iterdir()):
        if not todo_dir.is_dir() or todo_dir.name.startswith("."):
            continue

        bug_md = todo_dir / "bug.md"
        state_yaml = todo_dir / "state.yaml"
        worktree_state = project_root / "trees" / todo_dir.name / "todos" / todo_dir.name / "state.yaml"
        state_path = worktree_state if worktree_state.exists() else state_yaml

        if not bug_md.exists():
            continue

        # Read state to determine status
        status = "unknown"
        if state_path.exists():
            try:
                state = yaml.safe_load(state_path.read_text())
                build = state.get("build", "pending")
                review = state.get("review", "pending")

                if review == "approved":
                    status = "approved"
                elif review == "changes_requested":
                    status = "fixing"
                elif build == "complete":
                    status = "reviewing"
                elif build in ("started", "complete"):
                    status = "building"
                else:
                    status = "pending"
            except (yaml.YAMLError, OSError):
                pass

        bugs.append((todo_dir.name, status))

    if not bugs:
        print("No bugs found")
        return

    print(f"Bug fixes ({len(bugs)}):\n")
    print(f"{'Slug':<40} {'Status':<15}")
    print("-" * 60)
    for slug, status in bugs:
        print(f"{slug:<40} {status:<15}")


def _handle_config(args: list[str]) -> None:
    """Handle telec config command.

    Requires explicit subcommands. Use `telec config wizard` to open the
    interactive configuration UI.
    """

    if not args:
        print(_usage("config"))
        return

    subcommand = args[0]
    if subcommand == "wizard":
        if len(args) > 1:
            print(f"Unexpected arguments for config wizard: {' '.join(args[1:])}")
            print(_usage("config", "wizard"))
            raise SystemExit(1)
        if not sys.stdin.isatty():
            print("Error: Interactive config requires a terminal.")
            raise SystemExit(1)
        _run_tui_config_mode(guided=False)
    elif subcommand in ("get", "patch"):
        from teleclaude.cli.config_cmd import handle_config_command

        handle_config_command(args)
    elif subcommand in ("people", "env", "notify", "validate", "invite"):
        from teleclaude.cli.config_cli import handle_config_cli

        handle_config_cli(args)
    else:
        print(f"Unknown config subcommand: {subcommand}")
        print(_usage("config"))
        raise SystemExit(1)


def _handle_events(args: list[str]) -> None:
    """Handle telec events subcommands."""
    if not args:
        print(_usage("events"))
        return

    subcommand = args[0]
    if subcommand == "list":
        _handle_events_list(args[1:])
    else:
        print(f"Unknown events subcommand: {subcommand}")
        print(_usage("events"))
        raise SystemExit(1)


def _handle_events_list(args: list[str]) -> None:
    """List all registered event schemas."""
    from teleclaude_events import build_default_catalog

    domain_filter: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--domain" and i + 1 < len(args):
            domain_filter = args[i + 1]
            i += 2
        else:
            i += 1

    catalog = build_default_catalog()
    schemas = catalog.list_all()
    if domain_filter:
        schemas = [s for s in schemas if s.domain == domain_filter]

    if not schemas:
        print("No event schemas found.")
        return

    col_widths = [55, 8, 24, 8, 50, 12]
    headers = ["EVENT TYPE", "LEVEL", "DOMAIN", "VISIBLE", "DESCRIPTION", "ACTIONABLE"]
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_row)
    print("-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))
    for s in schemas:
        row = "  ".join(
            [
                str(s.event_type).ljust(col_widths[0]),
                str(s.default_level).ljust(col_widths[1]),
                str(s.domain).ljust(col_widths[2]),
                str(s.default_visibility.value).ljust(col_widths[3]),
                str(s.description).ljust(col_widths[4]),
                ("yes" if s.actionable else "no").ljust(col_widths[5]),
            ]
        )
        print(row)


def _handle_auth(args: list[str]) -> None:
    """Handle telec auth subcommands."""
    if os.environ.get(TMUX_ENV_KEY):
        print("Error: telec auth is unavailable inside tmux sessions.")
        print("Run it from a plain SSH terminal before starting telec.")
        raise SystemExit(1)

    if not args:
        print(_usage("auth"))
        return

    # Support conversational spelling: "telec auth who am i"
    if len(args) >= 3 and args[0] == "who" and args[1] == "am" and args[2].lower().rstrip("?") == "i":
        _handle_whoami(args[3:])
        return

    subcommand = args[0]
    sub_args = args[1:]

    if subcommand == "login":
        _handle_login(sub_args)
    elif subcommand == "whoami":
        _handle_whoami(sub_args)
    elif subcommand == "logout":
        _handle_logout(sub_args)
    else:
        print(f"Unknown auth subcommand: {subcommand}")
        print(_usage("auth"))
        raise SystemExit(1)


def _role_for_email(email: str) -> str | None:
    normalized = email.strip().lower()
    if not normalized:
        return None
    try:
        # Import lazily so CLI commands that do not require config can start
        # even when runtime config is invalid or unavailable.
        from teleclaude.config.loader import load_global_config

        global_cfg = load_global_config()
    except Exception:
        return None
    for person in global_cfg.people:
        if person.email.strip().lower() == normalized:
            return person.role
    return None


def _requires_tui_login() -> bool:
    """Return True when terminal login is required before launching TUI."""
    try:
        from teleclaude.config.loader import load_global_config

        global_cfg = load_global_config()
    except Exception:
        return False
    return len(global_cfg.people) > 1


def _handle_login(args: list[str]) -> None:
    """Handle telec auth login <email>."""
    if not args:
        print(_usage("auth", "login"))
        return
    if len(args) != 1 or args[0].startswith("-"):
        print("Error: login expects exactly one positional email.")
        print(_usage("auth", "login"))
        raise SystemExit(1)

    email = args[0]
    try:
        auth_state = write_current_session_email(email)
    except ValueError as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    role = _role_for_email(auth_state.email)
    role_suffix = f" ({role})" if role else ""
    print(f"Logged in as {auth_state.email}{role_suffix}.")
    print(f"TTY: {auth_state.context.tty}")
    print(f"Session auth file updated: {auth_state.context.auth_path}")


def _handle_whoami(args: list[str]) -> None:
    """Handle telec auth whoami."""
    if args:
        print(f"Unexpected arguments: {' '.join(args)}")
        print(_usage("auth", "whoami"))
        raise SystemExit(1)

    context = get_current_session_context()
    if context is None:
        print("Error: no terminal session detected (TTY unavailable).")
        raise SystemExit(1)

    email = read_current_session_email()
    if not email:
        print(f"No login set for current TTY ({context.tty}).")
        return

    role = _role_for_email(email) or "unresolved"
    print(f"Email: {email}")
    print(f"Role: {role}")
    print(f"TTY: {context.tty}")
    print(f"Session auth file: {context.auth_path}")


def _handle_logout(args: list[str]) -> None:
    """Handle telec auth logout."""
    if args:
        print(f"Unexpected arguments: {' '.join(args)}")
        print(_usage("auth", "logout"))
        raise SystemExit(1)

    context = get_current_session_context()
    if context is None:
        print("Error: no terminal session detected (TTY unavailable).")
        raise SystemExit(1)

    removed = clear_current_session_email()
    if removed:
        print(f"Cleared login for TTY {context.tty}.")
    else:
        print(f"No login file found for TTY {context.tty}.")


if __name__ == MAIN_MODULE:
    main()

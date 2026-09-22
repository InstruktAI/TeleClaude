"""CLI surface — CLI_SURFACE dict and HELP_SUBCOMMAND_EXPANSIONS."""

from __future__ import annotations

from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.types.todo_kind import TODO_KIND_USAGE

from . import flags as F
from .surface_types import (
    _HR_ADMIN,
    _HR_ALL,
    _HR_ALL_NON_ADMIN,
    _HR_MEMBER,
    _HR_MEMBER_CONTRIB,
    _HR_MEMBER_CONTRIB_NEWCOMER,
    _SYS_ALL,
    _SYS_ALL_PLUS_JOB_RUNNER,
    _SYS_INTG,
    _SYS_ORCH,
    _SYS_ORCH_TASKER,
    CommandAuth,
    CommandDef,
    Flag,
    TelecCommand,
    strip_hidden_flag_tokens,
)

__all__ = ["CLI_SURFACE", "CommandAuth", "CommandDef", "Flag", "TelecCommand", "export_surface_markdown"]


def export_surface_markdown() -> str:
    """Return a markdown document describing the full CLI surface."""
    lines: list[str] = ["# TeleClaude CLI Surface\n"]

    for cmd_name, cmd_def in CLI_SURFACE.items():
        if cmd_def.hidden:
            continue
        _render_command(lines, cmd_name, cmd_def, depth=2)

    return "\n".join(lines)


def _render_command(lines: list[str], path: str, cmd: CommandDef, depth: int) -> None:
    """Recursively render a command and its subcommands to markdown lines."""
    prefix = "#" * depth
    lines.append(f"{prefix} `telec {path}`")
    lines.append("")
    lines.append(cmd.desc)
    lines.append("")

    cleaned_args = strip_hidden_flag_tokens(cmd.args, cmd.flags)
    if cleaned_args:
        lines.append(f"**Usage:** `telec {path} {cleaned_args}`")
        lines.append("")

    visible_flags = cmd.visible_flags
    if visible_flags:
        lines.append("**Flags:**")
        lines.append("")
        for flag in visible_flags:
            short = f" (`{flag.short}`)" if flag.short else ""
            lines.append(f"- `{flag.long}`{short}: {flag.desc}")
        lines.append("")

    if cmd.notes:
        lines.append("**Notes:**")
        lines.append("")
        for note in cmd.notes:
            lines.append(f"- {note}")
        lines.append("")

    for sub_name, sub_def in cmd.subcommands.items():
        if sub_def.hidden:
            continue
        _render_command(lines, f"{path} {sub_name}", sub_def, depth=min(depth + 1, 6))


CLI_SURFACE: dict[str, CommandDef] = {
    "sessions": CommandDef(
        desc="Manage agent sessions",
        subcommands={
            "list": CommandDef(
                desc="List sessions (default: spawned by current, --all for all)",
                args="[--all] [--closed] [--job <value>] [--computer <host>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_SESSIONS_LIST_ALL,
                    F.FLAG_SESSIONS_LIST_CLOSED,
                    F.FLAG_SESSIONS_LIST_JOB,
                    F.FLAG_COMPUTER,
                ],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "coordinate": CommandDef(
                desc="Adopt this session as the project's single coordinator (human-directed only; refuses if one is live)",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
            "start": CommandDef(
                desc="Start a new agent session",
                args=(
                    "[--computer <host>] [--path <path>] [--agent <name>] [--mode <mode>]"
                    " [--message <msg>] [--direct] [--detach]"
                ),
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_COMPUTER,
                    F.FLAG_PATH,
                    F.FLAG_AGENT,
                    F.FLAG_MODE,
                    F.FLAG_MESSAGE,
                    F.FLAG_DIRECT_START,
                    F.FLAG_DETACH,
                ],
                notes=[
                    (
                        "Use --direct for peer conversation mode when you want shared linked output "
                        "instead of worker supervision notifications."
                    ),
                    (
                        "--detach: do not use unless explicitly instructed. Sanctioned only for a "
                        "personal-assistant dispatching an orchestrator to a project. --detach disables "
                        "notifications — you will not learn when the child finishes, so omit it whenever "
                        "your next step depends on the result."
                    ),
                ],
                examples=[
                    "telec sessions start --path /another/project",
                    "telec sessions start --agent claude --mode slow",
                    'telec sessions start --message "Implement feature X"',
                    "telec sessions start --direct",
                ],
                auth=CommandAuth(system=_SYS_ORCH_TASKER, human=_HR_MEMBER),
            ),
            "send": CommandDef(
                desc="Send a message to a running session",
                args="<session_id> [<message>] [--computer <host>] [--direct] [--close-link]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_COMPUTER,
                    F.FLAG_DIRECT_SEND,
                    F.FLAG_CLOSE_LINK,
                    F.FLAG_CLOSE_LINK_ALIAS,
                    F.FLAG_MESSAGE_ALIAS,
                    F.FLAG_SESSION,
                ],
                notes=[
                    "Positional form is canonical: telec sessions send <session_id> <message>.",
                    "One-time ignition: sending once with --direct establishes the link.",
                    "After link creation, turn-complete outputs from linked peers are cross-shared automatically.",
                    "Only one party needs to send with --direct to establish the link.",
                    "Use --close-link to sever the direct link for all members.",
                ],
                examples=[
                    'telec sessions send sess-123 "Please implement feature X"',
                    'telec sessions send sess-123 "Let\'s discuss the architecture" --direct',
                    "telec sessions send sess-123 --close-link",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
            "tail": CommandDef(
                desc="Get recent messages from a session's transcript",
                args="<session_id> [--since <ts>] [--tools] [--thinking] [--full] [--pane]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_SESSION,
                    F.FLAG_TAIL_SINCE,
                    F.FLAG_TAIL_TOOLS,
                    F.FLAG_THINKING,
                    F.FLAG_TAIL_FULL,
                    F.FLAG_TAIL_PANE,
                    F.FLAG_COMPUTER,
                ],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "run": CommandDef(
                desc="Run a canonical command on a new agent session",
                args=(
                    "[--command <cmd>] [--path <path>] [--args <val>] [--agent <name>]"
                    " [--mode <mode>] [--computer <host>] [--subfolder <dir>] [--detach]"
                    " [--additional-context <ctx>]"
                ),
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_RUN_COMMAND,
                    F.FLAG_PATH,
                    F.FLAG_RUN_ARGS,
                    F.FLAG_AGENT,
                    F.FLAG_MODE,
                    F.FLAG_COMPUTER,
                    F.FLAG_RUN_SUBFOLDER,
                    F.FLAG_DETACH,
                    F.FLAG_RUN_ADDITIONAL_CONTEXT,
                ],
                notes=[
                    "Creates a fresh session and runs the bare canonical command as the first agent message.",
                    "Worker lifecycle commands: next-build, next-review-build, next-finalize.",
                    (
                        "--detach: do not use unless explicitly instructed. Sanctioned only for a "
                        "personal-assistant dispatching an orchestrator to a project. --detach disables "
                        "notifications — you will not learn when the child finishes, so omit it whenever "
                        "your next step depends on the result."
                    ),
                ],
                examples=[
                    "telec sessions run --command next-build --args my-slug",
                    "telec sessions run --command next-review-plan --args my-slug",
                ],
                auth=CommandAuth(system=_SYS_ORCH_TASKER, human=_HR_MEMBER),
            ),
            "revive": CommandDef(
                desc="Revive session by TeleClaude session ID",
                args="<session_id>",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_REVIVE_AGENT,
                    F.FLAG_REVIVE_ATTACH,
                    F.FLAG_COMPUTER,
                ],
                notes=[
                    (
                        "Restarts an ended session's agent with the full prior transcript, "
                        "so the agent resumes with its original context intact."
                    ),
                    "Without --agent, session_id is a TeleClaude session ID.",
                    "With --agent, session_id is a native agent session ID resolved via the specified agent.",
                ],
                auth=CommandAuth(system=_SYS_ORCH_TASKER, human=_HR_ADMIN),
            ),
            "end": CommandDef(
                desc="End a session, or every direct child of the calling session when targetless",
                args="[<session_id>] [--computer <host>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_SESSION,
                    F.FLAG_COMPUTER,
                ],
                notes=[
                    "With no target, closes every live direct child of the calling session across computers.",
                    "Targetless cleanup is idempotent and rejects --computer so caller scope cannot be narrowed.",
                ],
                auth=CommandAuth(system=_SYS_ORCH_TASKER | _SYS_INTG, human=_HR_MEMBER),
            ),
            "unsubscribe": CommandDef(
                desc="Stop receiving notifications from a session",
                args="<session_id>",
                flags=[F.FLAG_HELP, F.FLAG_COMPUTER],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
            "restart": CommandDef(
                desc="Restart an agent session ('self' to restart own session)",
                args="<session_id> [--handoff [<agent>]]",
                flags=[F.FLAG_HELP, F.FLAG_COMPUTER, F.FLAG_HANDOFF],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ADMIN),
            ),
            "result": CommandDef(
                desc="Send a formatted result to the session's user",
                args="<content> [--format <fmt>]",
                flags=[F.FLAG_HELP, F.FLAG_RESULT_FORMAT, F.FLAG_RESULT_CONTENT_ALIAS],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB),
            ),
            "file": CommandDef(
                desc="Send a file to the session's user",
                args="[--path <path>] [--filename <name>] [--caption <text>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_FILE_PATH,
                    F.FLAG_FILE_FILENAME,
                    F.FLAG_FILE_CAPTION,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "escalate": CommandDef(
                desc="Escalate to an admin via Discord",
                args="[--customer <name>] [--reason <text>] [--summary <text>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_ESCALATE_CUSTOMER,
                    F.FLAG_ESCALATE_REASON,
                    F.FLAG_ESCALATE_SUMMARY,
                ],
                auth=CommandAuth(
                    system=_SYS_ALL | _SYS_INTG,
                    human=_HR_ALL_NON_ADMIN,
                ),
            ),
        },
    ),
    "reminders": CommandDef(
        desc="Manage durable reminders for the calling session",
        subcommands={
            "set": CommandDef(
                desc="Arm or atomically replace a session-local reminder",
                args=("<slug> [--after <duration> | --at <RFC3339>] [--intent <text>] [--repeat] [--slug <target>]"),
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_REMINDER_AFTER,
                    F.FLAG_REMINDER_AT,
                    F.FLAG_REMINDER_INTENT,
                    F.FLAG_REMINDER_REPEAT,
                    F.FLAG_REMINDER_SLUG,
                ],
                auth=CommandAuth(system=_SYS_ALL_PLUS_JOB_RUNNER, human=_HR_ALL),
            ),
            "list": CommandDef(
                desc="List every live reminder owned by the calling session",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL_PLUS_JOB_RUNNER, human=_HR_ALL),
            ),
            "cancel": CommandDef(
                desc="Idempotently cancel one or all caller-owned reminders",
                args="[<slug>] [--all]",
                flags=[F.FLAG_HELP, F.FLAG_REMINDER_CANCEL_ALL],
                auth=CommandAuth(system=_SYS_ALL_PLUS_JOB_RUNNER, human=_HR_ALL),
            ),
        },
    ),
    "computers": CommandDef(
        desc="Manage computer inventory",
        subcommands={
            "list": CommandDef(
                desc="List available computers (local + cached remote)",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
        },
    ),
    "projects": CommandDef(
        desc="Manage project inventory and onboarding",
        subcommands={
            "list": CommandDef(
                desc="List projects on local and remote computers",
                args="[--computer <host>]",
                flags=[F.FLAG_HELP, F.FLAG_COMPUTER],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "init": CommandDef(
                desc="Initialize project plumbing and sync artifacts",
                flags=[F.FLAG_HELP],
                notes=[
                    "Sets up git hooks, syncs artifacts, and registers the project root.",
                    "AI-driven analysis lives in `telec projects {onboard,analyze,assess}`.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "converge": CommandDef(
                desc="Converge plumbing for every registered root on this machine",
                flags=[F.FLAG_HELP],
                notes=["Writes no tracked files."],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "onboard": CommandDef(
                desc="Full project bootstrap: init plumbing, then dispatch config assessment and doc-snippet analysis",
                flags=[F.FLAG_HELP],
                notes=[
                    "Runs `telec projects init` synchronously, then dispatches `telec projects assess` and `telec projects analyze`.",
                    "AI sessions run concurrently in tmux after dispatch — monitor via `telec sessions list` according to heartbeat policy.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "analyze": CommandDef(
                desc="Generate project doc snippets via AI analysis",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "assess": CommandDef(
                desc="Assess project quality tool configuration against blessed templates",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
        },
    ),
    "companies": CommandDef(
        desc="Manage company onboarding",
        subcommands={
            "onboard": CommandDef(
                desc="Scaffold a company under ~/.teleclaude/companies, or dispatch doc-snippet analysis",
                args="<name> [--slug <value>]",
                flags=[F.FLAG_HELP, F.FLAG_COMPANY_SLUG],
                notes=[
                    "Scaffolds companies/<slug>/{inbox (git), docs/<taxonomy>, teleclaude.yml, meta.yaml, .env} synchronously.",
                    "Re-running reprocesses only changed inbox material (SHA-tracked in meta.yaml).",
                    "The analysis session runs concurrently in tmux after dispatch — monitor via `telec sessions list` according to heartbeat policy.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
        },
    ),
    "agents": CommandDef(
        desc="Manage agent dispatch status and availability",
        subcommands={
            "availability": CommandDef(
                desc="Get current availability for all agents",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "status": CommandDef(
                desc="Set dispatch status for a specific agent",
                args="<agent> [--status <val>] [--reason <text>] [--model <model>] [--until <ts>] [--clear]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_AGENT_STATUS,
                    F.FLAG_AGENT_STATUS_REASON,
                    F.FLAG_AGENT_STATUS_MODEL,
                    F.FLAG_AGENT_STATUS_UNTIL,
                    F.FLAG_AGENT_STATUS_CLEAR,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ADMIN),
            ),
        },
    ),
    "channels": CommandDef(
        desc="Manage internal Redis Stream channels",
        subcommands={
            "list": CommandDef(
                desc="List active channels",
                args="[--project <name>]",
                flags=[F.FLAG_HELP, F.FLAG_PROJECT_FILTER],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
            "publish": CommandDef(
                desc="Publish a message to a channel",
                args="<channel> [--data <json>]",
                flags=[F.FLAG_HELP, F.FLAG_CHANNEL_DATA],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
        },
    ),
    "operations": CommandDef(
        desc="Inspect durable long-running operations",
        subcommands={
            "get": CommandDef(
                desc="Fetch durable operation status by operation_id",
                args="<operation_id> [-c/--computer <computer>]",
                flags=[F.FLAG_HELP, F.FLAG_COMPUTER],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER),
            ),
        },
    ),
    "version": CommandDef(
        desc="Print version, channel, and commit",
        flags=[F.FLAG_HELP],
        auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
    ),
    "reload": CommandDef(
        desc="Reload every running telec TUI so it picks up changed TUI code",
        flags=[F.FLAG_HELP],
        notes=[
            "Each running TUI records itself on start; this addresses those records.",
            "A TUI restarts in place, keeping its pid, its tmux panes, and its view state.",
            "Reports the pids reached, so a silent no-op is visible rather than assumed.",
        ],
        auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
    ),
    "sync": CommandDef(
        desc="Validate doc/snippet/artifact sources (blocks on findings) and apply your edits",
        args="[--skip-deploy]",
        flags=[
            F.FLAG_HELP,
            F.FLAG_SKIP_DEPLOY,
            F.FLAG_SKIP_VALIDATION,
        ],
        notes=[
            "Validation always blocks — there is no warn-and-pass mode.",
            "--skip-deploy is the read-only gate (pre-commit / CI / lint); it never mutates the host.",
        ],
        auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
    ),
    "message": CommandDef(
        desc="Send a message to a person by slug",
        args="<slug> <text> [--file <path>] [--subject <text>] [--channel <name>]",
        flags=[
            F.FLAG_HELP,
            F.FLAG_MSG_FILE,
            F.FLAG_MSG_SUBJECT,
            F.FLAG_MSG_CHANNEL,
        ],
        notes=[
            "Recipient-owned routing: defaults to the person's configured preferred_channel (email when unset).",
            "The message text is the file's caption on Telegram/Discord; on email it is the body and the file is an attachment.",
            "A file directed at a WhatsApp delivery is an actionable error — WhatsApp has no media-send capability here.",
            "Discover a person's slug via 'telec config people list'.",
        ],
        examples=[
            'telec message alex "Heads up: the deploy finished"',
            'telec message alex "See attached" --file ./report.pdf',
            'telec message alex "Weekly digest" --channel email --subject "Weekly digest"',
        ],
        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
    ),
    "docs": CommandDef(
        desc="Query documentation snippets",
        subcommands={
            "index": CommandDef(
                desc="List snippet IDs and metadata (phase 1)",
                args=f"[--baseline-only] [--third-party] [--areas <{'|'.join(TAXONOMY_TYPES)}>] [--domains <domain>] [--scope <{F.SCOPE_VALUES}>] [--project <slug>] [--target <slug>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_DOCS_BASELINE_ONLY,
                    F.FLAG_DOCS_THIRD_PARTY,
                    F.FLAG_DOCS_AREAS,
                    F.FLAG_DOCS_DOMAINS,
                    F.FLAG_DOCS_SCOPE,
                    F.FLAG_DOCS_PROJECT,
                    F.FLAG_DOCS_TARGET,
                ],
                notes=[
                    "Pending snippets (those with delivered_by) append ` (delivered by: slug1,slug2)` at the end of the phase-1 line.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "get": CommandDef(
                desc="Fetch full snippet content by ID (phase 2)",
                args=f"<id> [id...] [--scope <{F.SCOPE_VALUES}>] [--project <slug>] [--target <slug>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_DOCS_GET_CLOSURE,
                    F.FLAG_DOCS_SCOPE,
                    F.FLAG_DOCS_PROJECT,
                    F.FLAG_DOCS_GET_TARGET,
                ],
                runtime_notes=[
                    "The generated Activatable Procedures catalog uses `--closure` to load one delivered procedure and its eligible required-read closure in one pass.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
        },
        notes=[
            "Two-phase flow: use 'telec docs index' to discover IDs, then 'telec docs get <id...>' to fetch content.",
            "Omitting --areas and/or --domains returns all values for that dimension; pass a comma-separated subset to filter.",
            "Example phase 1: telec docs index --areas policy,procedure --domains software-development",
            "Example phase 2: telec docs get software-development/policy/testing project/spec/command-surface",
        ],
    ),
    "todo": CommandDef(
        desc="Manage work items",
        subcommands={
            "create": CommandDef(
                desc="Create a todo with substantive content",
                args=f"<slug> <content> --kind <{TODO_KIND_USAGE}> [--approved] [--after <deps>] [--schedule <value>] [--icebox] [--project-root <path>] [--group <parent-slug>] [--plan] [--human-involved <reason>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_AFTER_DEPS,
                    F.FLAG_TODO_SCHEDULE,
                    F.FLAG_TODO_KIND,
                    F.FLAG_TODO_CREATE_APPROVED,
                    F.FLAG_TODO_ICEBOX,
                    F.FLAG_TODO_PROJECT_ROOT,
                    F.FLAG_TODO_GROUP,
                    F.FLAG_TODO_PLAN,
                    F.FLAG_TODO_CREATE_HOLD,
                    F.FLAG_TODO_CREATE_REASON,
                    F.FLAG_HUMAN_INVOLVED,
                ],
                notes=[
                    "Creates the todo entry, canonical state, and stores content as the input artifact.",
                    "--human-involved requires a non-empty reason and resolves the record from observed recency: "
                    "a stale declaration records false and the todo is still created. The reason is never "
                    "stored; omission records false and does not affect later actions.",
                    "Content IS the input artifact — the author's INTENT (WHAT/WHY in operator language, "
                    "affected surfaces, acceptance shape, brownfield grounding), never a work order. Do NOT "
                    "prescribe HOW (file paths, mechanisms, edit/step instructions) or doc-layer deliverables — "
                    "in particular never instruct authoring an ADR or which snippets to write. Per "
                    "software-development/policy/preparation-artifact-quality (Input artifact quality): HOW is "
                    "the prepare phase's hypothesis to verify, doc routing is intake's, and an ADR is governed "
                    "by general/policy/adr-discipline (default none, never by process step). Any HOW or doc "
                    "instruction left in content is an unverified hypothesis, not a directive. (--plan is the "
                    "deliberate exception: its content is a complete implementation-plan, not an input.)",
                    "Use --icebox for valid future work. Hidden --hold is an exceptional brake for valid work "
                    "awaiting an external gate; neither surface makes unfinished intent valid. "
                    "--group <parent-slug> creates a complete grouped child in one call and makes the parent a structural holder "
                    "via the existing derivation; the first grouped child strips the parent's todo_state "
                    "while preserving all its artifacts as frozen evidence, and is refused once the parent's "
                    "lifecycle_phase has reached prepared or the work lane, so build, review, and finalize "
                    "state is never shredded. Grouping also moves the parent's pending documentation ownership to the first "
                    "grouped child: every in-body marker, companion filename, and delivered_by membership naming the parent "
                    "is rewritten to that child and committed as part of the same transition.",
                    "ALWAYS pass --kind — an agent that authored a todo's scope owns its classification. "
                    "Omitting --kind (kind-less) is reserved for the TUI's direct-primitive dump path, where "
                    "human intent is still unknown and /analyze-todo-input classifies it later. It is NOT a CLI "
                    "shortcut to skip classifying work you understand.",
                    "--plan is valid with --kind change or --kind task.",
                    "Do NOT create a todo for work you can finish yourself in under ~5 minutes — do it inline and stay on it. "
                    "Todos are for substantial, dispatchable work, never a way to defer a small fix you were asked to make now.",
                    "Process changes are decided by humans (software-development/policy/process-change-authority): "
                    "when the intent implies a behavioral delta to a process-layer contract (lifecycle state machines, "
                    "gate composition, review lanes, lifecycle procedures, todo/state semantics), file it only on a "
                    "human decision from the live conversation. Holding no such decision, do NOT file the todo: "
                    "escalate the proposal to the human and go idle. The prepare orchestrator refuses process-change "
                    "intents it cannot trace to a human decision.",
                ],
                auth=CommandAuth(system=_SYS_ALL_PLUS_JOB_RUNNER, human=_HR_MEMBER_CONTRIB),
            ),
            "list": CommandDef(
                desc="List todo entries (source of truth for todo status)",
                args="[--include-icebox] [--icebox-only] [--include-delivered] [--delivered-only] [--include-removed] [--removed-only] [--since <when>] [--json]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_TODO_LIST_INCLUDE_ICEBOX,
                    F.FLAG_TODO_LIST_ICEBOX_ONLY,
                    F.FLAG_TODO_LIST_INCLUDE_DELIVERED,
                    F.FLAG_TODO_LIST_DELIVERED_ONLY,
                    F.FLAG_TODO_LIST_INCLUDE_REMOVED,
                    F.FLAG_TODO_LIST_REMOVED_ONLY,
                    F.FLAG_TODO_LIST_SINCE,
                    F.FLAG_TODO_LIST_JSON,
                ],
                notes=[
                    "Output is sectioned into active/delivered/icebox/removed dependency trees.",
                    "CONTRACT CHANGE: --json now emits a nested object keyed by section "
                    "(active/delivered/icebox/removed), each a tree with `children`; previously a flat "
                    "list. Empty todo list emits `{}`. Text output no longer appends a [status] suffix.",
                    "--include-delivered returns the full delivery history; scope it with --since.",
                    "--since accepts a relative duration (7d, 72h, 2w) or an ISO date/timestamp.",
                    "--since alone implies --include-delivered; combine with --delivered-only to exclude active items.",
                    "--include-removed interleaves soft-removed entries; each removed row renders with its todo id and removed_at age.",
                ],
                examples=[
                    "telec todo list --include-delivered --since 7d",
                    "telec todo list --delivered-only --since 2026-05-01",
                    "telec todo list --include-removed",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "design": CommandDef(
                desc="Run the creative state machine",
                args="[<slug>]",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "co-create": CommandDef(
                desc="Deprecated alias for `telec todo design`",
                args="[<slug>]",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
                hidden=True,
            ),
            "remove": CommandDef(
                desc=(
                    "Soft-remove a todo: the durable record (todo entry + state + all "
                    "artifacts and version history) is retained for a fixed grace window; "
                    "the working resources (worktree + branch + workspace) are released "
                    "immediately. After the window elapses, background maintenance hard-"
                    "purges the row by id. Reactivation is row-id-addressed (see the "
                    "downstream recovery surface) and fail-closed on a live same-slug twin."
                ),
                args="<slug> [--force]",
                flags=[F.FLAG_HELP, F.FLAG_TODO_REMOVE_FORCE],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "freeze": CommandDef(
                desc="Move todo to icebox",
                args="<slug>",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "unfreeze": CommandDef(
                desc="Promote todo from icebox",
                args="<slug>",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "deliver": CommandDef(
                desc="Move todo to delivered",
                args="<slug> [--commit <hash>]",
                flags=[F.FLAG_HELP, F.FLAG_TODO_DELIVER_COMMIT],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "update": CommandDef(
                desc="Update a todo slug, dependencies, or kind",
                args=f"<slug> [--slug <new>] [--after <dep>]... [--schedule <value>] [--kind <{TODO_KIND_USAGE}>] [--hold --reason <text>] [--release] [--unclaim] [--force]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_TODO_UPDATE_SLUG,
                    F.FLAG_TODO_UPDATE_AFTER,
                    F.FLAG_TODO_UPDATE_SCHEDULE,
                    F.FLAG_TODO_UPDATE_KIND,
                    F.FLAG_TODO_UPDATE_HOLD,
                    F.FLAG_TODO_UPDATE_REASON,
                    F.FLAG_TODO_UPDATE_RELEASE,
                    F.FLAG_TODO_UPDATE_UNCLAIM,
                    F.FLAG_TODO_UPDATE_FORCE,
                ],
                notes=[
                    "Mutates slug, deps, kind, or hold; --after replaces the full dependency set.",
                    "Kind and slug changes are refused after build starts; --after remains allowed.",
                    "--hold requires --reason; --reason is refused without --hold, and --hold and --release are mutually exclusive.",
                    "--unclaim clears the caller-owned runner claim; --release only clears the dispatch brake.",
                    "--force only applies to kind orphan handling.",
                    "Combining --slug with other legs is staged, not a single atomic patch.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "prepare": CommandDef(
                desc="Run the Phase A (prepare) state machine",
                args="<slug>",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "work": CommandDef(
                desc="Run the Phase B (work) state machine",
                args="[<slug>]",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "integrate": CommandDef(
                desc="Run the Phase C (integrate) state machine",
                args="[<slug>] [--abandon]",
                flags=[F.FLAG_HELP, F.FLAG_TODO_INTEGRATE_ABANDON],
                auth=CommandAuth(system=_SYS_INTG, human=_HR_MEMBER),
            ),
            "artifacts": CommandDef(
                desc="Manage todo artifacts in the database",
                subcommands={
                    "list": CommandDef(
                        desc="List artifacts for a todo",
                        args="<slug>",
                        flags=[F.FLAG_HELP],
                        examples=["telec todo artifacts list my-slug"],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "read": CommandDef(
                        desc="Read a todo artifact",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings>",
                        flags=[F.FLAG_HELP],
                        examples=["telec todo artifacts read my-slug requirements"],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "write": CommandDef(
                        desc="Write a todo artifact",
                        args="<slug> <name: input|prd|architecture|diagnosis|investigation|implementation-plan|task-plan|quality-checklist|design-spec|deferrals|log|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> <content>",
                        flags=[F.FLAG_HELP],
                        notes=["Legacy bug artifacts are read-only; write bug todo content to input."],
                        examples=['telec todo artifacts write my-slug prd "# PRD content"'],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
                    ),
                    "diff": CommandDef(
                        desc="Show a unified diff between two artifact versions",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> <old-digest> <new-digest>",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Looks up both versions by digest in the artifact version history "
                            "and prints a unified diff between them.",
                            "Used by the prepare loop to show reviewers what changed since the last approved digest.",
                        ],
                        examples=[
                            "telec todo artifacts diff my-slug requirements abc123 def456",
                        ],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "remove": CommandDef(
                        desc="Remove a todo artifact and its version history",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings>",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Refuses input because it is the seed artifact for a todo.",
                            "Missing artifacts are treated as a successful no-op.",
                        ],
                        examples=["telec todo artifacts remove my-slug requirements"],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
                    ),
                },
            ),
            "show": CommandDef(
                desc="Show diagnostic state payload for a todo; artifact bodies are omitted by default",
                args="<slug> [--include-removed] [--include-artifact-content]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_TODO_SHOW_INCLUDE_REMOVED,
                    F.FLAG_TODO_SHOW_INCLUDE_ARTIFACT_CONTENT,
                ],
                examples=[
                    "telec todo show my-slug",
                    "telec todo show my-slug --include-removed",
                    "telec todo show my-slug --include-artifact-content",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "reactivate": CommandDef(
                desc="Restore a soft-removed todo",
                args="<slug> | --id <row-id>",
                flags=[F.FLAG_HELP, F.FLAG_TODO_REACTIVATE_ID],
                notes=[
                    "Resolves the slug against soft-removed rows and restores the uniquely matching entry.",
                    "Use --id after a removed-slug response identifies multiple retained rows.",
                    "On success: status reverts to prev_status and outgoing dependencies are replayed.",
                ],
                examples=["telec todo reactivate my-slug", "telec todo reactivate --id <row-id>"],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "stamp": CommandDef(
                desc="Stamp a verdict or readiness marker into todo state",
                args=(
                    "<slug> [--verdict <v> --phase <p>] [--prd-approved]"
                    " [--task-approved]"
                    " [--architecture-skipped <reason>]"
                    " [--drift-reviewed <artifact> <verdict> <reason>]"
                    f" [--kind-assign <{TODO_KIND_USAGE}> [<content>]]"
                    " [--build-complete] [--finalize-ready]"
                    " [--kickback --reason <reason>]"
                    " [--task-outcome <success|error> [--reason <text>]]"
                    " [--diagnosis-settled] [--diagnosis-unresolved --reason <reason>]"
                ),
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_STAMP_VERDICT,
                    F.FLAG_STAMP_PHASE,
                    F.FLAG_STAMP_PRD_APPROVED,
                    F.FLAG_STAMP_TASK_APPROVED,
                    F.FLAG_STAMP_ARCHITECTURE_SKIPPED,
                    F.FLAG_STAMP_DRIFT_REVIEWED,
                    F.FLAG_STAMP_KIND_ASSIGN,
                    F.FLAG_STAMP_BUILD_COMPLETE,
                    F.FLAG_STAMP_FINALIZE_READY,
                    F.FLAG_STAMP_KICKBACK,
                    F.FLAG_STAMP_REASON,
                    F.FLAG_STAMP_TASK_OUTCOME,
                    F.FLAG_STAMP_DIAGNOSIS_SETTLED,
                    F.FLAG_STAMP_DIAGNOSIS_UNRESOLVED,
                    F.FLAG_STAMP_REQUIREMENTS_READY,
                    F.FLAG_STAMP_PLAN_READY,
                    F.FLAG_STAMP_DEFERRALS_PROCESSED,
                    F.FLAG_STAMP_DESIGN_SPEC_CONFIRMED,
                    F.FLAG_STAMP_ART_APPROVED,
                    F.FLAG_STAMP_VISUALS_APPROVED,
                    F.FLAG_STAMP_BUILD_STARTED,
                ],
                examples=[
                    "telec todo stamp my-slug --verdict approve --phase plan_review",
                    "telec todo stamp my-task --task-approved",
                    'telec todo stamp my-slug --kind-assign task "actionable task"',
                    "telec todo stamp my-slug --verdict changes_requested --phase build_review",
                    "telec todo stamp my-slug --finalize-ready",
                    'telec todo stamp my-slug --kickback --reason "<why the plan cannot be built>"',
                    "telec todo stamp my-task --task-outcome success",
                    'telec todo stamp my-task --task-outcome error --reason "<why a human is needed>"',
                    "telec todo stamp my-bug --diagnosis-settled",
                    'telec todo stamp my-bug --diagnosis-unresolved --reason "<why>"',
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "bugs": CommandDef(
        desc="Bug reporting and tracking",
        subcommands={
            "report": CommandDef(
                desc=(
                    "Interrogate the pre-filing decisions before scaffolding a bug; a completed filing "
                    "enters the bug lane and the lifecycle router dispatches /next-prepare"
                ),
                args="<description> [--slug <slug>] [--body <text>] [--project <name>] [--human-involved <reason>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_BUG_APPROVED,
                    F.FLAG_BUG_SLUG,
                    F.FLAG_BUG_BODY,
                    F.FLAG_BUG_PROJECT,
                    F.FLAG_HUMAN_INVOLVED,
                ],
                notes=[
                    "An invocation carrying only the report payload does not file: it presents the required "
                    "pre-filing decisions (fix-directly, duplication, ordering, validity and ownership) and "
                    "only that output names how to complete the filing.",
                    "File against the project that OWNS the defective code, not the one you happen to be "
                    "standing in. Platform behavior misbehaving inside a side project is a platform bug: "
                    "pass --project so the orchestrator that picks it up can actually deliver the fix. A bug "
                    "filed where the code does not live cannot be fixed there and gets re-filed later, "
                    "carrying stale conclusions with it. When you cannot tell which project owns it, ask.",
                    "The filing surface interrogates for duplication up front (todo list, in-flight bug lanes, "
                    "suppressions); diagnose remains the deeper same-defect dedup that can still retire a twin "
                    "the up-front check missed.",
                    "Your reported todo may therefore still be removed as a duplicate at diagnose — that is expected dedup, not a dropped report. The surviving todo carries the fix; do not re-report the same bug.",
                    "Report the OBSERVED wrong behavior, never a missing capability or a solution ('X has no way to do Y' "
                    "is a fix wearing a symptom's clothes). A bug fix stays within the existing process contract "
                    "(software-development/policy/process-change-authority): when the defect seems to demand a behavioral "
                    "delta to a process-layer contract (lifecycle state machines, gate composition, review lanes, "
                    "lifecycle procedures), do NOT file it as a bug — escalate the process proposal to the human instead.",
                    "Require the observed symptom plus its trigger context verbatim in the description or --body: "
                    "what happened, what was expected, and what preceded it. A report with no trigger context is "
                    "unauditable later — this is the reporting invitation the schema alone cannot supply.",
                ],
                auth=CommandAuth(system=_SYS_ALL_PLUS_JOB_RUNNER, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "list": CommandDef(
                desc="List in-flight bug fixes with status",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "suppress": CommandDef(
                desc="Register a known-issue suppression so the log bug hunter stops re-filing a triaged signal",
                args='"<pattern>" --reason <r> [--match substring|regex] [--disposition expected|wontfix] [--project <name>] [--source-bug <slug>] [--expires <when>]',
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_SUPPRESS_REASON,
                    F.FLAG_SUPPRESS_MATCH,
                    F.FLAG_SUPPRESS_DISPOSITION,
                    F.FLAG_PROJECT_TRUSTED,
                    F.FLAG_SUPPRESS_SOURCE_BUG,
                    F.FLAG_SUPPRESS_EXPIRES,
                ],
                notes=[
                    "The ledger is the log bug hunter's allowlist: a matched candidate error line is treated as already triaged and does not dispatch a session.",
                    "Matching is literal (substring) or a compiled regex; a regex pattern is validated here and rejected if it does not compile.",
                    "Author the pattern to target the invariant signal (a stable reason token), never a volatile value like a millisecond figure.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "suppressions": CommandDef(
                desc="List the active known-issue suppressions for a project",
                args="[--project <name>]",
                flags=[F.FLAG_HELP, F.FLAG_PROJECT_TRUSTED],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "unsuppress": CommandDef(
                desc="Remove a known-issue suppression by id so its signal is eligible for filing again",
                args="<id> [--project <name>]",
                flags=[F.FLAG_HELP, F.FLAG_PROJECT_TRUSTED],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "content": CommandDef(
        desc="Manage content pipeline",
        subcommands={
            "dump": CommandDef(
                desc="Fire-and-forget content dump to publications inbox",
                args="<description-or-text> [--slug <slug>] [--tags <tags>] [--author <name>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_CONTENT_SLUG,
                    F.FLAG_CONTENT_TAGS,
                    F.FLAG_CONTENT_AUTHOR,
                ],
                notes=[
                    "Creates publications/inbox/YYYYMMDD-<slug>/ with content.md and meta.yaml.",
                    "Author defaults to terminal auth identity (telec auth whoami) or 'unknown'.",
                    "Emits a content.dumped notification event if the notification service is available.",
                    "Slug collision is handled automatically by appending a counter suffix.",
                ],
                examples=[
                    'telec content dump "My brain dump about agent shorthand"',
                    'telec content dump "Deep dive into mesh" --slug mesh-deep-dive --tags "mesh,architecture"',
                    'telec content dump "Content for review" --author alice',
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "jobs": CommandDef(
        desc="Recurring job commands",
        subcommands={
            "report": CommandDef(
                desc="Write a structured recurring job result record",
                args="<job_id> --success <true|false> --message <text> [--items-processed <n>] [--error <text> ...]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_JOB_SUCCESS,
                    F.FLAG_JOB_MESSAGE,
                    F.FLAG_JOB_ITEMS_PROCESSED,
                    F.FLAG_JOB_ERROR,
                ],
                notes=[
                    "job_id is the job's identity: an agent job's procedure snippet ID, or a script job's declared name. Validated against configured jobs; writes JSON under ~/.teleclaude/jobs/{job_id}/runs/.",
                    "This command writes locally and does not call the daemon.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "events": CommandDef(
        desc="Event catalog and platform commands",
        subcommands={
            "list": CommandDef(
                desc="List event schemas: type, level, domain, visibility, description, actionable",
                args="[--domain <name>]",
                flags=[F.FLAG_HELP, F.FLAG_EVENTS_DOMAIN],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
        },
    ),
    "signals": CommandDef(
        desc="Signal pipeline status and diagnostics",
        subcommands={
            "status": CommandDef(
                desc="Show signal pipeline counts and last ingest time",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
        },
    ),
    "mcp": CommandDef(
        desc="Use configured MCP servers through TeleClaude lazy runtime",
        subcommands={
            "list": CommandDef(
                desc="List configured MCP servers without starting them",
                args="[--exclude <slug>] [--json]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MCP_EXCLUDE,
                    F.FLAG_MCP_JSON,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "list-tools": CommandDef(
                desc="Initialize one MCP server and list its tools",
                args="<slug> [--json]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MCP_JSON,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "call": CommandDef(
                desc="Call one MCP tool through the lazy runtime",
                args="<slug> <tool> --json <arguments-json>",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MCP_CALL_JSON,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
        },
        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
    ),
    "auth": CommandDef(
        desc="Terminal login identity commands",
        subcommands={
            "login": CommandDef(
                desc="Set terminal login identity for this TTY",
                args="<email>",
                flags=[F.FLAG_HELP],
                notes=[
                    "Stores auth state in a TTY-scoped file.",
                    "Running login again on the same TTY overwrites the existing file.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "whoami": CommandDef(
                desc="Show terminal login identity for this TTY",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "logout": CommandDef(
                desc="Clear terminal login identity for this TTY",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
        },
    ),
    "config": CommandDef(
        desc="Manage configuration",
        subcommands={
            "wizard": CommandDef(
                desc="Open the interactive configuration wizard",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=frozenset(), human=_HR_ADMIN),
                hidden=True,
            ),
            "get": CommandDef(
                desc="Get config values",
                args="[paths...] [--format <fmt>]",
                flags=[F.FLAG_HELP, F.FLAG_CONFIG_FORMAT],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "patch": CommandDef(
                desc="Patch config values",
                args="[--yaml '...'] [--from-file <path>] [--format <fmt>]",
                flags=[F.FLAG_HELP, F.FLAG_CONFIG_YAML, F.FLAG_CONFIG_FROM_FILE, F.FLAG_CONFIG_FORMAT],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
            ),
            "validate": CommandDef(
                desc="Full validation",
                flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "people": CommandDef(
                desc="Manage people",
                subcommands={
                    "list": CommandDef(
                        desc="List people",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "show": CommandDef(
                        desc="Show a person's organizational memberships",
                        args="<name> [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "add": CommandDef(
                        desc="Add a person",
                        args=(
                            "<name> --email <email> --role <role>"
                            " [--expertise '<json>']"
                            " [--telegram-user <user>] [--telegram-id <id>]"
                            " [--no-invite] [--json]"
                        ),
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_PEOPLE_EMAIL,
                            F.FLAG_PEOPLE_ROLE,
                            F.FLAG_PEOPLE_USERNAME,
                            F.FLAG_PEOPLE_EXPERTISE,
                            F.FLAG_PEOPLE_TELEGRAM_USER,
                            F.FLAG_PEOPLE_TELEGRAM_ID,
                            F.FLAG_PEOPLE_NO_INVITE,
                            F.FLAG_PEOPLE_NAME_ALIAS,
                            F.FLAG_JSON_MACHINE_READABLE,
                        ],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "edit": CommandDef(
                        desc="Edit a person",
                        args=(
                            "<name> [--email <email>] [--role <role>]"
                            " [--company <slug>] [--company-role <admin|member>]"
                            " [--remove-company <slug>] [--assign <project-slug>]... [--unassign <project-slug>]..."
                            " [--expertise '<json>']"
                            " [--telegram-user <user>] [--telegram-id <id>]"
                            " [--discord-voice-bot] [--json]"
                        ),
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_PEOPLE_EMAIL,
                            F.FLAG_PEOPLE_ROLE,
                            F.FLAG_PEOPLE_COMPANY,
                            F.FLAG_PEOPLE_COMPANY_ROLE,
                            F.FLAG_PEOPLE_REMOVE_COMPANY,
                            F.FLAG_PEOPLE_ASSIGN,
                            F.FLAG_PEOPLE_UNASSIGN,
                            F.FLAG_PEOPLE_USERNAME,
                            F.FLAG_PEOPLE_EXPERTISE,
                            F.FLAG_PEOPLE_TELEGRAM_USER,
                            F.FLAG_PEOPLE_TELEGRAM_ID,
                            F.FLAG_PEOPLE_DISCORD_VOICE_BOT,
                            F.FLAG_JSON_MACHINE_READABLE,
                        ],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "remove": CommandDef(
                        desc="Remove a person",
                        args="<name> [--delete-dir] [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_PEOPLE_DELETE_DIR, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "invite": CommandDef(
                        desc="Generate invite links for a person",
                        args="<name> [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                },
                notes=[
                    (
                        "To edit people's subscriptions, modify the person config: "
                        "~/.teleclaude/people/{name}/teleclaude.yml"
                    ),
                    (
                        '--expertise JSON shape: {"<domain>": "<level>", "<domain>": '
                        '{"<sub-area>": "<level>"}}. '
                        "Levels: novice, intermediate, advanced, expert. "
                        'Example: \'{"python": "expert", "typescript": '
                        '{"backend": "advanced", "frontend": "intermediate"}}\''
                    ),
                ],
            ),
            "env": CommandDef(
                desc="Manage environment variables",
                subcommands={
                    "list": CommandDef(
                        desc="List environment variables",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "set": CommandDef(
                        desc="Set environment variables",
                        args="<KEY=VALUE> ... [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                },
            ),
            "notify": CommandDef(
                desc="Toggle notification settings",
                flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "tts": CommandDef(
                desc="Manage TTS dependency provisioning",
                subcommands={
                    "deprovision": CommandDef(
                        desc="Disable TTS and remove the TTS-exclusive optional dependencies",
                        args="[--yes]",
                        flags=[F.FLAG_HELP, F.FLAG_TTS_YES],
                        notes=[
                            "Disables TTS, removes the TTS-exclusive deps (elevenlabs, the mlx text "
                            "pipeline), and leaves deps shared with STT/summarization installed.",
                            "Bare invocation prints this guard and makes no daemon call.",
                            "Re-enabling TTS afterward lazily re-provisions the removed deps.",
                        ],
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                },
            ),
        },
    ),
    "history": CommandDef(
        desc="Search and view agent session history",
        subcommands={
            "search": CommandDef(
                desc="Search agent session transcripts",
                args="[terms...] [--agent <name>] [--computer <host>] [--identity <value>] [--project <path>] [--limit <n>] [--include-workers] [--json]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_HISTORY_AGENT,
                    F.FLAG_COMPUTER_MANY,
                    F.FLAG_HISTORY_LIMIT,
                    F.FLAG_HISTORY_INCLUDE_WORKERS,
                    F.FLAG_HISTORY_IDENTITY,
                    F.FLAG_PROJECT_FILTER,
                    F.FLAG_HISTORY_JSON,
                ],
                examples=[
                    "telec history search config wizard",
                    "telec history search --agent claude,codex bug fix",
                    "telec history search --include-workers tui",
                ],
                literal_dash_tokens=True,
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "show": CommandDef(
                desc="Show full transcript for a session",
                args="<session-id> [--agent <name>] [--computer <host>] [--thinking] [--raw] [--json]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_HISTORY_SHOW_AGENT,
                    F.FLAG_COMPUTER_MANY,
                    F.FLAG_THINKING,
                    F.FLAG_HISTORY_RAW,
                    F.FLAG_HISTORY_JSON,
                ],
                examples=[
                    "telec history show 00000000-0000-4000-8000-000000000000",
                    "telec history show 00000000-0000-4000-8000-000000000000 --agent claude",
                    "telec history show 00000000-0000-4000-8000-000000000000 --thinking",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
        },
    ),
    "memories": CommandDef(
        desc=(
            "Read or remove durable personal-preference observations about the human. "
            "Memories capture meta-level things about who the human is — their relational stance, "
            "values, communication style, vision — never coding norms, architectural decisions, "
            "or operational gotchas (those live in policies, principles, and addenda). "
            "Memories are written exclusively by the session memory extraction agent (the memory "
            "scraper, invoked via /extract-memory); other agents must never create them."
        ),
        subcommands={
            "list": CommandDef(
                desc="List personal-preference observations about the human.",
                args="[--limit <n>] [--type <type>] [--project <name>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_LIMIT,
                    F.FLAG_MEMORIES_TYPE,
                    F.FLAG_PROJECT_FILTER,
                ],
                examples=[
                    "telec memories list",
                    "telec memories list --type preference",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "search": CommandDef(
                desc="Search personal-preference observations about the human.",
                args="<query> [--limit <n>] [--type <type>] [--project <name>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_LIMIT_20,
                    F.FLAG_MEMORIES_TYPE,
                    F.FLAG_PROJECT_FILTER,
                ],
                examples=[
                    'telec memories search "communication style"',
                    'telec memories search "narrative" --type preference',
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "save": CommandDef(
                desc=(
                    "Persist a memory observation. Reserved for the session memory extraction "
                    "agent (the memory scraper, invoked via /extract-memory). Other agents must "
                    "never call this."
                ),
                args="<text> [--title <title>] [--type <type>] [--project <name>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_SAVE_TITLE,
                    F.FLAG_MEMORIES_SAVE_TYPE,
                    F.FLAG_MEMORIES_SAVE_PROJECT,
                ],
                examples=[],
                hidden=True,
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "delete": CommandDef(
                desc="Delete a personal-preference observation by ID (typically run by the human while pruning).",
                args="<id>",
                flags=[F.FLAG_HELP],
                examples=["telec memories delete 42"],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "timeline": CommandDef(
                desc="Show personal-preference observations around an anchor ID.",
                args="<id> [--before <n>] [--after <n>] [--project <name>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_BEFORE,
                    F.FLAG_MEMORIES_AFTER,
                    F.FLAG_PROJECT_FILTER,
                ],
                examples=["telec memories timeline 42 --before 3 --after 3"],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "code": CommandDef(
        desc="Code quality and commit tools",
        notes=[
            "lint, test, format, install, blueprint, and owners require the code capability.",
            "add and commit remain available when either code or docs is subscribed.",
        ],
        subcommands={
            "blueprint": CommandDef(
                desc="Query the codebase Blueprint (structural blast-radius)",
                subcommands={
                    "affected": CommandDef(
                        desc="Print the blast-radius dependents of changed files",
                        args="<changed-files>",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Maps each changed file to its symbols, runs a transitive reverse "
                            "dependency traversal over the Blueprint, and prints the union of "
                            "dependents with file:line.",
                            "When the Blueprint is missing or stale (manifest baseline != current "
                            "main), prints a fallback notice and exits 0 — fall back to manual "
                            "exploration; blast-radius is never silently skipped.",
                        ],
                        examples=[
                            "telec code blueprint affected teleclaude/core/foo.py teleclaude/api/bar.py",
                        ],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
                    ),
                },
            ),
            "lint": CommandDef(
                desc="Run native make lint plus TeleClaude guardrails",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_CODE_ALL_LINT,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "test": CommandDef(
                desc="Run native make test",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_CODE_ALL_TEST,
                    F.FLAG_CODE_UPDATE_SNAPSHOTS,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "format": CommandDef(
                desc="Run native make format",
                flags=[F.FLAG_HELP, F.FLAG_CODE_ALL_FORMAT],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "install": CommandDef(
                desc="Run native make install",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "owners": CommandDef(
                desc="Resolve live-session ownership for supplied dirty paths",
                args="<path> [<path> ...]",
                flags=[F.FLAG_HELP],
                notes=[
                    "Accepts the complete already-aged dirty blocking set; the command performs no age logic.",
                    "Prints one path-keyed JSON object; each value is the list of every live session that "
                    "declared that path (no tiebreak), or null when no live session declared it.",
                ],
                auth=CommandAuth(system=_SYS_INTG, human=_HR_MEMBER),
            ),
            "add": CommandDef(
                desc="Declare files for the next commit (stages NEW, unmerged, or partial-staged tracked)",
                args="<path> [<path> ...]",
                flags=[F.FLAG_HELP],
                notes=[
                    "Sealed equivalent of 'git add' for the three cases git's data model genuinely requires staging:",
                    "  (1) NEW (untracked) files — must enter the index before commit pathspec can match.",
                    "  (2) Unmerged-index files (post-conflict) — must be marked resolved before commit.",
                    "  (3) Partial-staged tracked files (staged hunks + later working-tree delta) — "
                    "must be fully (re)staged so the pathspec commit does not silently sweep in "
                    "unstaged hunks. The partial-staging guard in `telec code commit` directs agents "
                    "here for recovery.",
                    "Every successful call declares its paths to session-scoping. Modified-tracked files "
                    "that are NOT partial-staged don't need staging — pathspec commits them straight from "
                    "the working tree.",
                    "A clean tracked path or a path that does not exist yet is declared the same way — "
                    "declaring is bookkeeping for work about to start, not a claim about current git "
                    "state, so declaring ahead of the first touch always succeeds.",
                    "NEW files in scope are NOT auto-committed; this is the explicit declaration step. "
                    "Without it, untracked files stay untracked (safety net for temp/scratch artifacts "
                    "the agent may have created incidentally).",
                    "Alternative one-shot form: telec code commit --approved '<msg>' --include <path>.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "commit": CommandDef(
                desc="Commit workspace-scoped changes via a pathspec-scoped commit (sealed; no git forwarding)",
                args='"<message>" [--approved] [--human-involved <reason>] [--include <path> ...] [--only <path> ...]',
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_COMMIT_APPROVED,
                    F.FLAG_COMMIT_INCLUDE,
                    F.FLAG_COMMIT_ONLY,
                    F.FLAG_HUMAN_INVOLVED_COMMIT,
                ],
                notes=[
                    "Accepts only: one quoted message, --approved, --human-involved <reason>, --include <path> ..., and --only <path> ... .",
                    "Modified-tracked files in scope are auto-committed via pathspec straight from the working tree — no staging needed.",
                    "NEW (untracked) files in scope are NOT auto-committed by default; declare them via `telec code add`, `--include`, or `--only` (safety net against incidental temp/scratch artifacts).",
                    "--only commits exactly the declared paths and is mutually exclusive with --include.",
                    "Unmerged-index files in pathspec are staged internally for the integrator conflict path.",
                    "Without --approved on main: prints commit-first and review-routing guidance and exits.",
                    "Pathspec = workspace scope plus --include paths, or exactly --only paths. Anything else in the index (foreign stage) is left untouched — there is no env-var bypass.",
                    "The commit author is stamped as the resolved agent's bot identity (git --author); the message gains the branding line, Session:, and Human-Involved: — no Co-Authored-By trailer is ever added.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "pre-commit": CommandDef(
                desc="Run the thin pre-commit backstop",
                flags=[F.FLAG_HELP],
                hidden=True,
            ),
            "post-commit": CommandDef(
                desc="Run deterministic post-commit maintenance",
                flags=[F.FLAG_HELP],
                hidden=True,
            ),
            "post-merge": CommandDef(
                desc="Run deterministic post-merge automation",
                flags=[F.FLAG_HELP],
                hidden=True,
            ),
        },
    ),
}
HELP_SUBCOMMAND_EXPANSIONS: dict[str, dict[str, list[tuple[str, str]]]] = {}

# =============================================================================
# Leaf-node constants — the object a handler parses, resolved by lookup so a
# renamed or removed CLI_SURFACE key fails at import instead of a path
# literal silently resolving to nothing.
# =============================================================================

HISTORY_SEARCH = CLI_SURFACE["history"].subcommands["search"]
HISTORY_SHOW = CLI_SURFACE["history"].subcommands["show"]

SESSIONS_LIST = CLI_SURFACE["sessions"].subcommands["list"]
SESSIONS_START = CLI_SURFACE["sessions"].subcommands["start"]
SESSIONS_SEND = CLI_SURFACE["sessions"].subcommands["send"]
SESSIONS_TAIL = CLI_SURFACE["sessions"].subcommands["tail"]
SESSIONS_RUN = CLI_SURFACE["sessions"].subcommands["run"]
SESSIONS_REVIVE = CLI_SURFACE["sessions"].subcommands["revive"]
SESSIONS_END = CLI_SURFACE["sessions"].subcommands["end"]
SESSIONS_UNSUBSCRIBE = CLI_SURFACE["sessions"].subcommands["unsubscribe"]
SESSIONS_RESTART = CLI_SURFACE["sessions"].subcommands["restart"]
SESSIONS_RESULT = CLI_SURFACE["sessions"].subcommands["result"]
SESSIONS_FILE = CLI_SURFACE["sessions"].subcommands["file"]
SESSIONS_ESCALATE = CLI_SURFACE["sessions"].subcommands["escalate"]

PROJECTS_LIST = CLI_SURFACE["projects"].subcommands["list"]
AGENTS_STATUS = CLI_SURFACE["agents"].subcommands["status"]
CHANNELS_LIST = CLI_SURFACE["channels"].subcommands["list"]
CHANNELS_PUBLISH = CLI_SURFACE["channels"].subcommands["publish"]

JOBS_REPORT = CLI_SURFACE["jobs"].subcommands["report"]

REMINDERS_SET = CLI_SURFACE["reminders"].subcommands["set"]
REMINDERS_CANCEL = CLI_SURFACE["reminders"].subcommands["cancel"]

TODO_WORK = CLI_SURFACE["todo"].subcommands["work"]
TODO_PREPARE = CLI_SURFACE["todo"].subcommands["prepare"]
TODO_INTEGRATE = CLI_SURFACE["todo"].subcommands["integrate"]
TODO_DESIGN = CLI_SURFACE["todo"].subcommands["design"]
OPERATIONS_GET = CLI_SURFACE["operations"].subcommands["get"]
TODO_CREATE = CLI_SURFACE["todo"].subcommands["create"]
TODO_DELIVER = CLI_SURFACE["todo"].subcommands["deliver"]
TODO_REMOVE = CLI_SURFACE["todo"].subcommands["remove"]
TODO_STAMP = CLI_SURFACE["todo"].subcommands["stamp"]
TODO_REACTIVATE = CLI_SURFACE["todo"].subcommands["reactivate"]
TODO_LIST = CLI_SURFACE["todo"].subcommands["list"]
TODO_UPDATE = CLI_SURFACE["todo"].subcommands["update"]
TODO_SHOW = CLI_SURFACE["todo"].subcommands["show"]

BUGS_REPORT = CLI_SURFACE["bugs"].subcommands["report"]
BUGS_LIST = CLI_SURFACE["bugs"].subcommands["list"]
BUGS_SUPPRESS = CLI_SURFACE["bugs"].subcommands["suppress"]
BUGS_SUPPRESSIONS = CLI_SURFACE["bugs"].subcommands["suppressions"]
BUGS_UNSUPPRESS = CLI_SURFACE["bugs"].subcommands["unsuppress"]

SYNC = CLI_SURFACE["sync"]

DOCS_INDEX = CLI_SURFACE["docs"].subcommands["index"]
DOCS_GET = CLI_SURFACE["docs"].subcommands["get"]

MEMORIES_LIST = CLI_SURFACE["memories"].subcommands["list"]
MEMORIES_SEARCH = CLI_SURFACE["memories"].subcommands["search"]
MEMORIES_SAVE = CLI_SURFACE["memories"].subcommands["save"]
MEMORIES_DELETE = CLI_SURFACE["memories"].subcommands["delete"]
MEMORIES_TIMELINE = CLI_SURFACE["memories"].subcommands["timeline"]

MESSAGE = CLI_SURFACE["message"]

CONTENT_DUMP = CLI_SURFACE["content"].subcommands["dump"]

EVENTS_LIST = CLI_SURFACE["events"].subcommands["list"]

MCP_LIST = CLI_SURFACE["mcp"].subcommands["list"]
MCP_LIST_TOOLS = CLI_SURFACE["mcp"].subcommands["list-tools"]
MCP_CALL = CLI_SURFACE["mcp"].subcommands["call"]

COMPANIES_ONBOARD = CLI_SURFACE["companies"].subcommands["onboard"]

CODE_BLUEPRINT_AFFECTED = CLI_SURFACE["code"].subcommands["blueprint"].subcommands["affected"]
CODE_LINT = CLI_SURFACE["code"].subcommands["lint"]
CODE_TEST = CLI_SURFACE["code"].subcommands["test"]
CODE_FORMAT = CLI_SURFACE["code"].subcommands["format"]
CODE_INSTALL = CLI_SURFACE["code"].subcommands["install"]
CODE_OWNERS = CLI_SURFACE["code"].subcommands["owners"]
CODE_ADD = CLI_SURFACE["code"].subcommands["add"]
CODE_COMMIT = CLI_SURFACE["code"].subcommands["commit"]

CONFIG_TTS_DEPROVISION = CLI_SURFACE["config"].subcommands["tts"].subcommands["deprovision"]
CONFIG_GET = CLI_SURFACE["config"].subcommands["get"]
CONFIG_PATCH = CLI_SURFACE["config"].subcommands["patch"]
CONFIG_VALIDATE = CLI_SURFACE["config"].subcommands["validate"]
CONFIG_NOTIFY = CLI_SURFACE["config"].subcommands["notify"]
CONFIG_PEOPLE_LIST = CLI_SURFACE["config"].subcommands["people"].subcommands["list"]
CONFIG_PEOPLE_SHOW = CLI_SURFACE["config"].subcommands["people"].subcommands["show"]
CONFIG_PEOPLE_ADD = CLI_SURFACE["config"].subcommands["people"].subcommands["add"]
CONFIG_PEOPLE_EDIT = CLI_SURFACE["config"].subcommands["people"].subcommands["edit"]
CONFIG_PEOPLE_REMOVE = CLI_SURFACE["config"].subcommands["people"].subcommands["remove"]
CONFIG_PEOPLE_INVITE = CLI_SURFACE["config"].subcommands["people"].subcommands["invite"]
CONFIG_ENV_LIST = CLI_SURFACE["config"].subcommands["env"].subcommands["list"]
CONFIG_ENV_SET = CLI_SURFACE["config"].subcommands["env"].subcommands["set"]

"""CLI surface — CLI_SURFACE dict and HELP_SUBCOMMAND_EXPANSIONS."""

from __future__ import annotations

from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.snippet_validation import SnippetScope
from teleclaude.types.todo_kind import TODO_KIND_USAGE

_SCOPE_VALUES = "|".join(member.value for member in SnippetScope)

from .surface_types import (
    _FLAG_AFTER_DEPS,
    _FLAG_AGENT,
    _FLAG_COMPUTER,
    _FLAG_DETACH,
    _FLAG_LIMIT_20,
    _FLAG_MODE,
    _FLAG_PATH,
    _FLAG_PROJECT_FILTER,
    _FLAG_PROJECT_TRUSTED,
    _FLAG_SESSION,
    _FLAG_THINKING,
    _H,
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
                    _H,
                    Flag("--all", desc="Show all sessions"),
                    Flag("--closed", desc="Include closed sessions"),
                    Flag("--job", desc="Filter by job value"),
                    Flag("--computer", desc="Filter to a specific computer"),
                ],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "start": CommandDef(
                desc="Start a new agent session",
                args=(
                    "[--computer <host>] [--path <path>] [--agent <name>] [--mode <mode>]"
                    " [--message <msg>] [--direct] [--detach]"
                ),
                flags=[
                    _H,
                    _FLAG_COMPUTER,
                    _FLAG_PATH,
                    _FLAG_AGENT,
                    _FLAG_MODE,
                    Flag("--message", desc="Initial message to send"),
                    Flag("--direct", desc="Conversation mode: create direct link with caller and bypass listeners"),
                    _FLAG_DETACH,
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
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "send": CommandDef(
                desc="Send a message to a running session",
                args="<session_id> [<message>] [--direct] [--close-link]",
                flags=[
                    _H,
                    Flag("--direct", desc="Conversation mode: create shared direct link"),
                    Flag("--close-link", desc="Close direct link with target session (alias: --close_link)"),
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
                args="<session_id> [--since <ts>] [--tools] [--thinking] [--full]",
                flags=[
                    _H,
                    _FLAG_SESSION,
                    Flag("--since", desc="ISO8601 timestamp filter"),
                    Flag("--tools", desc="Include tool use entries"),
                    _FLAG_THINKING,
                    Flag("--full", desc="Show all projected messages instead of the latest user turn"),
                ],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "run": CommandDef(
                desc="Run a slash command on a new agent session",
                args=(
                    "[--command <cmd>] [--path <path>] [--args <val>] [--agent <name>]"
                    " [--mode <mode>] [--computer <host>] [--subfolder <dir>] [--detach]"
                    " [--additional-context <ctx>]"
                ),
                flags=[
                    _H,
                    Flag("--command", desc="Slash command (e.g. /next-build)"),
                    _FLAG_PATH,
                    Flag("--args", desc="Command arguments"),
                    _FLAG_AGENT,
                    _FLAG_MODE,
                    _FLAG_COMPUTER,
                    Flag("--subfolder", desc="Subdirectory within the project"),
                    _FLAG_DETACH,
                    Flag("--additional-context", desc="Additional context for the worker, appended to startup message"),
                ],
                notes=[
                    "Creates a fresh session and runs the slash command as the first agent message.",
                    "Worker lifecycle commands: /next-build, /next-review-build, /next-fix-review, /next-finalize.",
                    (
                        "--detach: do not use unless explicitly instructed. Sanctioned only for a "
                        "personal-assistant dispatching an orchestrator to a project. --detach disables "
                        "notifications — you will not learn when the child finishes, so omit it whenever "
                        "your next step depends on the result."
                    ),
                ],
                examples=[
                    "telec sessions run --command /next-build --args my-slug",
                ],
                auth=CommandAuth(system=_SYS_ORCH_TASKER, human=_HR_MEMBER),
            ),
            "revive": CommandDef(
                desc="Revive session by TeleClaude session ID",
                args="<session_id>",
                flags=[
                    _H,
                    Flag("--agent", desc="Treat session_id as native agent session ID for the given agent"),
                    Flag("--attach", desc="Attach to tmux session after revive"),
                    Flag("--computer", desc="Target computer"),
                ],
                notes=[
                    (
                        "Restarts an ended session's agent with the full prior transcript, "
                        "so the agent resumes with its original context intact."
                    ),
                    "Without --agent, session_id is a TeleClaude session ID.",
                    "With --agent, session_id is a native agent session ID resolved via the specified agent.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
            ),
            "end": CommandDef(
                desc="End (terminate) a session ('self' to end own session)",
                args="<session_id> [--computer <host>]",
                flags=[
                    _H,
                    _FLAG_SESSION,
                    _FLAG_COMPUTER,
                ],
                auth=CommandAuth(system=_SYS_ORCH | _SYS_INTG, human=_HR_MEMBER),
            ),
            "unsubscribe": CommandDef(
                desc="Stop receiving notifications from a session",
                args="<session_id>",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
            "restart": CommandDef(
                desc="Restart an agent session ('self' to restart own session)",
                args="<session_id>",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ADMIN),
            ),
            "result": CommandDef(
                desc="Send a formatted result to the session's user",
                args="<content> [--format <fmt>]",
                flags=[_H, Flag("--format", desc="Output format: markdown, html")],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB),
            ),
            "file": CommandDef(
                desc="Send a file to the session's user",
                args="[--path <path>] [--filename <name>] [--caption <text>]",
                flags=[
                    _H,
                    Flag("--path", desc="File path on the daemon host"),
                    Flag("--filename", desc="Display filename"),
                    Flag("--caption", desc="Optional caption"),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "widget": CommandDef(
                desc="Render a rich widget to the session's user",
                args="[--data <json>]",
                flags=[_H, Flag("--data", desc="Widget expression as JSON")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "escalate": CommandDef(
                desc="Escalate to an admin via Discord",
                args="[--customer <name>] [--reason <text>] [--summary <text>]",
                flags=[
                    _H,
                    Flag("--customer", desc="Customer name"),
                    Flag("--reason", desc="Reason for escalation"),
                    Flag("--summary", desc="Context summary for the admin"),
                ],
                auth=CommandAuth(
                    system=_SYS_ALL | _SYS_INTG,
                    human=_HR_ALL_NON_ADMIN,
                ),
            ),
        },
    ),
    "computers": CommandDef(
        desc="Manage computer inventory",
        subcommands={
            "list": CommandDef(
                desc="List available computers (local + cached remote)",
                flags=[_H],
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
                flags=[_H, Flag("--computer", "-c", "Filter to a specific computer")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "init": CommandDef(
                desc="Initialize project plumbing and sync artifacts",
                flags=[_H],
                notes=[
                    "Sets up git hooks, syncs artifacts, and registers the project root.",
                    "AI-driven analysis lives in `telec projects {onboard,analyze,assess}`.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "onboard": CommandDef(
                desc="Full project bootstrap: init plumbing, then dispatch config assessment and doc-snippet analysis",
                flags=[_H],
                notes=[
                    "Runs `telec projects init` synchronously, then dispatches `telec projects assess` and `telec projects analyze`.",
                    "AI sessions run concurrently in tmux after dispatch — monitor via `telec sessions list` according to heartbeat policy.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "analyze": CommandDef(
                desc="Generate project doc snippets via AI analysis",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "assess": CommandDef(
                desc="Assess project quality tool configuration against blessed templates",
                flags=[_H],
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
                flags=[_H, Flag("--slug", desc="Company slug (optional; derived from the name when omitted)")],
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
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "status": CommandDef(
                desc="Set dispatch status for a specific agent",
                args="<agent> [--status <val>] [--reason <text>] [--until <ts>] [--clear]",
                flags=[
                    _H,
                    Flag("--status", desc="Status: available, unavailable, degraded"),
                    Flag("--reason", desc="Reason for status change"),
                    Flag("--until", desc="ISO8601 UTC expiry for unavailable"),
                    Flag("--clear", desc="Reset to available immediately"),
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
                flags=[_H, _FLAG_PROJECT_FILTER],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
            "publish": CommandDef(
                desc="Publish a message to a channel",
                args="<channel> [--data <json>]",
                flags=[_H, Flag("--data", desc="JSON payload to publish")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
        },
    ),
    "operations": CommandDef(
        desc="Inspect durable long-running operations",
        subcommands={
            "get": CommandDef(
                desc="Fetch durable operation status by operation_id",
                args="<operation_id>",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER),
            ),
        },
    ),
    "version": CommandDef(
        desc="Print version, channel, and commit",
        auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
    ),
    "sync": CommandDef(
        desc="Validate doc/snippet/artifact sources (blocks on findings) and apply your edits",
        args="[--skip-deploy]",
        flags=[
            _H,
            Flag("--skip-deploy", desc="Validate only; do not build or deploy (read-only gate)"),
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
            _H,
            Flag("--file", desc="Path to a single file to attach (Telegram, Discord, email only)"),
            Flag("--subject", desc="Email subject line; ignored on channels without a subject concept"),
            Flag("--channel", desc="Override channel: telegram, discord, whatsapp, email"),
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
    "context": CommandDef(
        desc="Codebase context engineering surface",
        subcommands={
            "blueprint": CommandDef(
                desc="Query the codebase Blueprint (structural blast-radius)",
                subcommands={
                    "affected": CommandDef(
                        desc="Print the blast-radius dependents of changed files",
                        args="<changed-files>",
                        flags=[_H],
                        notes=[
                            "Maps each changed file to its symbols, runs a transitive reverse "
                            "dependency traversal over the Blueprint, and prints the union of "
                            "dependents with file:line.",
                            "When the Blueprint is missing or stale (manifest baseline != current "
                            "main), prints a fallback notice and exits 0 — fall back to manual "
                            "exploration; blast-radius is never silently skipped.",
                        ],
                        examples=[
                            "telec context blueprint affected teleclaude/core/foo.py teleclaude/api/bar.py",
                        ],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
                    ),
                },
            ),
        },
    ),
    "docs": CommandDef(
        desc="Query documentation snippets",
        subcommands={
            "index": CommandDef(
                desc="List snippet IDs and metadata (phase 1)",
                args=f"[--baseline-only] [--third-party] [--areas <{'|'.join(TAXONOMY_TYPES)}>] [--domains <domain>] [--scope <{_SCOPE_VALUES}>] [--project <slug>] [--target <slug>]",
                flags=[
                    _H,
                    Flag("--baseline-only", "-b", "Show only baseline snippets"),
                    Flag("--third-party", "-t", "Include third-party docs"),
                    Flag("--areas", "-a", f"Filter by taxonomy type ({'|'.join(TAXONOMY_TYPES)}); omit for all"),
                    Flag("--domains", "-d", "Filter by published domain; omit for all"),
                    Flag("--scope", desc=f"Filter to global or project snippets ({_SCOPE_VALUES})"),
                    Flag("--project", desc="Filter to a registered project's snippets by slug"),
                    Flag("--target", desc="Filter to snippets delivered by slug"),
                ],
                notes=[
                    "Pending snippets (those with delivered_by) append ` (delivered by: slug1,slug2)` at the end of the phase-1 line.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "get": CommandDef(
                desc="Fetch full snippet content by ID (phase 2)",
                args=f"<id> [id...] [--scope <{_SCOPE_VALUES}>] [--project <slug>] [--target <slug>]",
                flags=[
                    _H,
                    Flag("--scope", desc=f"Filter to global or project snippets ({_SCOPE_VALUES})"),
                    Flag("--project", desc="Filter to a registered project's snippets by slug"),
                    Flag(
                        "--target",
                        desc="Include the slug's planned sections and companion replacement body (default: strip all)",
                    ),
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
                args=f"<slug> <content> --kind <{TODO_KIND_USAGE}> [--after <deps>] [--schedule <value>] [--icebox] [--project-root <path>] [--group <parent-slug>] [--plan] [--human-involved]",
                flags=[
                    _H,
                    _FLAG_AFTER_DEPS,
                    Flag(
                        "--schedule",
                        desc="Task-only schedule: ISO-8601 instant or cron:<minute hour day month weekday> (0/7=Sunday)",
                    ),
                    Flag(
                        "--kind",
                        desc=(
                            f"The work-unit's entry point into the lifecycle: {TODO_KIND_USAGE}. Always set it "
                            "when creating via the CLI — agents classify their own todos; omitting it is the "
                            "TUI dump path only. --kind task is side-effect-only and never touches the repo "
                            "(software-development/spec/todo-kind-task) — code work is change/feature/bug."
                        ),
                    ),
                    Flag("--icebox", desc="Create future todo parked in the icebox; does not auto-spawn"),
                    Flag("--project-root", "-p", desc="Target an explicit project root instead of the invocation cwd"),
                    Flag("--group", desc="Attach the new todo as a child of <parent-slug>, making the parent a holder"),
                    Flag(
                        "--plan",
                        desc="For --kind change, content seeds implementation-plan as a draft basis; for --kind task, content is the pre-authorized task-plan.",
                    ),
                    Flag(
                        "--hold",
                        desc="Create the todo with the dispatch brake set so router/runner pickup is suppressed until release; reserved for live-human prepare orchestration only.",
                        hidden=True,
                    ),
                    Flag(
                        "--human-involved",
                        desc=(
                            "Declares a human was in the conversation that produced this filing — saw it, asked "
                            "for it, or shaped it. Agent-caller only; a human door (TUI/CLI login/web) derives "
                            "this automatically and ignores the flag. Omitting it for an agent filing records "
                            "false — a forgotten flag lands the todo in the started-without-me audit bucket, "
                            "never a hidden autonomous filing."
                        ),
                    ),
                ],
                notes=[
                    "Creates the todo entry, canonical state, and stores content as the input artifact.",
                    "Include the observed trigger — what happened, what was asked, or what shaped this filing — "
                    "verbatim in <content> whenever a human conversation produced it, and pass --human-involved. "
                    "The gap this closes is the reporting invitation, not the schema: a filing whose trigger "
                    "context lives nowhere is unauditable later.",
                    "Content IS the input artifact — the author's INTENT (WHAT/WHY in operator language, "
                    "affected surfaces, acceptance shape, brownfield grounding), never a work order. Do NOT "
                    "prescribe HOW (file paths, mechanisms, edit/step instructions) or doc-layer deliverables — "
                    "in particular never instruct authoring an ADR or which snippets to write. Per "
                    "software-development/policy/preparation-artifact-quality (Input artifact quality): HOW is "
                    "the prepare phase's hypothesis to verify, doc routing is intake's, and an ADR is governed "
                    "by general/policy/adr-discipline (default none, never by process step). Any HOW or doc "
                    "instruction left in content is an unverified hypothesis, not a directive. (--plan is the "
                    "deliberate exception: its content is a complete implementation-plan, not an input.)",
                    "Use --icebox to place unfleshed future ideas directly into the icebox, while --hold is "
                    "the human requested create-time parking flag for todos needing fleshing out progressively. "
                    "--group <parent-slug> creates a complete grouped child in one call and makes the parent a structural holder "
                    "via the existing derivation; the first grouped child strips the parent's todo_state "
                    "while preserving all its artifacts as frozen evidence, and is refused once the parent's "
                    "lifecycle_phase has reached prepared or the work lane, so build, review, and finalize "
                    "state is never shredded.",
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
                    Flag("--include-icebox", "-i", "Include icebox items"),
                    Flag("--icebox-only", "-o", "Show only icebox items"),
                    Flag("--include-delivered", "-d", "Include delivered items"),
                    Flag("--delivered-only", desc="Show only delivered items"),
                    Flag("--include-removed", "-r", "Include soft-removed items"),
                    Flag("--removed-only", desc="Show only soft-removed items"),
                    Flag(
                        "--since",
                        desc="Only delivered entries at/after this point: duration (7d, 72h, 2w) or ISO date (2026-05-01). Implies --include-delivered.",
                    ),
                    Flag("--json", desc="Output as a sectioned JSON object (active/delivered/icebox/removed trees)"),
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
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "design": CommandDef(
                desc="Run the creative state machine",
                args="[<slug>]",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "co-create": CommandDef(
                desc="Deprecated alias for `telec todo design`",
                args="[<slug>]",
                flags=[_H],
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
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "freeze": CommandDef(
                desc="Move todo to icebox",
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "unfreeze": CommandDef(
                desc="Promote todo from icebox",
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "deliver": CommandDef(
                desc="Move todo to delivered",
                args="<slug> [--commit <hash>]",
                flags=[
                    Flag(
                        "--commit",
                        desc=(
                            "The commit that delivered the slug. The integrator always supplies its own pushed "
                            "commit and withholds delivery until that commit is confirmed on origin/main. Never "
                            "inferred from HEAD, which is routinely an unrelated commit; omitting it therefore "
                            "records a delivery with no provenance."
                        ),
                    ),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "update": CommandDef(
                desc="Update a todo slug, dependencies, or kind",
                args=f"<slug> [--slug <new>] [--after <dep>]... [--schedule <value>] [--kind <{TODO_KIND_USAGE}>] [--hold] [--release] [--unclaim] [--force]",
                flags=[
                    _H,
                    Flag("--slug", desc="New todo slug; delegates to the durable rename engine"),
                    Flag(
                        "--after",
                        desc=(
                            "Dependency slug(s); replaces the full set. "
                            "CSV accepted: --after parent-a,parent-b. "
                            "Repeated flags accepted for compatibility: --after parent-a --after parent-b. "
                            'Use --after "" to clear all dependencies.'
                        ),
                    ),
                    Flag(
                        "--schedule", desc="Task-only schedule; pass an empty value to clear (cron weekday 0/7=Sunday)"
                    ),
                    Flag("--kind", desc=f"New todo kind: {TODO_KIND_USAGE}"),
                    Flag("--hold", desc="Set the per-todo automatic dispatch brake"),
                    Flag("--release", desc="Release the per-todo automatic dispatch brake"),
                    Flag("--unclaim", desc="Release the caller-owned runner claim without ending the session"),
                    Flag("--force", desc="Allow permanent orphan-artifact handling for kind migrations"),
                ],
                notes=[
                    "Mutates slug, deps, kind, or hold; --after replaces the full dependency set.",
                    "Kind and slug changes are refused after build starts; --after remains allowed.",
                    "--hold and --release are mutually exclusive and compose with dependency updates.",
                    "--unclaim clears the caller-owned runner claim; --release only clears the dispatch brake.",
                    "--force only applies to kind orphan handling.",
                    "Combining --slug with other legs is staged, not a single atomic patch.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "prepare": CommandDef(
                desc="Run the Phase A (prepare) state machine",
                args="<slug>",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "work": CommandDef(
                desc="Run the Phase B (work) state machine",
                args="[<slug>]",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "integrate": CommandDef(
                desc="Run the Phase C (integrate) state machine",
                args="[<slug>]",
                flags=[_H],
                auth=CommandAuth(system=_SYS_INTG, human=_HR_MEMBER),
            ),
            "artifacts": CommandDef(
                desc="Manage todo artifacts in the database",
                subcommands={
                    "list": CommandDef(
                        desc="List artifacts for a todo",
                        args="<slug>",
                        flags=[_H],
                        examples=["telec todo artifacts list my-slug"],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "read": CommandDef(
                        desc="Read a todo artifact",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|architecture-review-findings|plan-review-findings|review-findings>",
                        flags=[_H],
                        examples=["telec todo artifacts read my-slug requirements"],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "write": CommandDef(
                        desc="Write a todo artifact",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|quality-checklist|design-spec|deferrals|log|requirements-review-findings|architecture-review-findings|plan-review-findings|review-findings> <content>",
                        flags=[_H],
                        notes=["Legacy bug artifacts are read-only; write bug todo content to input."],
                        examples=['telec todo artifacts write my-slug requirements "# Requirements content"'],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
                    ),
                    "diff": CommandDef(
                        desc="Show a unified diff between two artifact versions",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|architecture-review-findings|plan-review-findings|review-findings> <old-digest> <new-digest>",
                        flags=[_H],
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
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|architecture-review-findings|plan-review-findings|review-findings>",
                        flags=[_H],
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
                    _H,
                    Flag("--include-removed", desc="Also search soft-removed entries"),
                    Flag(
                        "--include-artifact-content",
                        desc="Include artifact body content under artifact_content in the payload",
                    ),
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
                args="<slug>",
                flags=[_H],
                notes=[
                    "Resolves the slug against soft-removed rows and restores the uniquely matching entry.",
                    "On success: status reverts to prev_status and outgoing dependencies are replayed.",
                ],
                examples=["telec todo reactivate my-slug"],
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
                ),
                flags=[
                    _H,
                    Flag("--verdict", desc="approve | changes_requested | needs_work | needs_decision"),
                    Flag(
                        "--phase",
                        desc=("Review phase the verdict belongs to (architecture_review, plan_review, build_review)"),
                    ),
                    Flag("--prd-approved", desc="Mark PRD as approved by the human"),
                    Flag("--task-approved", desc="Authorize the current task-plan for a task"),
                    Flag("--architecture-skipped", desc="Skip architecture phase with a reason"),
                    Flag("--drift-reviewed", desc="Record drift review: <artifact> <substantive|cosmetic> <reason>"),
                    Flag(
                        "--kind-assign",
                        desc=(
                            f"Assign kind and enter that kind's lifecycle entry phase: <{TODO_KIND_USAGE}> [content]. "
                            "task is side-effect-only and never touches the repo (software-development/spec/todo-kind-task)."
                        ),
                    ),
                    Flag(
                        "--build-complete",
                        desc="Record the worker's build-complete claim; gates run on the next telec todo work dispatch",
                    ),
                    Flag("--finalize-ready", desc="Mark worktree as ready for finalize handoff"),
                    Flag(
                        "--kickback",
                        desc="Work-orchestrator-only: send an unbuildable todo back to plan drafting",
                    ),
                    Flag("--reason", desc="Reason recorded to input (required with --kickback / --task-outcome error)"),
                    Flag(
                        "--task-outcome",
                        desc="Durable task firing outcome: success delivers/clears, error holds with --reason",
                    ),
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
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "bugs": CommandDef(
        desc="Bug reporting and tracking",
        subcommands={
            "report": CommandDef(
                desc="Scaffold a bug from a description; lifecycle router dispatches /next-prepare",
                args="<description> [--slug <slug>] [--body <text>] [--project <name>] [--human-involved]",
                flags=[
                    Flag("--slug", desc="Custom slug (default: auto-generated)"),
                    Flag("--body", desc="Detailed description body for bug.md"),
                    Flag(
                        "--project",
                        desc=(
                            "Project that owns the defective code (from trusted_dirs). Defaults to the "
                            "invoking cwd — where the symptom was OBSERVED, which is often not where the "
                            "code lives. Set it whenever the two differ."
                        ),
                    ),
                    Flag(
                        "--human-involved",
                        desc=(
                            "Declares a human was in the conversation that produced this filing — saw it, asked "
                            "for it, or shaped it. Agent-caller only; a human door (TUI/CLI login/web) derives "
                            "this automatically and ignores the flag. Omitting it for an agent filing records "
                            "false — a forgotten flag lands the todo in the started-without-me audit bucket, "
                            "never a hidden autonomous filing."
                        ),
                    ),
                ],
                notes=[
                    "File against the project that OWNS the defective code, not the one you happen to be "
                    "standing in. Platform behavior misbehaving inside a side project is a platform bug: "
                    "pass --project so the orchestrator that picks it up can actually deliver the fix. A bug "
                    "filed where the code does not live cannot be fixed there and gets re-filed later, "
                    "carrying stale conclusions with it. When you cannot tell which project owns it, ask.",
                    "Duplicate detection runs at the diagnose phase, not here: if another bug for the same defect is already in flight, the diagnose phase retires the later twin.",
                    "Your reported todo may therefore be removed as a duplicate — that is expected dedup, not a dropped report. The surviving todo carries the fix; do not re-report the same bug.",
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
                flags=[],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "suppress": CommandDef(
                desc="Register a known-issue suppression so the log bug hunter stops re-filing a triaged signal",
                args='"<pattern>" --reason <r> [--match substring|regex] [--disposition expected|wontfix] [--project <name>] [--source-bug <slug>] [--expires <when>]',
                flags=[
                    Flag("--reason", desc="Human-readable justification (required)"),
                    Flag("--match", desc="Match mode: substring (default, literal) or regex"),
                    Flag("--disposition", desc="expected or wontfix (default: wontfix); record-only"),
                    _FLAG_PROJECT_TRUSTED,
                    Flag("--source-bug", desc="Slug of the originating bug whose triage produced this suppression"),
                    Flag("--expires", desc="Optional ISO-8601 expiry after which the suppression lapses"),
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
                flags=[_FLAG_PROJECT_TRUSTED],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "unsuppress": CommandDef(
                desc="Remove a known-issue suppression by id so its signal is eligible for filing again",
                args="<id> [--project <name>]",
                flags=[_FLAG_PROJECT_TRUSTED],
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
                    Flag("--slug", desc="Custom slug (default: auto-generated from text)"),
                    Flag("--tags", desc="Comma-separated tags"),
                    Flag("--author", desc="Author identity (default: terminal auth)"),
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
                args="<job_name> --success <true|false> --message <text> [--items-processed <n>] [--error <text> ...]",
                flags=[
                    _H,
                    Flag("--success", desc="Whether the job completed successfully"),
                    Flag("--message", desc="Human-readable outcome summary"),
                    Flag("--items-processed", desc="Count of processed items (default: 0)"),
                    Flag("--error", desc="Error detail; repeat for multiple errors"),
                ],
                notes=[
                    "Validates job_name against configured jobs and writes JSON under ~/.teleclaude/jobs/{job}/runs/.",
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
                flags=[
                    Flag("--domain", desc="Filter by domain"),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "emit": CommandDef(
                desc="Emit an event via the daemon",
                hidden=True,
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "signals": CommandDef(
        desc="Signal pipeline status and diagnostics",
        subcommands={
            "status": CommandDef(
                desc="Show signal pipeline counts and last ingest time",
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
                    _H,
                    Flag("--exclude", desc="Server slug to omit; repeat for specialized procedures"),
                    Flag("--json", desc="Print raw JSON response"),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "list-tools": CommandDef(
                desc="Initialize one MCP server and list its tools",
                args="<slug> [--json]",
                flags=[
                    _H,
                    Flag("--json", desc="Print raw JSON response"),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "call": CommandDef(
                desc="Call one MCP tool through the lazy runtime",
                args="<slug> <tool> --json <arguments-json>",
                flags=[
                    _H,
                    Flag("--json", desc="JSON object arguments for the selected tool"),
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
                notes=[
                    "Stores auth state in a TTY-scoped file.",
                    "Running login again on the same TTY overwrites the existing file.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "whoami": CommandDef(
                desc="Show terminal login identity for this TTY",
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "logout": CommandDef(
                desc="Clear terminal login identity for this TTY",
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
        },
    ),
    "config": CommandDef(
        desc="Manage configuration",
        subcommands={
            "wizard": CommandDef(
                desc="Open the interactive configuration wizard",
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
            ),
            "get": CommandDef(
                desc="Get config values",
                args="[paths...]",
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "patch": CommandDef(
                desc="Patch config values",
                args="[--yaml '...']",
                flags=[_H, Flag("--yaml", "-y", "Inline YAML patch")],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
            ),
            "validate": CommandDef(
                desc="Full validation",
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "people": CommandDef(
                desc="Manage people",
                subcommands={
                    "list": CommandDef(
                        desc="List people",
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "add": CommandDef(
                        desc="Add a person",
                        args=(
                            "<name> --email <email> --role <role>"
                            " [--expertise '<json>']"
                            " [--telegram-user <user>] [--telegram-id <id>]"
                        ),
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "edit": CommandDef(
                        desc="Edit a person",
                        args=(
                            "<name> [--email <email>] [--role <role>]"
                            " [--expertise '<json>']"
                            " [--telegram-user <user>] [--telegram-id <id>]"
                        ),
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "remove": CommandDef(
                        desc="Remove a person",
                        args="<name>",
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "invite": CommandDef(
                        desc="Generate invite links for a person",
                        args="<name> [--json]",
                        flags=[_H, Flag("--json", desc="Emit machine-readable JSON output")],
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
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "set": CommandDef(
                        desc="Set environment variables",
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                },
            ),
            "notify": CommandDef(
                desc="Toggle notification settings",
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "tts": CommandDef(
                desc="Manage TTS dependency provisioning",
                subcommands={
                    "deprovision": CommandDef(
                        desc="Disable TTS and remove the TTS-exclusive optional dependencies",
                        args="[--yes]",
                        flags=[_H, Flag("--yes", desc="Confirm the destructive dependency removal")],
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
            "list": CommandDef(
                desc="List session summaries from mirrors",
                args="[--identity <email>] [--project <name>] [--limit <n>]",
                flags=[
                    _H,
                    Flag("--identity", desc="Filter by human identity (email or key)"),
                    _FLAG_PROJECT_FILTER,
                    _FLAG_LIMIT_20,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "search": CommandDef(
                desc="Search agent session transcripts",
                args="[terms...] [--agent <name>] [--computer <host>] [--limit <n>]",
                flags=[
                    _H,
                    Flag("--agent", "-a", "Agent name(s) or 'all' (default: all)"),
                    Flag("--computer", "-c", "Query one or more remote computers via daemon API"),
                    Flag("--limit", "-l", "Max results to show (default: 20)"),
                ],
                examples=[
                    "telec history search --agent claude config wizard",
                    "telec history search --agent all memory observations",
                    "telec history search --agent claude,codex bug fix",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "show": CommandDef(
                desc="Show full transcript for a session",
                args="<session-id> [--agent <name>] [--computer <host>] [--thinking] [--raw] [--tail <n>]",
                flags=[
                    _H,
                    Flag("--agent", "-a", "Agent name or 'all' (default: all)"),
                    Flag("--computer", "-c", "Fetch from a remote computer"),
                    _FLAG_THINKING,
                    Flag("--raw", desc="Show raw transcript instead of mirror text"),
                    Flag("--tail", desc="Limit output to last N chars (0=unlimited)"),
                ],
                examples=[
                    "telec history show f3625680",
                    "telec history show f3625680 --agent claude --tail 5000",
                    "telec history show f3625680 --thinking",
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
                    _H,
                    Flag("--limit", desc="Max results (default: 50)"),
                    Flag(
                        "--type",
                        desc="Filter by observation type stored in the schema",
                    ),
                    _FLAG_PROJECT_FILTER,
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
                    _H,
                    _FLAG_LIMIT_20,
                    Flag(
                        "--type",
                        desc="Filter by observation type stored in the schema",
                    ),
                    _FLAG_PROJECT_FILTER,
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
                    _H,
                    Flag("--title", desc="Observation title"),
                    Flag("--type", desc="Observation type"),
                    Flag("--project", desc="Project name"),
                ],
                examples=[],
                hidden=True,
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "delete": CommandDef(
                desc="Delete a personal-preference observation by ID (typically run by the human while pruning).",
                args="<id>",
                flags=[_H],
                examples=["telec memories delete 42"],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "timeline": CommandDef(
                desc="Show personal-preference observations around an anchor ID.",
                args="<id> [--before <n>] [--after <n>] [--project <name>]",
                flags=[
                    _H,
                    Flag("--before", desc="Observations before anchor (default: 3)"),
                    Flag("--after", desc="Observations after anchor (default: 3)"),
                    _FLAG_PROJECT_FILTER,
                ],
                examples=["telec memories timeline 42 --before 3 --after 3"],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "code": CommandDef(
        desc="Code quality and commit tools",
        notes=[
            "lint, test, format, and install require the code capability.",
            "changed, add, and commit remain available when either code or docs is subscribed.",
        ],
        subcommands={
            "lint": CommandDef(
                desc="Run native make lint plus TeleClaude guardrails",
                flags=[
                    _H,
                    Flag("--all", desc="Run against all configured sources, skip workspace scoping"),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "test": CommandDef(
                desc="Run native make test",
                flags=[
                    _H,
                    Flag("--all", desc="Run all tests, skip workspace scoping"),
                    Flag(
                        "--update-snapshots",
                        desc=(
                            "Update snapshot files after reading diffs. Use only when test failures show "
                            "snapshot deltas that match your intended change."
                        ),
                    ),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "format": CommandDef(
                desc="Run native make format",
                flags=[_H, Flag("--all", desc="Format all configured sources, skip workspace scoping")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "install": CommandDef(
                desc="Run native make install",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "changed": CommandDef(
                desc="List workspace-scoped changed files",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "add": CommandDef(
                desc="Stage files for the next commit (NEW, unmerged, or partial-staged tracked)",
                args="<path> [<path> ...]",
                flags=[_H],
                notes=[
                    "Sealed equivalent of 'git add' for the three cases git's data model genuinely requires staging:",
                    "  (1) NEW (untracked) files — must enter the index before commit pathspec can match.",
                    "  (2) Unmerged-index files (post-conflict) — must be marked resolved before commit.",
                    "  (3) Partial-staged tracked files (staged hunks + later working-tree delta) — "
                    "must be fully (re)staged so the pathspec commit does not silently sweep in "
                    "unstaged hunks. The partial-staging guard in `telec code commit` directs agents "
                    "here for recovery.",
                    "Modified-tracked files that are NOT partial-staged don't need staging — pathspec "
                    "commits them straight from the working tree.",
                    "NEW files in scope are NOT auto-committed; this is the explicit declaration step. "
                    "Without it, untracked files stay untracked (safety net for temp/scratch artifacts "
                    "the agent may have created incidentally).",
                    "Alternative one-shot form: telec code commit --approved '<msg>' --include <path>.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "commit": CommandDef(
                desc="Commit workspace-scoped changes via a pathspec-scoped commit (sealed; no git forwarding)",
                args='"<message>" [--approved] [--include <path> ...] [--only <path> ...]',
                flags=[
                    _H,
                    Flag(
                        "--approved",
                        desc="Agent-owned sealed commit gate. Required to commit; bare main invocation prints commit-first and review-routing guidance.",
                    ),
                    Flag(
                        "--include",
                        desc="Declare files outside workspace scope to add to this commit (space-separated paths).",
                    ),
                    Flag(
                        "--only",
                        desc="Commit exactly these paths instead of the resolved workspace scope; intended for splitting a dirty scope into multiple commits.",
                    ),
                ],
                notes=[
                    "Accepts only: one quoted message, --approved, --include <path> ..., and --only <path> ... .",
                    "Modified-tracked files in scope are auto-committed via pathspec straight from the working tree — no staging needed.",
                    "NEW (untracked) files in scope are NOT auto-committed by default; declare them via `telec code add`, `--include`, or `--only` (safety net against incidental temp/scratch artifacts).",
                    "--only commits exactly the declared paths and is mutually exclusive with --include.",
                    "Unmerged-index files in pathspec are staged internally for the integrator conflict path.",
                    "Without --approved on main: prints commit-first and review-routing guidance and exits.",
                    "Pathspec = workspace scope plus --include paths, or exactly --only paths. Anything else in the index (foreign stage) is left untouched — there is no env-var bypass.",
                    "The 🤖/Co-Authored-By trailer is appended automatically (idempotent).",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
        },
    ),
}
HELP_SUBCOMMAND_EXPANSIONS: dict[str, dict[str, list[tuple[str, str]]]] = {}

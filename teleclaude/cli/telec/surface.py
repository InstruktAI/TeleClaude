"""CLI surface — CLI_SURFACE dict and HELP_SUBCOMMAND_EXPANSIONS."""

from __future__ import annotations  # noqa: I001

from teleclaude.constants import DOMAIN_SCOPES, TAXONOMY_TYPES

from .surface_types import (
    CommandAuth,
    CommandDef,
    Flag,
    TelecCommand,
    _FLAG_AFTER_DEPS,
    _FLAG_AGENT,
    _FLAG_COMPUTER,
    _FLAG_DETACH,
    _FLAG_LIMIT_20,
    _FLAG_MODE,
    _FLAG_PROJECT_FILTER,
    _FLAG_PROJECT_PATH,
    _FLAG_PROJECT_TRUSTED,
    _FLAG_SESSION,
    _FLAG_THINKING,
    _H,
    _SYS_ALL,
    _SYS_INTG,
    _SYS_ORCH,
    _HR_ADMIN,
    _HR_ALL,
    _HR_ALL_NON_ADMIN,
    _HR_MEMBER,
    _HR_MEMBER_CONTRIB,
    _HR_MEMBER_CONTRIB_NEWCOMER,
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
                args="[--all] [--closed] [--job <value>]",
                flags=[
                    _H,
                    Flag("--all", desc="Show all sessions"),
                    Flag("--closed", desc="Include closed sessions"),
                    Flag("--job", desc="Filter by job value"),
                ],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "start": CommandDef(
                desc="Start a new agent session",
                args=(
                    "[--computer <host>] [--project <path>] [--agent <name>] [--mode <mode>]"
                    " [--message <msg>] [--direct] [--detach]"
                ),
                flags=[
                    _H,
                    _FLAG_COMPUTER,
                    _FLAG_PROJECT_PATH,
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
                    "telec sessions start --project /tmp/project",
                    "telec sessions start --project /tmp/project --agent claude --mode slow",
                    'telec sessions start --project /tmp/project --message "Implement feature X"',
                    "telec sessions start --project /tmp/project --direct",
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
                args="<session_id> [--since <ts>] [--tools] [--thinking]",
                flags=[
                    _H,
                    _FLAG_SESSION,
                    Flag("--since", desc="ISO8601 timestamp filter"),
                    Flag("--tools", desc="Include tool use entries"),
                    _FLAG_THINKING,
                ],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "run": CommandDef(
                desc="Run a slash command on a new agent session",
                args=(
                    "[--command <cmd>] [--project <path>] [--args <val>] [--agent <name>]"
                    " [--mode <mode>] [--computer <host>] [--subfolder <dir>] [--detach]"
                    " [--additional-context <ctx>]"
                ),
                flags=[
                    _H,
                    Flag("--command", desc="Slash command (e.g. /next-build)"),
                    _FLAG_PROJECT_PATH,
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
                    "telec sessions run --command /next-build --args my-slug --detach",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "revive": CommandDef(
                desc="Revive session by TeleClaude session ID",
                args="<session_id>",
                flags=[
                    _H,
                    Flag("--agent", desc="Treat session_id as native agent session ID for the given agent"),
                    Flag("--attach", desc="Attach to tmux session after revive"),
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
                desc="End (terminate) a session",
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
                    "Prompts for release-channel enrollment (alpha/beta/stable).",
                    "AI-driven analysis lives in `telec projects {onboard,analyze,assess}`.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "onboard": CommandDef(
                desc="Full project bootstrap: init plumbing, then dispatch config assessment and doc-snippet analysis",
                flags=[_H],
                notes=[
                    "Runs `telec projects init` synchronously, then dispatches `telec projects assess` and `telec projects analyze`.",
                    "AI sessions run concurrently in tmux after dispatch — monitor via `telec sessions list`.",
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
        desc="Validate, build indexes, and deploy artifacts",
        args="[--warn-only] [--validate-only]",
        flags=[
            _H,
            Flag("--warn-only", desc="Warn but don't fail"),
            Flag("--validate-only", desc="Validate without building"),
        ],
        auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
    ),
    "docs": CommandDef(
        desc="Query documentation snippets",
        subcommands={
            "index": CommandDef(
                desc="List snippet IDs and metadata (phase 1)",
                args=f"[--baseline-only] [--third-party] [--areas <{'|'.join(TAXONOMY_TYPES)}>] [--domains <{'|'.join(DOMAIN_SCOPES)}>] [--target <slug>]",
                flags=[
                    _H,
                    Flag("--baseline-only", "-b", "Show only baseline snippets"),
                    Flag("--third-party", "-t", "Include third-party docs"),
                    Flag("--areas", "-a", f"Filter by taxonomy type ({'|'.join(TAXONOMY_TYPES)}); omit for all"),
                    Flag("--domains", "-d", f"Filter by domain ({'|'.join(DOMAIN_SCOPES)}); omit for all"),
                    Flag("--target", desc="Filter to snippets delivered by slug"),
                ],
                notes=[
                    "Non-actual snippets render with a [target → slug] or [mixed → slug] prefix in phase 1 output.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "get": CommandDef(
                desc="Fetch full snippet content by ID (phase 2)",
                args="<id> [id...]",
                flags=[_H],
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
                desc="Create a draft todo skeleton with no input artifact",
                args="<slug> [--after <deps>] [--kind <feature|bug|refactor|migration|prepped>]",
                flags=[
                    _H,
                    _FLAG_AFTER_DEPS,
                    Flag("--kind", desc="Work item kind; defaults to feature"),
                ],
                notes=[
                    "Creates only the roadmap entry and canonical draft state.",
                    "Use this when humans are fleshing out artifacts directly and there is no braindump input yet.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
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
                desc="Remove a todo and its roadmap entry",
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "prepare": CommandDef(
                desc="Run the Phase A (prepare) state machine",
                args="[<slug>] [--invalidate-check] [--changed-paths <paths>]",
                flags=[
                    _H,
                    Flag("--invalidate-check", desc="Scan all active todos and invalidate stale preparations"),
                    Flag("--changed-paths", desc="Comma-separated file paths for invalidation check"),
                ],
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
            "mark-phase": CommandDef(
                desc="Operator override: write the authoritative lifecycle_phase field",
                args="<slug> --phase <value>",
                flags=[_H, Flag("--phase", desc="Phase value matching the canonical lifecycle phase enum")],
                notes=[
                    "Operator escape hatch; downstream phases will see whatever you set without re-deriving from evidence."
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "reconcile": CommandDef(
                desc="Re-evaluate current todo evidence and align lifecycle_phase within one stage",
                args="<slug> [--stage <prepare|work>]",
                flags=[_H, Flag("--stage", desc="Optional stage override; defaults from current lifecycle_phase")],
                notes=[
                    "Uses the current lifecycle phase's stage implicitly unless --stage is provided.",
                    "Stage-bounded: prepare reconciliation ignores work evidence, and work reconciliation ignores prepare evidence.",
                    "Does not dispatch work; run telec todo prepare/work afterward.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "set-deps": CommandDef(
                desc="Set dependencies for a work item in the roadmap",
                args="<slug> [--after <slugs>]",
                flags=[
                    _H,
                    Flag("--after", desc="Dependency slug (repeatable)"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "dump": CommandDef(
                desc="Fire-and-forget brain dump with notification trigger",
                args="<slug> <content> [--after <deps>] [--draft] [--prepped]",
                flags=[
                    _FLAG_AFTER_DEPS,
                    Flag("--draft", desc="Create silently — skip domain event so no cartridge picks it up"),
                    Flag(
                        "--prepped",
                        desc=(
                            "HUMAN-IN-THE-LOOP REQUIRED. Content is a complete plan; mark todo prepped "
                            "and ready for build. Agents must obtain explicit human approval of the "
                            "exact plan content before invoking. Never apply general guidance from a "
                            "prior --prepped dump as authorization for a different todo."
                        ),
                    ),
                ],
                notes=[
                    "Emits todo.dumped notification for autonomous processing.",
                    "Use --draft to stage an idea without triggering autonomous pickup.",
                    "Use --prepped when content is a complete implementation plan: content becomes "
                    "the implementation-plan artifact, kind=prepped, plan_review=approve, "
                    "ready for build.",
                    "POLICY — --prepped requires explicit human-in-the-loop approval of the exact plan content. "
                    "Bypassing prepare via --prepped lands a build-ready todo into the work pickup chain, "
                    "where an autonomous orchestrator can spawn builders against it. Agents must present "
                    "the full plan and the dump command to the human and obtain explicit consent BEFORE "
                    "invoking. Approval is per-todo and per-plan — never inherit it from another todo.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "split": CommandDef(
                desc="Split a todo into child items (container transition)",
                args="<slug> [--into <child>]",
                flags=[
                    Flag("--into", desc="Child slug (repeatable, at least one required)"),
                ],
                notes=[
                    (
                        "Scaffolds children and marks the parent as a holder/container. Parent artifacts "
                        "are preserved as source material for plucking and seeding child todos."
                    ),
                    (
                        "Children inherit parent's approved prepare phase: if requirements were approved, "
                        "children start at plan_drafting; if the plan was approved, children start at "
                        "prepared (ready for build)."
                    ),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
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
                        args="<slug> <name: input|prd|requirements|architecture|test-specs|implementation-plan|bug|quality-checklist|design-spec|deferrals|requirements-review-findings|architecture-review-findings|spec-review-findings|plan-review-findings|review-findings>",
                        flags=[_H],
                        examples=["telec todo artifacts read my-slug requirements"],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "write": CommandDef(
                        desc="Write a todo artifact",
                        args="<slug> <name: input|prd|requirements|architecture|test-specs|implementation-plan|bug|quality-checklist|design-spec|deferrals|requirements-review-findings|architecture-review-findings|spec-review-findings|plan-review-findings|review-findings> <content>",
                        flags=[_H],
                        examples=['telec todo artifacts write my-slug requirements "# Requirements content"'],
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
                    ),
                    "diff": CommandDef(
                        desc="Show a unified diff between two artifact versions",
                        args="<slug> <name: input|prd|requirements|architecture|test-specs|implementation-plan|bug|quality-checklist|design-spec|deferrals|requirements-review-findings|architecture-review-findings|spec-review-findings|plan-review-findings|review-findings> <old-digest> <new-digest>",
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
                        args="<slug> <name: input|prd|requirements|architecture|test-specs|implementation-plan|bug|quality-checklist|design-spec|deferrals|requirements-review-findings|architecture-review-findings|spec-review-findings|plan-review-findings|review-findings>",
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
                desc="Show full state payload for a todo",
                args="<slug>",
                flags=[_H],
                examples=["telec todo show my-slug"],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "stamp": CommandDef(
                desc="Stamp a verdict or readiness marker into todo state",
                args=(
                    "<slug> [--verdict <v> --phase <p>] [--prd-approved]"
                    " [--architecture-skipped <reason>] [--test-specs-skipped <reason>]"
                    " [--drift-reviewed <artifact> <verdict> <reason>] [--finalize-ready]"
                ),
                flags=[
                    _H,
                    Flag("--verdict", desc="approve | changes_requested | needs_work | needs_decision"),
                    Flag(
                        "--phase",
                        desc=(
                            "Review phase the verdict belongs to "
                            "(architecture_review, test_spec_review, plan_review, build_review)"
                        ),
                    ),
                    Flag("--prd-approved", desc="Mark PRD as approved by the human"),
                    Flag("--architecture-skipped", desc="Skip architecture phase with a reason"),
                    Flag("--test-specs-skipped", desc="Skip test-specs phase with a reason"),
                    Flag("--drift-reviewed", desc="Record drift review: <artifact> <substantive|cosmetic> <reason>"),
                    Flag("--finalize-ready", desc="Mark worktree as ready for finalize handoff"),
                ],
                examples=[
                    "telec todo stamp my-slug --verdict approve --phase plan_review",
                    "telec todo stamp my-slug --verdict changes_requested --phase build_review",
                    "telec todo stamp my-slug --finalize-ready",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
    "roadmap": CommandDef(
        desc="Manage the work item roadmap",
        subcommands={
            "list": CommandDef(
                desc="List roadmap entries (source of truth for todo status)",
                args="[--include-icebox] [--icebox-only] [--include-delivered] [--delivered-only] [--since <when>] [--json]",
                flags=[
                    Flag("--include-icebox", "-i", "Include icebox items"),
                    Flag("--icebox-only", "-o", "Show only icebox items"),
                    Flag("--include-delivered", "-d", "Include delivered items"),
                    Flag("--delivered-only", desc="Show only delivered items"),
                    Flag(
                        "--since",
                        desc="Only delivered entries at/after this point: duration (7d, 72h, 2w) or ISO date (2026-05-01). Implies --include-delivered.",
                    ),
                    Flag("--json", desc="Output as a sectioned JSON object (active/delivered/icebox trees)"),
                ],
                notes=[
                    "Output is sectioned into active/delivered/icebox dependency trees.",
                    "CONTRACT CHANGE: --json now emits a nested object keyed by section "
                    "(active/delivered/icebox), each a tree with `children`; previously a flat "
                    "list. Empty roadmap emits `{}`. Text output no longer appends a [status] suffix.",
                    "--include-delivered returns the full delivery history; scope it with --since.",
                    "--since accepts a relative duration (7d, 72h, 2w) or an ISO date/timestamp.",
                    "--since alone implies --include-delivered; combine with --delivered-only to exclude active items.",
                ],
                examples=[
                    "telec roadmap list --include-delivered --since 7d",
                    "telec roadmap list --delivered-only --since 2026-05-01",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "add": CommandDef(
                desc="Add entry to the roadmap",
                args="<slug> [--group <holder-slug>] [--after <slugs>] [--before <slug>] [--description <text>]",
                flags=[
                    Flag("--group", desc="Nest under an existing roadmap entry (holder slug)"),
                    _FLAG_AFTER_DEPS,
                    Flag("--before", desc="Insert before this slug (default: append)"),
                    Flag("--description", desc="Summary description"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "remove": CommandDef(
                desc="Remove entry from the roadmap",
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "move": CommandDef(
                desc="Reorder an entry in the roadmap",
                args="<slug> [--before <slug>] [--after <slug>]",
                flags=[
                    Flag("--before", desc="Move before this slug"),
                    Flag("--after", desc="Move after this slug"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "deps": CommandDef(
                desc="Set dependencies for an entry",
                args="<slug> [--after <slugs>]",
                flags=[
                    _FLAG_AFTER_DEPS,
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "freeze": CommandDef(
                desc="Move entry to icebox",
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "unfreeze": CommandDef(
                desc="Promote entry from icebox to roadmap",
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "migrate-icebox": CommandDef(
                desc="One-time migration: move icebox folders into todos/_icebox/",
                args="",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "deliver": CommandDef(
                desc="Move entry to delivered",
                args="<slug> [--commit <hash>]",
                flags=[
                    Flag("--commit", desc="Commit hash (auto-detects HEAD if omitted)"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
        },
    ),
    "bugs": CommandDef(
        desc="Bug reporting and tracking",
        subcommands={
            "report": CommandDef(
                desc="Scaffold a bug from a description; lifecycle router dispatches /next-work",
                args="<description> [--slug <slug>] [--body <text>] [--project <name>]",
                flags=[
                    Flag("--slug", desc="Custom slug (default: auto-generated)"),
                    Flag("--body", desc="Detailed description body for bug.md"),
                    _FLAG_PROJECT_TRUSTED,
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "create": CommandDef(
                desc="Scaffold a bug from an explicit slug; lifecycle router dispatches /next-work",
                args="<slug> [--project <name>]",
                flags=[
                    _FLAG_PROJECT_TRUSTED,
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER_CONTRIB),
            ),
            "list": CommandDef(
                desc="List in-flight bug fixes with status",
                flags=[],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
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
            "invite": CommandDef(
                desc="Generate invite links for a person",
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
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
        desc="Search and manage memory observations",
        subcommands={
            "list": CommandDef(
                desc="List memory observations",
                args="[--limit <n>] [--type <type>] [--project <name>]",
                flags=[
                    _H,
                    Flag("--limit", desc="Max results (default: 50)"),
                    Flag(
                        "--type",
                        desc="Filter by type: preference, decision, discovery, gotcha, pattern, friction, context",
                    ),
                    _FLAG_PROJECT_FILTER,
                ],
                examples=[
                    "telec memories list",
                    "telec memories list --type gotcha --project teleclaude",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "search": CommandDef(
                desc="Search memory observations",
                args="<query> [--limit <n>] [--type <type>] [--project <name>]",
                flags=[
                    _H,
                    _FLAG_LIMIT_20,
                    Flag(
                        "--type",
                        desc="Filter by type: preference, decision, discovery, gotcha, pattern, friction, context",
                    ),
                    _FLAG_PROJECT_FILTER,
                ],
                examples=[
                    'telec memories search "session reason"',
                    'telec memories search "config wizard" --type discovery --project teleclaude',
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "save": CommandDef(
                desc="Save a memory observation",
                args="<text> [--title <title>] [--type <type>] [--project <name>]",
                flags=[
                    _H,
                    Flag("--title", desc="Observation title"),
                    Flag("--type", desc="Type: preference, decision, discovery, gotcha, pattern, friction, context"),
                    Flag("--project", desc="Project name"),
                ],
                examples=[
                    (
                        'telec memories save "Root cause identified for session update reason suppression." '
                        '--title "Session reason fix" --type discovery --project teleclaude'
                    ),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "delete": CommandDef(
                desc="Delete a memory observation by ID",
                args="<id>",
                flags=[_H],
                examples=["telec memories delete 123"],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "timeline": CommandDef(
                desc="Show observations around an anchor ID",
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
        subcommands={
            "lint": CommandDef(
                desc="Run language-aware lint pipeline",
                flags=[
                    _H,
                    Flag("--step", desc="Run a single pipeline step"),
                    Flag("--all", desc="Run against all configured sources, skip workspace scoping"),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "test": CommandDef(
                desc="Run language-aware test suite",
                flags=[
                    _H,
                    Flag("--expensive", desc="Include expensive/slow tests"),
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
                desc="Run language-aware code formatter",
                flags=[_H, Flag("--all", desc="Format all configured sources, skip workspace scoping")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "changed": CommandDef(
                desc="List workspace-scoped changed files",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
            "commit": CommandDef(
                desc="Stage workspace-scoped files, lint, format, and commit",
                args="[<git-commit-args>]",
                flags=[
                    _H,
                    Flag("-m", desc="Commit message"),
                    Flag("--approved", desc="Human-approved Path B commit", hidden=True),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
            ),
        },
    ),
}
HELP_SUBCOMMAND_EXPANSIONS: dict[str, dict[str, list[tuple[str, str]]]] = {}

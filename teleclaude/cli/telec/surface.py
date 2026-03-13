"""CLI surface — CLI_SURFACE dict and HELP_SUBCOMMAND_EXPANSIONS."""
from __future__ import annotations  # noqa: I001

from .surface_types import (  # noqa: F401  # type: ignore[reportUnusedImport]
    CommandAuth, CommandDef, Flag, TelecCommand, _H, _SYS_ALL, _SYS_INTG, _SYS_ORCH,
    _HR_ADMIN, _HR_ALL, _HR_ALL_NON_ADMIN, _HR_MEMBER, _HR_MEMBER_CONTRIB, _HR_MEMBER_CONTRIB_NEWCOMER,
)

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
                    Flag("--job", desc="Filter by session_metadata.job value"),
                ],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
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
                    Flag("--detach", desc="Fire-and-forget: inherit context but skip listener registration"),
                ],
                notes=[
                    "--project is required.",
                    "Use --direct for peer conversation mode when you want shared linked output instead of worker supervision notifications.",
                    "Use --detach for fire-and-forget dispatch: child inherits identity but caller receives no notifications.",
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
                args="<session_id> [<message>]",
                flags=[
                    _H,
                    Flag("--session", "-s", "Session ID (compatibility form)"),
                    Flag("--message", "-m", "Message text (compatibility form)"),
                    Flag("--direct", desc="Conversation mode: create shared direct link"),
                    Flag("--close-link", desc="Close direct link with target session (alias: --close_link)"),
                ],
                notes=[
                    "Positional form is canonical: telec sessions send <session_id> <message>.",
                    "One-time ignition: sending once with --direct establishes the link.",
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
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
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
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB_NEWCOMER),
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
                    Flag("--detach", desc="Fire-and-forget: inherit context but skip listener registration"),
                    Flag("--additional-context", desc="Additional context for the worker, appended to startup message"),
                ],
                notes=[
                    "Creates a fresh session and runs the slash command as the first agent message.",
                    "Worker lifecycle commands: /next-build, /next-review-build, /next-fix-review, /next-finalize.",
                    "Example: telec sessions run --command /next-build --args my-slug --project /repo/path",
                    "Use --detach for fire-and-forget dispatch: child inherits identity but caller receives no notifications.",
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
                    "Without --agent, session_id is a TeleClaude session ID.",
                    "With --agent, session_id is a native agent session ID resolved via the specified agent.",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
            ),
            "end": CommandDef(
                desc="End (terminate) a session",
                args="<session_id>",
                flags=[
                    _H,
                    Flag("--session", "-s", "Session ID"),
                    Flag("--computer", desc="Target computer (optional; defaults to local)"),
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
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
            ),
            "result": CommandDef(
                desc="Send a formatted result to the session's user",
                args="<content>",
                flags=[_H, Flag("--format", desc="Output format: markdown, html")],
                auth=CommandAuth(system=_SYS_ALL | _SYS_INTG, human=_HR_MEMBER_CONTRIB),
            ),
            "file": CommandDef(
                desc="Send a file to the session's user",
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
                flags=[_H, Flag("--data", desc="Widget expression as JSON")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "escalate": CommandDef(
                desc="Escalate to an admin via Discord",
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
        desc="Manage project inventory",
        subcommands={
            "list": CommandDef(
                desc="List projects on local and remote computers",
                flags=[_H, Flag("--computer", desc="Filter to a specific computer")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
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
                args="<agent>",
                flags=[
                    _H,
                    Flag("--status", desc="Status: available, unavailable, degraded"),
                    Flag("--reason", desc="Reason for status change"),
                    Flag("--until", desc="ISO8601 UTC expiry for unavailable"),
                    Flag("--clear", desc="Reset to available immediately"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
            ),
        },
    ),
    "channels": CommandDef(
        desc="Manage internal Redis Stream channels",
        subcommands={
            "list": CommandDef(
                desc="List active channels",
                flags=[_H, Flag("--project", desc="Filter by project name")],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER),
            ),
            "publish": CommandDef(
                desc="Publish a message to a channel",
                args="<channel>",
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
    "init": CommandDef(
        desc="Initialize docs sync, auto-rebuild watcher, and optional project enrichment",
        notes=[
            "Sets up git hooks, syncs artifacts, installs file watchers.",
            "Optionally runs AI-driven project analysis to generate doc snippets.",
            "First init offers enrichment; re-init offers refresh of existing analysis.",
            "Prompts for release-channel enrollment (alpha/beta/stable).",
        ],
        auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
    ),
    "version": CommandDef(
        desc="Print version, channel, and commit",
        auth=CommandAuth(system=_SYS_ALL, human=_HR_ALL),
    ),
    "sync": CommandDef(
        desc="Validate, build indexes, and deploy artifacts",
        flags=[
            _H,
            Flag("--warn-only", desc="Warn but don't fail"),
            Flag("--validate-only", desc="Validate without building"),
        ],
        auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
    ),
    "watch": CommandDef(
        desc="Watch project for changes and auto-sync",
        flags=[_H],
        hidden=True,
        auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
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
            "Example phase 1: telec docs index --areas policy,procedure --domains software-development",
            "Example phase 2: telec docs get software-development/policy/testing project/spec/command-surface",
        ],
    ),
    "todo": CommandDef(
        desc="Manage work items",
        subcommands={
            "create": CommandDef(
                desc="Run the creative state machine",
                args="[<slug>]",
                flags=[_H],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "scaffold": CommandDef(
                desc="Scaffold todo files for a slug",
                args="<slug>",
                flags=[
                    Flag("--after", desc="Comma-separated dependency slugs"),
                ],
                notes=["Also registers the entry in roadmap.yaml when --after is provided."],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER_CONTRIB),
            ),
            "remove": CommandDef(
                desc="Remove a todo and its roadmap entry",
                args="<slug>",
                flags=[],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "validate": CommandDef(
                desc="Validate todo files and state.yaml schema",
                args="[slug]",
                flags=[],
                notes=["If slug is omitted, all active todos are checked."],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "demo": CommandDef(
                desc="Manage and run demo artifacts",
                subcommands={
                    "list": CommandDef(
                        desc="List available demos",
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "validate": CommandDef(
                        desc="Validate demo artifact for a slug",
                        args="<slug>",
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
                    ),
                    "run": CommandDef(
                        desc="Execute demo bash blocks for a slug",
                        args="<slug>",
                        auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
                    ),
                    "create": CommandDef(
                        desc="Promote demo artifact for a slug",
                        args="<slug>",
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER_CONTRIB),
                    ),
                },
                notes=[
                    "Use 'list' explicitly to list available demos.",
                    "validate <slug>: check todos/{slug}/demo.md has executable bash blocks.",
                    "run <slug>: execute bash blocks from demos/{slug}/demo.md.",
                    "create <slug>: promote todos/{slug}/demo.md to demos/{slug}/demo.md.",
                ],
            ),
            "prepare": CommandDef(
                desc="Run the Phase A (prepare) state machine",
                args="[<slug>]",
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
                desc="Mark a work or prepare phase in state.yaml",
                args="<slug>",
                flags=[
                    _H,
                    Flag("--phase", desc="Phase: build, review, prepare, requirements_review, plan_review"),
                    Flag(
                        "--status",
                        desc="Work: pending/started/complete/approved/changes_requested; Prepare verdict: approve/needs_work/needs_decision; Prepare lifecycle: prepared, gate, etc.",
                    ),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "mark-finalize-ready": CommandDef(
                desc="Record finalize readiness in worktree state.yaml",
                args="<slug>",
                flags=[
                    _H,
                    Flag("--worker-session-id", desc="Finalizer worker session that reported FINALIZE_READY"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "set-deps": CommandDef(
                desc="Set dependencies for a work item in the roadmap",
                args="<slug>",
                flags=[
                    _H,
                    Flag("--after", desc="Dependency slug (repeatable)"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
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
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "dump": CommandDef(
                desc="Fire-and-forget brain dump with notification trigger",
                args="<slug> <content>",
                flags=[
                    Flag("--after", desc="Comma-separated dependency slugs"),
                ],
                notes=[
                    "Emits todo.dumped notification for autonomous processing.",
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "split": CommandDef(
                desc="Split a todo into child items (container transition)",
                args="<slug>",
                flags=[
                    Flag("--into", desc="Child slug (repeatable, at least one required)"),
                ],
                notes=[
                    "Scaffolds children, cleans parent artifacts, sets container state.",
                    "Children inherit parent's approved prepare phase: if requirements were approved, children start at plan_drafting; if the plan was approved, children start at prepared (ready for build).",
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
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
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER_CONTRIB_NEWCOMER),
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
                args="<slug>",
                flags=[
                    Flag("--before", desc="Move before this slug"),
                    Flag("--after", desc="Move after this slug"),
                ],
                auth=CommandAuth(system=_SYS_ORCH, human=_HR_MEMBER),
            ),
            "deps": CommandDef(
                desc="Set dependencies for an entry",
                args="<slug>",
                flags=[
                    Flag("--after", desc="Comma-separated dependency slugs"),
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
                args="<slug>",
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
                desc="Report a bug, scaffold, and dispatch fix",
                args="<description>",
                flags=[
                    Flag("--slug", desc="Custom slug (default: auto-generated)"),
                    Flag("--body", desc="Detailed description body for bug.md"),
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB_NEWCOMER),
            ),
            "create": CommandDef(
                desc="Scaffold bug files for a slug",
                args="<slug>",
                flags=[],
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
                args="<description-or-text>",
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
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "edit": CommandDef(
                        desc="Edit a person",
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                    "remove": CommandDef(
                        desc="Remove a person",
                        auth=CommandAuth(system=_SYS_ORCH, human=_HR_ADMIN),
                    ),
                },
                notes=[
                    "To edit people's subscriptions, modify the person config: ~/.teleclaude/people/{name}/teleclaude.yml"
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
            "search": CommandDef(
                desc="Search agent session transcripts",
                args="[terms...]",
                flags=[
                    _H,
                    Flag("--agent", "-a", "Agent name(s) or 'all' (default: all)"),
                    Flag("--computer", desc="Query one or more remote computers via daemon API"),
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
                args="<session-id>",
                flags=[
                    _H,
                    Flag("--agent", "-a", "Agent name or 'all' (default: all)"),
                    Flag("--computer", desc="Fetch from a remote computer"),
                    Flag("--thinking", desc="Include thinking blocks"),
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
            "search": CommandDef(
                desc="Search memory observations",
                args="<query>",
                flags=[
                    _H,
                    Flag("--limit", desc="Max results (default: 20)"),
                    Flag(
                        "--type",
                        desc="Filter by type: preference, decision, discovery, gotcha, pattern, friction, context",
                    ),
                    Flag("--project", desc="Filter by project name"),
                ],
                examples=[
                    'telec memories search "session reason"',
                    'telec memories search "config wizard" --type discovery --project teleclaude',
                ],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
            "save": CommandDef(
                desc="Save a memory observation",
                args="<text>",
                flags=[
                    _H,
                    Flag("--title", desc="Observation title"),
                    Flag("--type", desc="Type: preference, decision, discovery, gotcha, pattern, friction, context"),
                    Flag("--project", desc="Project name"),
                ],
                examples=[
                    'telec memories save "Root cause identified for session update reason suppression." --title "Session reason fix" --type discovery --project teleclaude',
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
                args="<id>",
                flags=[
                    _H,
                    Flag("--before", desc="Observations before anchor (default: 3)"),
                    Flag("--after", desc="Observations after anchor (default: 3)"),
                    Flag("--project", desc="Filter by project name"),
                ],
                examples=["telec memories timeline 42 --before 3 --after 3"],
                auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
            ),
        },
    ),
}
# Help-only expansion for action groups; config people/env are now real leaf subcommands.
HELP_SUBCOMMAND_EXPANSIONS: dict[str, dict[str, list[tuple[str, str]]]] = {}

"""CLI surface — CLI_SURFACE dict and HELP_SUBCOMMAND_EXPANSIONS."""

from __future__ import annotations

from enum import StrEnum

from teleclaude.cli import CommandScope
from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.core.roles import Capability
from teleclaude.types.todo_kind import TODO_KIND_USAGE

from . import flags as F
from .surface_types import (
    _HR_ADMIN,
    _HR_ALL,
    _HR_ALL_NON_ADMIN,
    _HR_MEMBER,
    CommandAuth,
    CommandDef,
    Flag,
    FlagConditionedAuth,
    HookEntryVerb,
    JobsSubcommand,
    TelecCommand,
    strip_hidden_flag_tokens,
)

__all__ = ["CLI_SURFACE", "CommandAuth", "CommandDef", "Flag", "TelecCommand", "export_surface_markdown"]


class EventCommand(StrEnum):
    """Closed subcommand names for the event catalog interface."""

    LIST = "list"
    SCHEMA = "schema"


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


_HELP_DESK_LINKS_NOTE = "Renders only on the mesh master and where the desk is enabled."
# Creation is judged at the home it lands in: the caller's own person scope, the named company, or the platform.
_PROJECT_CREATE_AUTH = CommandAuth(
    capability=Capability.CONFIG,
    human=_HR_MEMBER,
    scope=CommandScope.CALLER_PERSON,
    when_flag=(
        FlagConditionedAuth(
            F.FLAG_PROJECT_COMPANY.long,
            CommandScope.NAMED_COMPANY,
            _HR_MEMBER,
            scope_flag=F.FLAG_PROJECT_COMPANY.long,
        ),
        FlagConditionedAuth(F.FLAG_PROJECT_PATH.long, CommandScope.PLATFORM, _HR_ADMIN),
    ),
)
_PROJECT_ADOPT_AUTH = CommandAuth(capability=Capability.CONFIG, human=_HR_MEMBER, scope=CommandScope.CALLER_PERSON)
_JOBS_READ_AUTH = CommandAuth(capability=Capability.JOBS_READ, human=_HR_MEMBER)
_JOBS_CONFIG_AUTH = CommandAuth(capability=Capability.JOBS, human=_HR_MEMBER, scope=CommandScope.INVOCATION)
_JOBS_RUN_AUTH = CommandAuth(capability=Capability.JOBS, human=_HR_MEMBER, scope=CommandScope.INVOCATION)

_RECEIPT_OUTCOME_DELIVERY = (
    "without waiting; the outcome is delivered to the calling session and read with "
    "`telec operations get <operation_id>`."
)
_RECEIPT_RETURN_NOTE = f"Returns an operation receipt {_RECEIPT_OUTCOME_DELIVERY}"
_RECEIPT_RETURN_SLUG_FORM_NOTE = f"The --slug form returns an operation receipt {_RECEIPT_OUTCOME_DELIVERY}"
TODO_COMMAND = "todo"


_HOOK_ENTRY_DESCRIPTIONS: dict[HookEntryVerb, str] = {
    HookEntryVerb.PRE_COMMIT: "Run the thin pre-commit backstop",
    HookEntryVerb.POST_COMMIT: "Run deterministic post-commit maintenance",
    HookEntryVerb.POST_MERGE: "Run deterministic post-merge automation",
}


def _hook_entry_commands() -> dict[str, CommandDef]:
    """Declare the git-hook entry verbs of ``telec repo``.

    Returns fresh nodes per call: surface post-processing may mutate a node per path.
    """
    return {
        verb: CommandDef(
            desc=desc,
            flags=[F.FLAG_HELP],
            hidden=True,
            auth=CommandAuth(human=frozenset(), caller_independent=True),
        )
        for verb, desc in _HOOK_ENTRY_DESCRIPTIONS.items()
    }


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
                notes=[
                    "Procedure agents that run unattended are listed only with --all (or by session id).",
                    "An agent caller's default listing keeps its own children even with --job; "
                    "`--all --job <procedure>` finds a procedure's agents.",
                ],
                auth=CommandAuth(capability=Capability.SESSION_OBSERVE, human=_HR_MEMBER),
            ),
            "show": CommandDef(
                desc="Show one session's stored record (default: your own session)",
                args="[<session_id>|self] [--computer <host>] [--full]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_COMPUTER,
                    F.FLAG_SESSIONS_SHOW_FULL,
                ],
                notes=[
                    "Default output groups the record as identity, origin, role, state, and wiring.",
                    "--full shows the complete stored record, decoded, without the last-output text, the "
                    "accepted-input fingerprint, the help-desk relay exchange, and the agent-status counter.",
                    "A session is shown only when you could list it; `telec sessions list` shows what you can reach.",
                    "For what a session said, use `telec sessions tail <session_id>` or `telec history show`.",
                    "For the roster and a session's children, use `telec sessions list`.",
                ],
                examples=[
                    "telec sessions show",
                    "telec sessions show <session_id>",
                    "telec sessions show <session_id> --full --computer <host>",
                ],
                auth=CommandAuth(
                    capability=Capability.SESSION_OBSERVE,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_SESSION,
                ),
            ),
            "coordinate": CommandDef(
                desc="Adopt this session as the project's single coordinator (human-directed only; refuses if one is live)",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(capability=Capability.SESSION_OBSERVE, human=_HR_MEMBER),
            ),
            "start": CommandDef(
                desc="Start a new agent session",
                args=(
                    "[--computer <host>] [--path <path>] [--agent <name>] [--mode <mode>]"
                    " [--message <msg>] [--direct] [--detach] [--company <slug>]"
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
                    F.FLAG_COMPANY,
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
                auth=CommandAuth(
                    capability=Capability.SESSION_ACT,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_PATH,
                    scope_flag=F.FLAG_PATH.long,
                ),
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
                auth=CommandAuth(
                    capability=Capability.PEER_TALK,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_SESSION,
                ),
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
                auth=CommandAuth(
                    capability=Capability.PEER_TALK,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_SESSION,
                ),
            ),
            "run": CommandDef(
                desc="Run an entry procedure on a new agent session",
                args=(
                    "[--command <procedure-id>] [--path <path>] [--args <val>] [--agent <name>]"
                    " [--mode <mode>] [--computer <host>] [--subfolder <dir>] [--detach]"
                    " [--additional-context <ctx>] [--company <slug>]"
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
                    F.FLAG_COMPANY,
                ],
                notes=[
                    "Creates a fresh session that carries the role the procedure declares and starts from a short loader that directs the agent to retrieve its procedure instructions.",
                    "Name the procedure by its domain-qualified snippet ID; a retired command name is refused.",
                    "Worker lifecycle procedures: build, review-build, finalize (sdlc/procedure/lifecycle/work/...).",
                    (
                        "--detach: do not use unless explicitly instructed. Sanctioned only for a "
                        "personal-assistant dispatching an orchestrator to a project. --detach disables "
                        "notifications — you will not learn when the child finishes, so omit it whenever "
                        "your next step depends on the result."
                    ),
                ],
                examples=[
                    "telec sessions run --command sdlc/procedure/lifecycle/work/build --args my-slug",
                    "telec sessions run --command sdlc/procedure/lifecycle/prepare/review-plan --args my-slug",
                ],
                auth=CommandAuth(
                    capability=Capability.SESSION_ACT,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_PATH,
                    scope_flag=F.FLAG_PATH.long,
                ),
            ),
            "run-pa": CommandDef(
                desc="Start the caller's personal assistant in their own workspace",
                args="[<brief>]",
                flags=[F.FLAG_HELP],
                default_help_note=False,
                examples=["telec sessions run-pa", 'telec sessions run-pa "Check the latest message"'],
                auth=CommandAuth(
                    capability=Capability.SESSION_ACT,
                    human=_HR_MEMBER,
                    scope=CommandScope.PLATFORM,
                ),
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
                auth=CommandAuth(
                    capability=Capability.SESSION_ACT,
                    human=_HR_ADMIN,
                    scope=CommandScope.TARGET_SESSION,
                ),
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
                auth=CommandAuth(
                    capability=Capability.SESSION_ACT,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_SESSION,
                ),
            ),
            "unsubscribe": CommandDef(
                desc="Stop receiving notifications from a session",
                args="<session_id>",
                flags=[F.FLAG_HELP, F.FLAG_COMPUTER],
                auth=CommandAuth(
                    capability=Capability.SELF_ACTS,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_SESSION,
                ),
            ),
            "restart": CommandDef(
                desc="Restart an agent session ('self' to restart own session)",
                args="<session_id> [--handoff [<agent>]]",
                flags=[F.FLAG_HELP, F.FLAG_COMPUTER, F.FLAG_HANDOFF],
                auth=CommandAuth(
                    capability=Capability.SESSION_ACT,
                    human=_HR_ADMIN,
                    scope=CommandScope.TARGET_SESSION,
                ),
            ),
            "result": CommandDef(
                desc="Send a formatted result to the session's user",
                args="<content> [--format <fmt>]",
                flags=[F.FLAG_HELP, F.FLAG_RESULT_FORMAT, F.FLAG_RESULT_CONTENT_ALIAS],
                auth=CommandAuth(capability=Capability.SELF_ACTS, human=_HR_MEMBER),
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
                auth=CommandAuth(capability=Capability.SELF_ACTS, human=_HR_MEMBER),
            ),
            "escalate": CommandDef(
                desc="Escalate a help-desk visitor to everyone in the desk's scope in its escalation thread",
                args="[--customer <name>] [--reason <text>] [--summary <text>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_ESCALATE_CUSTOMER,
                    F.FLAG_ESCALATE_REASON,
                    F.FLAG_ESCALATE_SUMMARY,
                ],
                auth=CommandAuth(
                    capability=Capability.SELF_ACTS,
                    human=_HR_ALL_NON_ADMIN,
                ),
                desk=True,
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
                auth=CommandAuth(capability=Capability.REMINDERS, human=_HR_MEMBER),
            ),
            "list": CommandDef(
                desc="List every live reminder owned by the calling session",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(capability=Capability.REMINDERS, human=_HR_MEMBER),
            ),
            "cancel": CommandDef(
                desc="Idempotently cancel one or all caller-owned reminders",
                args="[<slug>] [--all]",
                flags=[F.FLAG_HELP, F.FLAG_REMINDER_CANCEL_ALL],
                auth=CommandAuth(capability=Capability.REMINDERS, human=_HR_MEMBER),
            ),
        },
    ),
    "computers": CommandDef(
        desc="Manage computer inventory",
        subcommands={
            "list": CommandDef(
                desc="List available computers (local + cached remote)",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(
                    capability=Capability.SESSION_OBSERVE,
                    human=_HR_MEMBER,
                    scope=CommandScope.PLATFORM,
                ),
            ),
        },
    ),
    "projects": CommandDef(
        desc="Manage project inventory and plumbing",
        subcommands={
            "list": CommandDef(
                desc="List projects on local and remote computers",
                args="[--computer <host>]",
                flags=[F.FLAG_HELP, F.FLAG_COMPUTER],
                auth=CommandAuth(
                    capability=Capability.SESSION_OBSERVE,
                    human=_HR_MEMBER,
                    scope=CommandScope.PLATFORM,
                ),
            ),
        },
    ),
    "agents": CommandDef(
        desc="Manage agent dispatch status and availability",
        subcommands={
            "availability": CommandDef(
                desc="Get current availability for all agents",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(
                    capability=Capability.SESSION_OBSERVE,
                    human=_HR_MEMBER,
                    scope=CommandScope.PLATFORM,
                ),
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
                auth=CommandAuth(capability=Capability.SESSION_ACT, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
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
                auth=CommandAuth(capability=Capability.OPERATION_READ, human=_HR_MEMBER),
            ),
        },
    ),
    "version": CommandDef(
        desc="Print version, channel, and commit",
        flags=[F.FLAG_HELP],
        auth=CommandAuth(human=_HR_ALL, caller_independent=True),
        desk=True,
    ),
    "message": CommandDef(
        desc="Send a message to a person",
        args="<text> [--recipient <slug>] [--file <path>] [--subject <text>] [--channel <name>]",
        flags=[
            F.FLAG_HELP,
            F.FLAG_MSG_RECIPIENT,
            F.FLAG_MSG_FILE,
            F.FLAG_MSG_SUBJECT,
            F.FLAG_MSG_CHANNEL,
        ],
        notes=[
            "Recipient-owned routing: defaults to the person's configured preferred_channel (email when unset).",
            "Without --recipient, the recipient is the person the calling session runs under; system authority defaults to platform admins.",
            "The message text is the file's caption on Telegram/Discord; on email it is the body and the file is an attachment.",
            "A file directed at a WhatsApp delivery is an actionable error — WhatsApp has no media-send capability here.",
            "Discover a person's slug via 'telec config person list' to use with --recipient.",
        ],
        examples=[
            'telec message "Heads up: the deploy finished" --recipient alex',
            'telec message "See attached" --recipient alex --file ./report.pdf',
            'telec message "Weekly digest" --recipient alex --channel email --subject "Weekly digest"',
            'telec message "The scheduled report is ready"',
        ],
        auth=CommandAuth(capability=Capability.MESSAGING, human=_HR_MEMBER),
    ),
    "audio": CommandDef(
        desc="Transcribe supplied audio",
        subcommands={
            "stt": CommandDef(
                desc="Transcribe audio from a URL or local file",
                args="[--url <url>] [--path <path>] [--language <code>]",
                flags=[F.FLAG_HELP, F.FLAG_AUDIO_URL, F.FLAG_AUDIO_PATH, F.FLAG_AUDIO_LANGUAGE],
                notes=[
                    "The transcript is written to standard output.",
                    "Exit status 3: source unavailable; 4: unsupported media; 5: no STT service; 6: transcription failed.",
                    "Usage faults and request-level errors exit 1.",
                ],
                examples=[
                    "telec audio stt --url https://example.com/recording.ogg",
                    "telec audio stt --path ./recording.m4a --language nl",
                ],
                auth=CommandAuth(capability=Capability.AUDIO, human=_HR_MEMBER),
            ),
        },
    ),
    "docs": CommandDef(
        desc="Query documentation snippets",
        subcommands={
            "index": CommandDef(
                desc="List snippet IDs and metadata (phase 1)",
                args=f"[--baseline-only] [--third-party] [--areas <{'|'.join(TAXONOMY_TYPES)}>] [--domains <domain>] [--scope <{F.SCOPE_VALUES}>] [--project <slug>] [--person <slug>] [--company <slug>] [--local] [--target <slug>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_DOCS_BASELINE_ONLY,
                    F.FLAG_DOCS_THIRD_PARTY,
                    F.FLAG_DOCS_AREAS,
                    F.FLAG_DOCS_DOMAINS,
                    F.FLAG_DOCS_SCOPE,
                    F.FLAG_DOCS_PROJECT,
                    F.FLAG_DOCS_PERSON,
                    F.FLAG_DOCS_COMPANY,
                    F.FLAG_DOCS_LOCAL,
                    F.FLAG_DOCS_TARGET,
                ],
                notes=[
                    "Pending snippets (those with delivered_by) append ` (delivered by: slug1,slug2)` at the end of the phase-1 line.",
                ],
                auth=CommandAuth(capability=Capability.DOCS_READ, human=_HR_ALL),
                desk=True,
            ),
            "get": CommandDef(
                desc="Fetch full snippet content by ID (phase 2)",
                args=f"<id> [id...] [--scope <{F.SCOPE_VALUES}>] [--project <slug>] [--person <slug>] [--company <slug>] [--target <slug>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_DOCS_GET_CLOSURE,
                    F.FLAG_DOCS_GET_SCOPE,
                    F.FLAG_DOCS_PROJECT,
                    F.FLAG_DOCS_PERSON,
                    F.FLAG_DOCS_COMPANY,
                    F.FLAG_DOCS_GET_TARGET,
                ],
                runtime_notes=[
                    "The generated Activatable Procedures catalog uses `--closure` to load one delivered procedure and its eligible required-read closure in one pass.",
                ],
                auth=CommandAuth(capability=Capability.DOCS_READ, human=_HR_ALL),
                desk=True,
            ),
        },
        notes=[
            "Two-phase flow: use 'telec docs index' to discover IDs, then 'telec docs get <id...>' to fetch content.",
            "Omitting --areas and/or --domains returns all values for that dimension; pass a comma-separated subset to filter.",
            "Example phase 1: telec docs index --areas policy,procedure --domains sdlc",
            "Example phase 2: telec docs get sdlc/policy/testing local/projects/teleclaude/spec/command-surface",
        ],
    ),
    TODO_COMMAND: CommandDef(
        desc="Manage work items",
        subcommands={
            "sync": CommandDef(
                desc="Copy todo state to other computers",
                args="--project <slug>[,<slug>] --to <computer>[,<computer>]",
                flags=[F.FLAG_HELP, F.FLAG_TODO_SYNC_PROJECT, F.FLAG_TODO_SYNC_TO],
                notes=[
                    "The origin's todo state replaces each target checkout's todo state; todo state is not merged.",
                    "The origin daemon does not need to run. The admin is responsible for stopping work on the origin before syncing.",
                    "The target database is checked for integrity after each copy; each project and target pair reports its own outcome.",
                    "The installer provisions sqlite3_rsync on every computer; run make install on both sides before syncing.",
                ],
                auth=CommandAuth(human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
            "sync-replica": CommandDef(
                desc="Read the local todo database for a remote transfer",
                args="<locate|check> <slug>",
                flags=[F.FLAG_HELP],
                hidden=True,
                auth=CommandAuth(human=frozenset(), caller_independent=True),
            ),
            "switch-to-github": CommandDef(
                desc="Switch this project to the GitHub workflow store and move its open work",
                flags=[F.FLAG_HELP],
                notes=[
                    "The switch is one-way; another run continues an interrupted move.",
                    "Read the outcome with `telec operations get <operation-id>`.",
                    "Commit the project declaration change as you would any declaration edit.",
                ],
                auth=CommandAuth(human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
            "board": CommandDef(
                desc="Keep the project's GitHub board true to its workflow record",
                subcommands={
                    "repair": CommandDef(
                        desc="Rebuild every item, lane and marker on the project's board from its GitHub store",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Corrects a hand edit or a missed update on the board; the workflow itself is unchanged.",
                            "Names each write it could not make and why, such as a missing App permission or a "
                            "repository owned by a personal account, and the computer that creates the board "
                            "while it does not exist yet.",
                            _RECEIPT_RETURN_NOTE,
                        ],
                        examples=["telec todo board repair"],
                        auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
                    ),
                },
            ),
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
                    "Returns a filing receipt; the outcome, created or refused, is delivered to the calling session. "
                    "Act on the todo once that outcome reports it created; filings in one project complete in the "
                    "order they were accepted.",
                    "Active creation with declared pending documentation requires an associated commit and current "
                    "independent approval. A refusal writes no todo; submit a fresh create request after review.",
                    "Icebox creation remains available while work is forming; unfreeze checks the same documentation "
                    "evidence before lifecycle entry.",
                    "--human-involved requires a non-empty reason and resolves the record from observed recency: "
                    "a stale declaration records false and the todo is still created. The reason is never "
                    "stored; omission records false and does not affect later actions.",
                    "Content IS the input artifact — the author's INTENT: WHAT and WHY in operator language, "
                    "affected surfaces, acceptance shape, brownfield grounding. HOW and doc routing are "
                    "preparation's to derive. Per "
                    "sdlc/policy/preparation-artifact-quality (Input artifact quality): HOW is "
                    "the prepare phase's hypothesis to verify, doc routing is not the input's "
                    "(general/policy/documentation-discipline), and an ADR is governed "
                    "by general/policy/adr-discipline (default none, never by process step). Any HOW or doc "
                    "instruction left in content is an unverified hypothesis, not a directive. (--plan is the "
                    "deliberate exception: its content is a complete implementation-plan, not an input.)",
                    "Use --icebox for ideas and future work at any stage; an iced todo enters the lifecycle when "
                    "unfrozen, once valid. Hidden --hold is an exceptional brake for valid work awaiting an "
                    "external gate. "
                    "--group <parent-slug> creates a complete grouped child in one call and makes the parent a structural holder "
                    "via the existing derivation; the first grouped child strips the parent's todo_state "
                    "while preserving all its artifacts as frozen evidence, and is refused once the parent's "
                    "lifecycle_phase has reached prepared or the work lane, so build, review, and finalize "
                    "state is never shredded. Grouping also moves the parent's pending documentation ownership to the first "
                    "grouped child: every in-body marker, companion filename, and delivered_by membership naming the parent "
                    "is rewritten to that child and committed as part of the same transition.",
                    "The filer always supplies --kind, choosing one of the four lifecycle entry points.",
                    "--plan is valid with --kind change or --kind task.",
                    "Settled, bounded work is executed in context (sdlc/policy/todo-creation-discipline).",
                    "Process changes are agent-owned (sdlc/policy/process-change-authority): file them on the "
                    "ordinary path; only a consequence on the closed list of general/policy/human-contract waits "
                    "for the human.",
                ],
                auth=CommandAuth(
                    capability=Capability.TODO_WRITE,
                    human=_HR_MEMBER,
                    scope=CommandScope.TARGET_PATH,
                    scope_flag=F.FLAG_TODO_PROJECT_ROOT.long,
                ),
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
                    "Output is sectioned into active/delivered/icebox/removed trees; delivered history groups by membership and sorts newest first.",
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
                auth=CommandAuth(capability=Capability.TODO_READ, human=_HR_MEMBER),
            ),
            "design": CommandDef(
                desc="Run the creative state machine",
                args="[<slug>]",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(capability=Capability.TODO_ORCHESTRATION, human=_HR_MEMBER),
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
                notes=[_RECEIPT_RETURN_NOTE],
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
            "freeze": CommandDef(
                desc="Move todo to icebox",
                args="<slug>",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
            "unfreeze": CommandDef(
                desc="Promote todo from icebox",
                args="<slug>",
                flags=[F.FLAG_HELP],
                notes=[
                    "Pending documentation must have current associated independent approval before the todo leaves the icebox.",
                ],
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
            "deliver": CommandDef(
                desc="Move todo to delivered",
                args="<slug> [--commit <hash>]",
                flags=[F.FLAG_HELP, F.FLAG_TODO_DELIVER_COMMIT],
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
            "update": CommandDef(
                desc="Update a todo slug, group, dependencies, or kind",
                args=f"<slug> [--slug <new>] [--group <parent-slug>] [--after <dep>]... [--schedule <value>] [--kind <{TODO_KIND_USAGE}>] [--hold --reason <text>] [--release] [--unclaim] [--force]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_TODO_UPDATE_SLUG,
                    F.FLAG_TODO_UPDATE_GROUP,
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
                    "Mutates slug, group, deps, kind, or hold; --after replaces the full dependency set.",
                    "--group uses the same holder eligibility as create --group; pass an empty value to clear membership.",
                    "Group membership and an after dependency on the same holder or ancestor are mutually exclusive.",
                    "Agent callers may update only an unclaimed todo or one held by their claiming group; a live foreign claim is refused with the holder named.",
                    "Kind and slug changes are refused after build starts; --after remains allowed.",
                    "--hold requires --reason; --reason is refused without --hold, and --hold and --release are mutually exclusive.",
                    "--unclaim clears the caller-owned runner claim; --release only clears the dispatch brake.",
                    "--force only applies to kind orphan handling.",
                    "Combining --slug with other legs is staged, not a single atomic patch.",
                    _RECEIPT_RETURN_SLUG_FORM_NOTE,
                ],
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
            "prepare": CommandDef(
                desc="Run the Phase A (prepare) state machine",
                args="<slug>",
                flags=[F.FLAG_HELP],
                notes=[_RECEIPT_RETURN_NOTE],
                auth=CommandAuth(capability=Capability.TODO_ORCHESTRATION, human=_HR_MEMBER),
            ),
            "work": CommandDef(
                desc="Run the Phase B (work) state machine",
                args="[<slug>]",
                flags=[F.FLAG_HELP],
                notes=[_RECEIPT_RETURN_NOTE],
                auth=CommandAuth(capability=Capability.TODO_ORCHESTRATION, human=_HR_MEMBER),
            ),
            "integrate": CommandDef(
                desc="Run the Phase C (integrate) state machine",
                args="[<slug>] [--abandon]",
                flags=[F.FLAG_HELP, F.FLAG_TODO_INTEGRATE_ABANDON],
                notes=[_RECEIPT_RETURN_NOTE],
                auth=CommandAuth(capability=Capability.INTEGRATION, human=_HR_MEMBER),
            ),
            "artifacts": CommandDef(
                desc="Manage todo artifacts in the database",
                subcommands={
                    "list": CommandDef(
                        desc="List artifacts for a todo",
                        args="<slug>",
                        flags=[F.FLAG_HELP],
                        examples=["telec todo artifacts list my-slug"],
                        auth=CommandAuth(capability=Capability.ARTIFACT_READ, human=_HR_MEMBER),
                    ),
                    "read": CommandDef(
                        desc="Read a todo artifact",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings|check-failures>",
                        flags=[F.FLAG_HELP],
                        examples=["telec todo artifacts read my-slug requirements"],
                        auth=CommandAuth(capability=Capability.ARTIFACT_READ, human=_HR_MEMBER),
                    ),
                    "write": CommandDef(
                        desc="Write a todo artifact",
                        args="<slug> <name: input|prd|architecture|diagnosis|investigation|implementation-plan|task-plan|quality-checklist|design-spec|deferrals|log|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> <content>",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Legacy bug artifacts are read-only; write bug todo content to input.",
                            "check-failures is written only by the platform's failed-check filer.",
                        ],
                        examples=['telec todo artifacts write my-slug prd "# PRD content"'],
                        auth=CommandAuth(capability=Capability.ARTIFACT_WRITE, human=_HR_MEMBER),
                    ),
                    "diff": CommandDef(
                        desc="Show a unified diff between two artifact versions",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings|check-failures> <old-digest> <new-digest>",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Looks up both versions by digest in the artifact version history "
                            "and prints a unified diff between them.",
                            "Used by the prepare loop to show reviewers what changed since the last approved digest.",
                        ],
                        examples=[
                            "telec todo artifacts diff my-slug requirements abc123 def456",
                        ],
                        auth=CommandAuth(capability=Capability.ARTIFACT_READ, human=_HR_MEMBER),
                    ),
                    "remove": CommandDef(
                        desc="Remove a todo artifact and its version history",
                        args="<slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings>",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Refuses input because it is the seed artifact for a todo.",
                            "Refuses check-failures because only the platform writes it.",
                            "Missing artifacts are treated as a successful no-op.",
                        ],
                        examples=["telec todo artifacts remove my-slug requirements"],
                        auth=CommandAuth(capability=Capability.ARTIFACT_WRITE, human=_HR_MEMBER),
                    ),
                },
            ),
            "show": CommandDef(
                desc="Show diagnostic state payload for a todo, including who holds an active todo's claim; artifact bodies are omitted by default",
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
                auth=CommandAuth(capability=Capability.TODO_READ, human=_HR_MEMBER),
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
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
            "stamp": CommandDef(
                desc="Stamp a verdict or readiness marker into todo state",
                args=(
                    "<slug> [--verdict <v> --phase <p>] [--prd-approved]"
                    " [--task-approved]"
                    " [--architecture-skipped <reason>]"
                    " [--drift-reviewed <artifact> <verdict> <reason>]"
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
                    "telec todo stamp my-slug --verdict changes_requested --phase build_review",
                    "telec todo stamp my-slug --finalize-ready",
                    'telec todo stamp my-slug --kickback --reason "<why the plan cannot be built>"',
                    "telec todo stamp my-task --task-outcome success",
                    'telec todo stamp my-task --task-outcome error --reason "<why a human is needed>"',
                    "telec todo stamp my-bug --diagnosis-settled",
                    'telec todo stamp my-bug --diagnosis-unresolved --reason "<why>"',
                ],
                auth=CommandAuth(capability=Capability.STAMP, human=_HR_MEMBER),
            ),
            "return-to-work": CommandDef(
                desc="Return a held, unintegrated finalized todo to its code-conformance build and review cycle",
                args="<slug> --reason <reason> --evidence <address>",
                flags=[F.FLAG_HELP, F.FLAG_TODO_RETURN_REASON, F.FLAG_TODO_RETURN_EVIDENCE],
                notes=[
                    "Requires an active, held finalize-ready todo with no active lifecycle claim or integration recovery.",
                    "Preserves preparation, candidate refs, worktree, commits, review-round history, and the hold.",
                ],
                examples=[
                    'telec todo return-to-work my-feature --reason "review found a code-conformance gap" --evidence "review-findings#finding-1"',
                ],
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
        },
    ),
    "bugs": CommandDef(
        desc="Bug reporting and tracking",
        subcommands={
            "report": CommandDef(
                desc=(
                    "Interrogate the pre-filing decisions before scaffolding a bug; a completed filing "
                    "enters the bug lane and the lifecycle router dispatches /prepare"
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
                    "pre-filing decisions (bug or change, fix-directly, duplication, ordering, validity and "
                    "ownership) and "
                    "only that output names how to complete the filing.",
                    "A completed filing returns a receipt; the outcome, created or refused, is delivered to the "
                    "calling session.",
                    "File against the project that OWNS the defective code, not the one you happen to be "
                    "standing in. Platform behavior misbehaving inside a side project is a platform bug: "
                    "pass --project so the orchestrator that picks it up can actually deliver the fix. A bug "
                    "filed where the code does not live cannot be fixed there and gets re-filed later, "
                    "carrying stale conclusions with it. A symptom that stops once the side project's own "
                    "configuration matches a TeleClaude default (a .gitignore entry, a blessed template line) "
                    "is the side project's to fix, there. When you cannot tell which "
                    "project owns it, ask.",
                    "The filing surface interrogates for duplication up front (todo list, in-flight bug lanes, "
                    "suppressions); diagnose remains the deeper same-defect dedup that can still retire a twin "
                    "the up-front check missed.",
                    "Your reported todo may therefore still be removed as a duplicate at diagnose — that is expected dedup, not a dropped report. The surviving todo carries the fix.",
                    "A report names the observed wrong behavior; what is missing and how to fix it are "
                    "preparation's to derive. A bug whose cause is a process defect may correct that "
                    "defect within its symptom and causal scope (sdlc/policy/process-change-authority).",
                    "Require the observed symptom plus its trigger context verbatim in the description or --body: "
                    "what happened, what was expected, and what preceded it. A report with no trigger context is "
                    "unauditable later — this is the reporting invitation the schema alone cannot supply.",
                ],
                auth=CommandAuth(
                    capability=Capability.TODO_WRITE,
                    human=_HR_MEMBER,
                    scope=CommandScope.NAMED_TRUSTED_DIRECTORY,
                    scope_flag=F.FLAG_BUG_PROJECT.long,
                ),
            ),
            "list": CommandDef(
                desc="List in-flight bug fixes with status",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(capability=Capability.TODO_READ, human=_HR_MEMBER),
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
                auth=CommandAuth(
                    capability=Capability.TODO_WRITE,
                    human=_HR_MEMBER,
                    scope=CommandScope.NAMED_TRUSTED_DIRECTORY,
                    scope_flag=F.FLAG_PROJECT_TRUSTED.long,
                ),
            ),
            "suppressions": CommandDef(
                desc="List the active known-issue suppressions for a project",
                args="[--project <name>]",
                flags=[F.FLAG_HELP, F.FLAG_PROJECT_TRUSTED],
                auth=CommandAuth(
                    capability=Capability.TODO_READ,
                    human=_HR_MEMBER,
                    scope=CommandScope.NAMED_TRUSTED_DIRECTORY,
                    scope_flag=F.FLAG_PROJECT_TRUSTED.long,
                ),
            ),
            "unsuppress": CommandDef(
                desc="Remove a known-issue suppression by id so its signal is eligible for filing again",
                args="<id> [--project <name>]",
                flags=[F.FLAG_HELP, F.FLAG_PROJECT_TRUSTED],
                auth=CommandAuth(
                    capability=Capability.TODO_WRITE,
                    human=_HR_MEMBER,
                    scope=CommandScope.NAMED_TRUSTED_DIRECTORY,
                    scope_flag=F.FLAG_PROJECT_TRUSTED.long,
                ),
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
                    "Author defaults to the principal the daemon resolves for the caller.",
                    "Emits a content.dumped notification event if the notification service is available.",
                    "Slug collision is handled automatically by appending a counter suffix.",
                ],
                examples=[
                    'telec content dump "My brain dump about agent shorthand"',
                    'telec content dump "Deep dive into mesh" --slug mesh-deep-dive --tags "mesh,architecture"',
                    'telec content dump "Content for review" --author alice',
                ],
                auth=CommandAuth(capability=Capability.TODO_WRITE, human=_HR_MEMBER),
            ),
        },
    ),
    "jobs": CommandDef(
        desc="Recurring job commands",
        subcommands={
            JobsSubcommand.LIST.value: CommandDef(
                desc="List jobs visible to the current project",
                flags=[F.FLAG_HELP],
                auth=_JOBS_READ_AUTH,
            ),
            JobsSubcommand.STATUS.value: CommandDef(
                desc="Show runtime status for jobs visible to the current project",
                flags=[F.FLAG_HELP],
                auth=_JOBS_READ_AUTH,
            ),
            JobsSubcommand.ENABLE.value: CommandDef(
                desc="Subscribe the current project to a published job",
                args="<name>",
                flags=[F.FLAG_HELP],
                auth=_JOBS_CONFIG_AUTH,
            ),
            JobsSubcommand.DISABLE.value: CommandDef(
                desc="Unsubscribe the current project from a published job",
                args="<name>",
                flags=[F.FLAG_HELP],
                auth=_JOBS_CONFIG_AUTH,
            ),
            JobsSubcommand.RUN.value: CommandDef(
                desc="Run a job in the current project",
                args="<name>",
                flags=[F.FLAG_HELP],
                notes=[_RECEIPT_RETURN_NOTE],
                auth=_JOBS_RUN_AUTH,
            ),
            JobsSubcommand.REPORT.value: CommandDef(
                desc="Write a structured recurring job result record",
                args="<name> --success <true|false> --message <text> [--items-processed <n>] [--error <text> ...] [--state-json <object>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_JOB_SUCCESS,
                    F.FLAG_JOB_MESSAGE,
                    F.FLAG_JOB_ITEMS_PROCESSED,
                    F.FLAG_JOB_ERROR,
                    F.FLAG_JOB_STATE_JSON,
                ],
                notes=[
                    "The positional is the job's declared name and identity. Validated against configured jobs; writes the current record under state/runs/<project>/<name>.json.",
                    "--state-json replaces the opaque checkpoint object; omission preserves the previous checkpoint.",
                    "This command writes locally and does not call the daemon.",
                ],
                auth=CommandAuth(capability=Capability.JOB_REPORT, human=_HR_MEMBER),
            ),
        },
    ),
    "events": CommandDef(
        desc="Event catalog and platform commands",
        subcommands={
            EventCommand.LIST.value: CommandDef(
                desc="List declared event types: name, version, what they are about, description",
                args="[--domain <name>]",
                flags=[F.FLAG_HELP, F.FLAG_EVENTS_DOMAIN],
                auth=CommandAuth(human=_HR_MEMBER, caller_independent=True),
            ),
            EventCommand.SCHEMA.value: CommandDef(
                desc="Show one event type's declaration: subject, home, related kinds, state, and data fields",
                args="<event>",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(human=_HR_MEMBER, caller_independent=True),
            ),
        },
    ),
    "signals": CommandDef(
        desc="Signal pipeline status and diagnostics",
        subcommands={
            "status": CommandDef(
                desc="Show signal pipeline counts and last ingest time",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(human=_HR_MEMBER, caller_independent=True),
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
                auth=CommandAuth(human=_HR_MEMBER, caller_independent=True),
            ),
            "list-tools": CommandDef(
                desc="Initialize one MCP server and list its tools",
                args="<slug> [--json]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MCP_JSON,
                ],
                auth=CommandAuth(capability=Capability.MCP, human=_HR_MEMBER),
            ),
            "call": CommandDef(
                desc="Call one MCP tool through the lazy runtime",
                args="<slug> <tool> --json <arguments-json>",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MCP_CALL_JSON,
                ],
                auth=CommandAuth(capability=Capability.MCP, human=_HR_MEMBER),
            ),
        },
        auth=CommandAuth(capability=Capability.MCP, human=_HR_MEMBER),
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
                auth=CommandAuth(human=_HR_ALL, caller_independent=True),
            ),
            "whoami": CommandDef(
                desc="Show the identity carried by this session or terminal",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(human=_HR_ALL, caller_independent=True),
                desk=True,
            ),
            "logout": CommandDef(
                desc="Clear terminal login identity for this TTY",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(human=_HR_ALL, caller_independent=True),
            ),
        },
    ),
    "config": CommandDef(
        desc="Manage configuration",
        subcommands={
            "wizard": CommandDef(
                desc="Open the interactive configuration wizard",
                flags=[F.FLAG_HELP],
                auth=CommandAuth(human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                hidden=True,
            ),
            "computer": CommandDef(
                desc="Machine configuration",
                subcommands={
                    "list": CommandDef(
                        desc="List computer subjects (singleton)",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(
                            capability=Capability.CONFIG_READ,
                            human=_HR_MEMBER,
                            scope=CommandScope.PLATFORM,
                        ),
                    ),
                    "get": CommandDef(
                        desc="Get the machine configuration",
                        args="[paths...] [--format <fmt>]",
                        flags=[F.FLAG_HELP, F.FLAG_CONFIG_FORMAT],
                        auth=CommandAuth(
                            capability=Capability.CONFIG_READ,
                            human=_HR_MEMBER,
                            scope=CommandScope.PLATFORM,
                        ),
                    ),
                    "init": CommandDef(
                        desc="Converge the machine configuration without overwriting existing values",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                    "patch": CommandDef(
                        desc="Patch the machine configuration",
                        args="--revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>]",
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_CONFIG_REVISION,
                            F.FLAG_CONFIG_YAML,
                            F.FLAG_CONFIG_FROM_FILE,
                            F.FLAG_CONFIG_FORMAT,
                        ],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                },
            ),
            "global": CommandDef(
                desc="Global configuration (cross-project overlay)",
                subcommands={
                    "list": CommandDef(
                        desc="List global subjects (singleton)",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(
                            capability=Capability.CONFIG_READ,
                            human=_HR_MEMBER,
                            scope=CommandScope.PLATFORM,
                        ),
                    ),
                    "get": CommandDef(
                        desc="Get the global configuration",
                        args="[paths...] [--format <fmt>]",
                        flags=[F.FLAG_HELP, F.FLAG_CONFIG_FORMAT],
                        auth=CommandAuth(
                            capability=Capability.CONFIG_READ,
                            human=_HR_MEMBER,
                            scope=CommandScope.PLATFORM,
                        ),
                    ),
                    "init": CommandDef(
                        desc="Converge the global configuration without overwriting existing values",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                    "patch": CommandDef(
                        desc="Patch the global configuration",
                        args="--revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>]",
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_CONFIG_REVISION,
                            F.FLAG_CONFIG_YAML,
                            F.FLAG_CONFIG_FROM_FILE,
                            F.FLAG_CONFIG_FORMAT,
                        ],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                },
            ),
            "person": CommandDef(
                desc="Person configuration (identity + settings)",
                subcommands={
                    "list": CommandDef(
                        desc="List registered person slugs",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                    "get": CommandDef(
                        desc="Get one person's configuration",
                        args="<slug> [paths...] [--format <fmt>]",
                        flags=[F.FLAG_HELP, F.FLAG_CONFIG_FORMAT],
                        auth=CommandAuth(
                            capability=Capability.CONFIG,
                            human=_HR_MEMBER,
                            scope=CommandScope.CONFIG_SUBJECT,
                        ),
                    ),
                    "init": CommandDef(
                        desc="Create or converge a person without overwriting existing values",
                        args="<name> --email <email> [--slug <slug>] [--role <role>] [--username <username>]",
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_PEOPLE_EMAIL,
                            F.FLAG_PEOPLE_SLUG,
                            F.FLAG_PEOPLE_ROLE,
                            F.FLAG_PEOPLE_USERNAME,
                        ],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                    "patch": CommandDef(
                        desc="Patch one person's configuration, or remove the person",
                        args="<slug> --revision <rev> [--yaml '...' | --from-file <path>] [--remove] [--delete-dir] [--format <fmt>]",
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_CONFIG_REVISION,
                            F.FLAG_CONFIG_YAML,
                            F.FLAG_CONFIG_FROM_FILE,
                            F.FLAG_CONFIG_REMOVE,
                            F.FLAG_PEOPLE_DELETE_DIR,
                            F.FLAG_CONFIG_FORMAT,
                        ],
                        auth=CommandAuth(
                            capability=Capability.CONFIG,
                            human=_HR_MEMBER,
                            scope=CommandScope.CONFIG_SUBJECT,
                        ),
                    ),
                    "invite": CommandDef(
                        desc="Generate (or rotate) invite links for a person on the mesh master",
                        args="<slug> [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        notes=[
                            "The invitation runs on the mesh master from any computer: the token is issued there, "
                            "where it is redeemed, and the links name the master's public bot endpoints.",
                            "With no unique live master the command fails and changes nothing; addressing a computer "
                            "that is not the master is refused with the master's name.",
                            "A configured provider whose endpoint cannot be resolved is reported as unavailable; the "
                            "other links are still returned, and so are all links when the email is not delivered.",
                        ],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                    "discord-voice-bot": CommandDef(
                        desc="Bind the active Discord bot credential to a person's voice configuration",
                        args="<slug> [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                },
                notes=[
                    "Patch naming `organization` is always refused — it is a read-only projection.",
                ],
            ),
            "company": CommandDef(
                desc="Company configuration (roster, projects)",
                subcommands={
                    "list": CommandDef(
                        desc="List registered company slugs",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                    "get": CommandDef(
                        desc="Get one company's configuration",
                        args="<slug> [paths...] [--format <fmt>]",
                        flags=[F.FLAG_HELP, F.FLAG_CONFIG_FORMAT],
                        auth=CommandAuth(
                            capability=Capability.CONFIG,
                            human=_HR_ADMIN,
                            scope=CommandScope.CONFIG_SUBJECT,
                        ),
                    ),
                    "init": CommandDef(
                        desc="Scaffold a company without overwriting existing values",
                        args="<name> [--slug <slug>]",
                        flags=[F.FLAG_HELP, F.FLAG_COMPANY_SLUG],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_MEMBER, scope=CommandScope.PLATFORM),
                    ),
                    "patch": CommandDef(
                        desc="Patch one company's roster or fields",
                        args="<slug> --revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>]",
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_CONFIG_REVISION,
                            F.FLAG_CONFIG_YAML,
                            F.FLAG_CONFIG_FROM_FILE,
                            F.FLAG_CONFIG_FORMAT,
                        ],
                        auth=CommandAuth(
                            capability=Capability.CONFIG,
                            human=_HR_ADMIN,
                            scope=CommandScope.CONFIG_SUBJECT,
                        ),
                    ),
                    "help-desk-links": CommandDef(
                        desc="Print the entry links of a company's help desk, hosted on the mesh master",
                        args="<slug> [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        notes=[_HELP_DESK_LINKS_NOTE],
                        auth=CommandAuth(
                            capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.CONFIG_SUBJECT
                        ),
                    ),
                },
            ),
            "project": CommandDef(
                desc="Project configuration",
                subcommands={
                    "list": CommandDef(
                        desc="List registered project slugs",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(
                            capability=Capability.CONFIG_READ,
                            human=_HR_MEMBER,
                            scope=CommandScope.PLATFORM,
                        ),
                    ),
                    "get": CommandDef(
                        desc="Get one project's configuration",
                        args="<slug> [paths...] [--format <fmt>]",
                        flags=[F.FLAG_HELP, F.FLAG_CONFIG_FORMAT],
                        auth=CommandAuth(
                            capability=Capability.CONFIG_READ,
                            human=_HR_MEMBER,
                            scope=CommandScope.CONFIG_SUBJECT,
                        ),
                    ),
                    "create": CommandDef(
                        desc="Create a new, empty project",
                        args="<name> [--company <slug> | --path <dir>]",
                        flags=[F.FLAG_HELP, F.FLAG_PROJECT_COMPANY, F.FLAG_PROJECT_PATH],
                        notes=[
                            "Without a flag the project lands in your own projects area, owned by you.",
                            "--company puts it in that company's projects area, owned by the company; "
                            "any member of the company may. --path makes an ownerless platform project at a "
                            "folder outside every home, for platform administrators; it never combines with "
                            "--company.",
                            "The name is the project's identity: an invalid name, or one another project on "
                            "this computer already holds, is refused before anything is written.",
                            "The project gets its own repository on main, declares its owner and declares no "
                            "capabilities yet. Scaffold inside it, then run `telec config project adopt` there "
                            "to declare them.",
                        ],
                        auth=_PROJECT_CREATE_AUTH,
                    ),
                    "adopt": CommandDef(
                        desc="Register the folder you stand in as a project, where it is",
                        flags=[F.FLAG_HELP],
                        notes=[
                            "Adopts the checkout that owns your current directory, or the directory itself when "
                            "no repository holds it or only the global home's does.",
                            "Inside a home the project is owned by that home and gets its own repository if it "
                            "has none; a different declared owner is refused. Outside every home the declared "
                            "owner stays. No file is moved.",
                            "Writes nothing outside the project and the project registry.",
                        ],
                        auth=_PROJECT_ADOPT_AUTH,
                    ),
                    "patch": CommandDef(
                        desc="Patch one project's configuration",
                        args="<slug> --revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>]",
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_CONFIG_REVISION,
                            F.FLAG_CONFIG_YAML,
                            F.FLAG_CONFIG_FROM_FILE,
                            F.FLAG_CONFIG_FORMAT,
                        ],
                        notes=["Writes the project's teleclaude.yml only — never commits."],
                        auth=CommandAuth(
                            capability=Capability.CONFIG,
                            human=_HR_MEMBER,
                            scope=CommandScope.CONFIG_SUBJECT,
                        ),
                    ),
                    "help-desk-links": CommandDef(
                        desc="Print the entry links of a project's help desk, hosted on the mesh master",
                        args="<slug> [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        notes=[_HELP_DESK_LINKS_NOTE],
                        auth=CommandAuth(
                            capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.CONFIG_SUBJECT
                        ),
                    ),
                },
            ),
            "validate": CommandDef(
                desc="Full validation",
                flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                auth=CommandAuth(
                    capability=Capability.CONFIG_READ,
                    human=_HR_MEMBER,
                    scope=CommandScope.PLATFORM,
                ),
            ),
            "env": CommandDef(
                desc="Manage environment variables",
                subcommands={
                    "list": CommandDef(
                        desc="List environment variables",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                    "set": CommandDef(
                        desc="Set environment variables",
                        args="<KEY=VALUE> ... [--json]",
                        flags=[F.FLAG_HELP, F.FLAG_JSON_MACHINE_READABLE],
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
                    ),
                },
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
                        auth=CommandAuth(capability=Capability.CONFIG, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
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
                auth=CommandAuth(capability=Capability.SESSION_OBSERVE, human=_HR_MEMBER),
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
                auth=CommandAuth(capability=Capability.TRANSCRIPT_READ, human=_HR_MEMBER),
            ),
        },
    ),
    "memories": CommandDef(
        desc=(
            "Read, save or remove durable observations about people. "
            "Memories capture meta-level things about who a person is — their relational stance, "
            "values, communication style, vision — never coding norms, architectural decisions, "
            "or operational gotchas (those live in policies, principles, and addenda). "
            "Memories are kept current by the memory agents a conversation session's end starts; "
            "any other agent saves one only when its human asks it to remember something."
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
                auth=CommandAuth(capability=Capability.MEMORIES_READ, human=_HR_MEMBER),
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
                auth=CommandAuth(capability=Capability.MEMORIES_READ, human=_HR_MEMBER),
            ),
            "save": CommandDef(
                desc=(
                    "Persist a memory observation. Save one when the human you work for asks you "
                    "to remember something; otherwise a person's memories are kept through the curation verbs."
                ),
                args="<text> [--title <title>] [--type <type>] [--project <name>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_SAVE_TITLE,
                    F.FLAG_MEMORIES_SAVE_TYPE,
                    F.FLAG_MEMORIES_SAVE_PROJECT,
                ],
                examples=[],
                auth=CommandAuth(capability=Capability.MEMORIES_SAVE, human=_HR_MEMBER),
            ),
            "delete": CommandDef(
                desc="Delete a personal-preference observation by ID (typically run by the human while pruning).",
                args="<id>",
                flags=[F.FLAG_HELP],
                examples=["telec memories delete 42"],
                auth=CommandAuth(capability=Capability.MEMORIES_READ, human=_HR_MEMBER),
            ),
            "scope": CommandDef(
                desc=(
                    "Show the scope an identity (and desk) names for curation: its current memories, "
                    "including those held under the person's bound provider accounts at the desk."
                ),
                args="--identity <identity> [--desk <desk-id>]",
                flags=[F.FLAG_HELP, F.FLAG_MEMORIES_IDENTITY, F.FLAG_MEMORIES_DESK, F.FLAG_MEMORIES_CURATION_SESSION],
                notes=["--session <session_id> remains accepted from workers that began before identity addressing."],
                examples=[
                    "telec memories scope --identity person:maurice",
                    "telec memories scope --identity telegram:123 --desk hd-company-acme",
                ],
                auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
            ),
            "add": CommandDef(
                desc="Add a current memory about the extraction's person, in the scope the extraction prepared.",
                args="--identity <identity> [--desk <desk-id>] --extraction <id> --type <type> <text>",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_IDENTITY,
                    F.FLAG_MEMORIES_DESK,
                    F.FLAG_MEMORIES_EXTRACTION,
                    F.FLAG_MEMORIES_CURATION_SESSION,
                    F.FLAG_MEMORIES_CURATION_TYPE,
                ],
                notes=["--session <session_id> remains accepted from workers that began before identity addressing."],
                examples=[
                    'telec memories add --identity person:maurice --extraction 00000000-0000-4000-8000-000000000000 --type preference "Prefers short answers"'
                ],
                auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
            ),
            "update": CommandDef(
                desc="Replace the statement of a current memory in the extraction's scope.",
                args="<memory-id> --identity <identity> [--desk <desk-id>] --extraction <id> <text>",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_IDENTITY,
                    F.FLAG_MEMORIES_DESK,
                    F.FLAG_MEMORIES_EXTRACTION,
                    F.FLAG_MEMORIES_CURATION_SESSION,
                ],
                notes=["--session <session_id> remains accepted from workers that began before identity addressing."],
                examples=[
                    'telec memories update 42 --identity person:maurice --extraction 00000000-0000-4000-8000-000000000000 "Now prefers detail"'
                ],
                auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
            ),
            "retire": CommandDef(
                desc="Retire a current memory in the extraction's scope: it leaves use and stays recorded.",
                args="<memory-id> --identity <identity> [--desk <desk-id>] --extraction <id>",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_IDENTITY,
                    F.FLAG_MEMORIES_DESK,
                    F.FLAG_MEMORIES_EXTRACTION,
                    F.FLAG_MEMORIES_CURATION_SESSION,
                ],
                notes=["--session <session_id> remains accepted from workers that began before identity addressing."],
                examples=[
                    "telec memories retire 42 --identity person:maurice --extraction 00000000-0000-4000-8000-000000000000"
                ],
                auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
            ),
            "prospect": CommandDef(
                desc="Collect a business item from the extraction's desk conversation as a prospect for the desk's home.",
                args="--desk <desk-id> --extraction <id> --type <type> <text>",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_MEMORIES_DESK,
                    F.FLAG_MEMORIES_EXTRACTION,
                    F.FLAG_MEMORIES_CURATION_SESSION,
                    F.FLAG_MEMORIES_CURATION_TYPE,
                ],
                notes=["--session <session_id> remains accepted from workers that began before identity addressing."],
                examples=[
                    'telec memories prospect --desk hd-company-acme --extraction 00000000-0000-4000-8000-000000000000 --type request "Wants an export"'
                ],
                auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
            ),
            "extraction": CommandDef(
                desc="Read an extraction's conversation material, or declare it finished or failed.",
                subcommands={
                    "read": CommandDef(
                        desc=(
                            "Show the extraction's bounded conversation material, its coverage and scope, "
                            "and the prospects already recorded from its source."
                        ),
                        args="<id>",
                        flags=[F.FLAG_HELP],
                        examples=["telec memories extraction read 00000000-0000-4000-8000-000000000000"],
                        auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
                    ),
                    "complete": CommandDef(
                        desc="Declare the extraction's memory and prospect changes finished, including a read with none.",
                        args="<id>",
                        flags=[F.FLAG_HELP],
                        examples=["telec memories extraction complete 00000000-0000-4000-8000-000000000000"],
                        auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
                    ),
                    "fail": CommandDef(
                        desc="Report that the extraction could not be finished; its stretch stays eligible.",
                        args="<id> --reason <reason>",
                        flags=[F.FLAG_HELP, F.FLAG_MEMORIES_FAIL_REASON],
                        examples=[
                            'telec memories extraction fail 00000000-0000-4000-8000-000000000000 --reason "source unreadable"'
                        ],
                        auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
                    ),
                },
            ),
            "advance": CommandDef(
                desc="Advance a conversation session's read point to the newest entry read; it never moves backwards.",
                args="--session <session_id> --to <timestamp>",
                flags=[F.FLAG_HELP, F.FLAG_MEMORIES_CURATION_SESSION, F.FLAG_MEMORIES_ADVANCE_TO],
                notes=[
                    "Accepted only from workers that began before identity addressing, and only while no extraction is open."
                ],
                examples=[
                    "telec memories advance --session 00000000-0000-4000-8000-000000000000 --to 2026-10-10T12:00:00Z"
                ],
                auth=CommandAuth(capability=Capability.MEMORY_CURATION, human=frozenset()),
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
                auth=CommandAuth(capability=Capability.MEMORIES_READ, human=_HR_MEMBER),
            ),
        },
    ),
    "repo": CommandDef(
        desc="Repository quality and commit tools",
        notes=[
            "test, format, install, and blueprint require the code capability.",
            "lint is available where code or docs is enabled; each check family follows its owning home's configuration.",
            "add, commit, and owners remain available when either code or docs is subscribed.",
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
                            "Waits briefly for recorded Blueprint maintenance when committed main "
                            "has advanced. If no complete generation matching committed main can "
                            "be established, prints unavailability and its recovery command; it "
                            "never returns stale dependents as a current answer.",
                        ],
                        examples=[
                            "telec repo blueprint affected teleclaude/core/foo.py teleclaude/api/bar.py",
                        ],
                        auth=CommandAuth(capability=Capability.CODE_CHECK, human=frozenset(), caller_independent=True),
                    ),
                },
            ),
            "lint": CommandDef(
                desc="Run checks selected by each owning home's configuration",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_CODE_ALL_LINT,
                ],
                auth=CommandAuth(capability=Capability.CODE_CHECK, human=frozenset(), caller_independent=True),
            ),
            "test": CommandDef(
                desc="Run native make test",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_CODE_ALL_TEST,
                    F.FLAG_CODE_UPDATE_SNAPSHOTS,
                ],
                auth=CommandAuth(capability=Capability.CODE_CHECK, human=frozenset(), caller_independent=True),
            ),
            "format": CommandDef(
                desc="Run native make format",
                flags=[F.FLAG_HELP, F.FLAG_CODE_ALL_FORMAT],
                auth=CommandAuth(capability=Capability.CODE, human=frozenset(), caller_independent=True),
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
                    "unstaged hunks. The partial-staging guard in `telec repo commit` directs agents "
                    "here for recovery.",
                    "A successful call from inside the session's checkout declares its paths to "
                    "session-scoping. Invoked from a different repository it stages as usual, declares "
                    "nothing, and reports the paths as not declared. Modified-tracked files "
                    "that are NOT partial-staged don't need staging — pathspec commits them straight from "
                    "the working tree.",
                    "A clean tracked path or a path that does not exist yet is declared the same way — "
                    "declaring is bookkeeping for work about to start, not a claim about current git "
                    "state, so declaring ahead of the first touch always succeeds.",
                    "NEW files in scope are NOT auto-committed; this is the explicit declaration step. "
                    "Without it, untracked files stay untracked (safety net for temp/scratch artifacts "
                    "the agent may have created incidentally).",
                    "Alternative one-shot form: telec repo commit --approved '<msg>' --include <path>.",
                ],
                auth=CommandAuth(capability=Capability.CODE, human=frozenset(), caller_independent=True),
            ),
            "owners": CommandDef(
                desc="Print live declaration owners for every dirty path in the canonical checkout",
                flags=[F.FLAG_HELP],
                notes=[
                    "Prints one path-keyed JSON object for every dirty path of the project's canonical checkout.",
                    "A value lists the live sessions that declared the path, or null when no live session declared it.",
                ],
                examples=["telec repo owners"],
                auth=CommandAuth(capability=Capability.INTEGRATION, human=_HR_MEMBER),
            ),
            "commit": CommandDef(
                desc="Commit workspace-scoped changes via a pathspec-scoped commit (sealed; no git forwarding)",
                args='"<message>" [--approved] [--todo <slug>] [--human-involved <reason>] [--include <path> ...] [--only <path> ...]',
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_COMMIT_APPROVED,
                    F.FLAG_COMMIT_INCLUDE,
                    F.FLAG_COMMIT_ONLY,
                    F.FLAG_COMMIT_TODO,
                    F.FLAG_HUMAN_INVOLVED_COMMIT,
                ],
                notes=[
                    "Accepts one quoted message, --approved, --todo <slug>, --human-involved <reason>, --include <path> ..., and --only <path> ... .",
                    "Use --todo <slug> to associate the commit with existing or planned work; this creates no todo.",
                    "Modified-tracked files in scope are auto-committed via pathspec straight from the working tree — no staging needed.",
                    "NEW (untracked) files in scope are NOT auto-committed by default; declare them via `telec repo add`, `--include`, or `--only` (safety net against incidental temp/scratch artifacts).",
                    "--only commits exactly the declared paths and is mutually exclusive with --include.",
                    "Unmerged-index files in pathspec are staged internally for the integrator conflict path.",
                    "Without --approved on main: prints commit-first and review-routing guidance and exits.",
                    "Pathspec = workspace scope plus --include paths, or exactly --only paths. Anything else in the index (foreign stage) is left untouched — there is no env-var bypass.",
                    "Supply a subject and explanatory body. The platform generates attribution and provenance; caller-supplied platform metadata is refused.",
                    "In a todo worktree, a successful commit also publishes the branch to origin; a failed publish leaves the commit in place.",
                ],
                auth=CommandAuth(capability=Capability.CODE, human=_HR_MEMBER),
            ),
            "stamp": CommandDef(
                desc="Record a commit-review outcome on commits that landed on main",
                args="<sha>[,<sha>...] --verdict approve|request_changes [--reason <text>]",
                flags=[
                    F.FLAG_HELP,
                    F.FLAG_CODE_STAMP_VERDICT,
                    F.FLAG_CODE_STAMP_REASON,
                ],
                notes=[
                    "Every accepted stamp is durably recorded by repository and full SHA, including when neither reviewer nor parent holds a todo claim.",
                    "A reviewer stamps only the SHAs reviewed. The author may stamp approve for an item that owes no review; that discard discharges the ordinary checkpoint only and never supplies independent documentation approval.",
                    "Independent approval requires authenticated reviewer and verified commit-producer provenance. Missing provenance is insufficient for documentation admission.",
                    "The latest independent review outcome is effective for admission; request_changes remains unresolved until a later independent approval.",
                    "A stamp covering a session's commits discharges that session's post-commit review prompt, whether the reviewer or the author gave it.",
                    "Every SHA must be a commit reachable from main; otherwise nothing is recorded.",
                ],
                examples=[
                    "telec repo stamp 1a2b3c4,5d6e7f8 --verdict approve",
                    "telec repo stamp 1a2b3c4 --verdict approve --reason 'removes a retired section'",
                ],
                auth=CommandAuth(capability=Capability.STAMP, human=_HR_MEMBER),
            ),
            **_hook_entry_commands(),
            "maintenance": CommandDef(
                desc="Inspect and recover canonical-main maintenance",
                flags=[F.FLAG_HELP],
                hidden=True,
                subcommands={
                    "status": CommandDef(
                        desc="Show outstanding maintenance records and integrator judgment",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(capability=Capability.MAINTENANCE_RECOVERY, human=frozenset()),
                    ),
                    "drain": CommandDef(
                        desc="Resume interrupted maintenance and record readiness",
                        flags=[F.FLAG_HELP],
                        auth=CommandAuth(capability=Capability.MAINTENANCE_RECOVERY, human=frozenset()),
                    ),
                    "retry": CommandDef(
                        desc="Retry one terminally failed maintenance action",
                        args="(--after-sha <sha> | --event-id <id>) --action <id> ",
                        flags=[
                            F.FLAG_HELP,
                            F.FLAG_MAINTENANCE_AFTER_SHA,
                            F.FLAG_MAINTENANCE_EVENT_ID,
                            F.FLAG_MAINTENANCE_ACTION,
                        ],
                        auth=CommandAuth(capability=Capability.MAINTENANCE_RECOVERY, human=frozenset()),
                    ),
                },
            ),
        },
    ),
    "sync": CommandDef(
        desc="Run this root's maintenance on demand: the fallback for commit-boundary maintenance",
        args="[--list]",
        flags=[F.FLAG_HELP, F.FLAG_SYNC_LIST],
        notes=[
            "Use it when commit-boundary maintenance did not run, or ran and left the root wrong: it performs every step the root's registry declares, in declared order, and reports each step's outcome as it completes.",
            "A failed step does not stop the later ones; the command exits non-zero when any step failed.",
            "When a run owes daemon replacement, steps not declared safe while the daemon serves run while it is stopped; serving-tolerant steps run after startup is verified. Reloads and service deployment remain reported rather than performed.",
            "Uncommitted edits are named first, with the sessions holding them. Publication uses committed state only: main's tip, or the commit an installed beta or stable release checkout runs; the other steps read the checkout as it stands.",
            "Runs only from the canonical checkout on main, or from the installed release checkout of a beta or stable installation (detached at its release), in a directory holding its own teleclaude.yml; elsewhere it refuses and names where to run it.",
            "A step that an earlier commit-boundary run recorded as failed is named with its replay command; the standing integrator owns that replay.",
            "With --list, it prints what each step will do and, when replacement is owed, distinguishes the stopped window from work after verified startup; the listing runs nothing.",
        ],
        examples=["telec sync", "telec sync --list"],
        auth=CommandAuth(capability=Capability.CODE, human=_HR_MEMBER),
    ),
    "app": CommandDef(
        desc="Operate the installed platform: its status, lifecycle, installs, rollback and assessments",
        flags=[F.FLAG_HELP],
        notes=[
            "Every verb acts on the machine's installation, whatever directory the caller stands in; nothing in a project checkout is run or changed.",
            "A commit in a project reaches nothing live: a revision becomes the platform's active release only through `install`.",
        ],
        subcommands={
            "status": CommandDef(
                desc="Show the daemon's health, the active release, the last install or rollback and the installs owed an assessment",
                flags=[F.FLAG_HELP],
                examples=["telec app status"],
                auth=CommandAuth(
                    capability=Capability.INSTALLATION_READ, human=_HR_MEMBER, scope=CommandScope.PLATFORM
                ),
            ),
            "start": CommandDef(
                desc="Install the services and start the installation's daemon",
                flags=[F.FLAG_HELP],
                notes=["Refuses until the machine configuration is valid; complete it with `telec config`."],
                examples=["telec app start"],
                auth=CommandAuth(capability=Capability.INSTALLATION, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
            "stop": CommandDef(
                desc="Stop the installation's daemon once its accepted work has settled",
                flags=[F.FLAG_HELP],
                examples=["telec app stop"],
                auth=CommandAuth(capability=Capability.INSTALLATION, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
            "restart": CommandDef(
                desc="Restart the installation's daemon on its active release",
                flags=[F.FLAG_HELP],
                examples=["telec app restart"],
                auth=CommandAuth(capability=Capability.INSTALLATION, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
            "install": CommandDef(
                desc="Install a revision as the active release",
                args="[<revision>]",
                flags=[F.FLAG_HELP],
                notes=[
                    "Without a revision, installs the target the installation's channel resolves for the repository it follows.",
                    "Moves forward only: a revision older than the active release is refused and nothing changes.",
                    "The previously active release stays installed. When no migration started the install can be rolled back; after one started, the way back is a forward repair.",
                ],
                examples=["telec app install", "telec app install v1.4.0"],
                auth=CommandAuth(capability=Capability.INSTALLATION, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
            "rollback": CommandDef(
                desc="Make the previously active release active again",
                flags=[F.FLAG_HELP],
                notes=[
                    "Refused, naming the condition, when a migration has started since the active release became active."
                ],
                examples=["telec app rollback"],
                auth=CommandAuth(capability=Capability.INSTALLATION, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
            "assessed": CommandDef(
                desc="Record that an install's running release has been assessed",
                args="<install>",
                flags=[F.FLAG_HELP],
                notes=[
                    "`<install>` is the number `telec app status` lists for an owed install. It discharges that install and every earlier owed one.",
                    "A later install stays owed, a later attempt at the same revision included.",
                    "Refuses, naming the owed installs, when none carries that number, and while the daemon does not serve the active release.",
                ],
                examples=["telec app assessed 3"],
                auth=CommandAuth(capability=Capability.INSTALLATION, human=_HR_ADMIN, scope=CommandScope.PLATFORM),
            ),
        },
    ),
}
# =============================================================================
# Computer addressing — every command that acts on state a computer owns accepts the
# computer to address. The daemon boundary carries the request to that computer
# (`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`);
# a command the invoking checkout or folder defines, or one that reports a job's own
# run, names no other computer.
# =============================================================================

_BOUNDARY_ADDRESSED_GROUPS = ("todo", "bugs", "jobs", "agents", "config")
_NOT_BOUNDARY_ADDRESSED = frozenset(
    {
        ("todo", "sync"),
        ("todo", "sync-replica"),
        ("jobs", "report"),
        ("config", "project", "adopt"),
        ("config", "wizard"),
    }
)
_COMPUTER_ARGS = "[--computer <host>]"


def _declare_boundary_addressing(path: tuple[str, ...], node: CommandDef) -> None:
    """Declare the computer to address on every leaf command under ``node`` that acts on computer-owned state."""
    if node.subcommands:
        for name, subcommand in node.subcommands.items():
            _declare_boundary_addressing((*path, name), subcommand)
        return
    if path in _NOT_BOUNDARY_ADDRESSED or F.FLAG_COMPUTER in node.flags:
        return
    node.flags.append(F.FLAG_COMPUTER)
    node.args = f"{node.args} {_COMPUTER_ARGS}".strip()
    node.addressed_at_boundary = True


for _group in _BOUNDARY_ADDRESSED_GROUPS:
    _declare_boundary_addressing((_group,), CLI_SURFACE[_group])

HELP_SUBCOMMAND_EXPANSIONS: dict[str, dict[str, list[tuple[str, str]]]] = {}

# =============================================================================
# Leaf-node constants — the object a handler parses, resolved by lookup so a
# renamed or removed CLI_SURFACE key fails at import instead of a path
# literal silently resolving to nothing.
# =============================================================================

HISTORY_SEARCH = CLI_SURFACE["history"].subcommands["search"]
HISTORY_SHOW = CLI_SURFACE["history"].subcommands["show"]

SESSIONS_LIST = CLI_SURFACE["sessions"].subcommands["list"]
SESSIONS_SHOW = CLI_SURFACE["sessions"].subcommands["show"]
SESSIONS_START = CLI_SURFACE["sessions"].subcommands["start"]
SESSIONS_SEND = CLI_SURFACE["sessions"].subcommands["send"]
SESSIONS_TAIL = CLI_SURFACE["sessions"].subcommands["tail"]
SESSIONS_RUN = CLI_SURFACE["sessions"].subcommands["run"]
SESSIONS_RUN_PA = CLI_SURFACE["sessions"].subcommands["run-pa"]
SESSIONS_REVIVE = CLI_SURFACE["sessions"].subcommands["revive"]
SESSIONS_END = CLI_SURFACE["sessions"].subcommands["end"]
SESSIONS_UNSUBSCRIBE = CLI_SURFACE["sessions"].subcommands["unsubscribe"]
SESSIONS_RESTART = CLI_SURFACE["sessions"].subcommands["restart"]
SESSIONS_RESULT = CLI_SURFACE["sessions"].subcommands["result"]
SESSIONS_FILE = CLI_SURFACE["sessions"].subcommands["file"]
SESSIONS_ESCALATE = CLI_SURFACE["sessions"].subcommands["escalate"]

PROJECTS_LIST = CLI_SURFACE["projects"].subcommands["list"]
AGENTS_STATUS = CLI_SURFACE["agents"].subcommands["status"]

JOBS_REPORT = CLI_SURFACE["jobs"].subcommands[JobsSubcommand.REPORT.value]
JOBS_LIST = CLI_SURFACE["jobs"].subcommands[JobsSubcommand.LIST.value]
JOBS_STATUS = CLI_SURFACE["jobs"].subcommands[JobsSubcommand.STATUS.value]
JOBS_ENABLE = CLI_SURFACE["jobs"].subcommands[JobsSubcommand.ENABLE.value]
JOBS_DISABLE = CLI_SURFACE["jobs"].subcommands[JobsSubcommand.DISABLE.value]
JOBS_RUN = CLI_SURFACE["jobs"].subcommands[JobsSubcommand.RUN.value]

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
TODO_BOARD_REPAIR = CLI_SURFACE["todo"].subcommands["board"].subcommands["repair"]
TODO_STAMP = CLI_SURFACE["todo"].subcommands["stamp"]
TODO_RETURN_TO_WORK = CLI_SURFACE["todo"].subcommands["return-to-work"]
TODO_REACTIVATE = CLI_SURFACE["todo"].subcommands["reactivate"]
TODO_LIST = CLI_SURFACE["todo"].subcommands["list"]
TODO_SYNC = CLI_SURFACE["todo"].subcommands["sync"]
TODO_SYNC_REPLICA = CLI_SURFACE["todo"].subcommands["sync-replica"]
TODO_UPDATE = CLI_SURFACE["todo"].subcommands["update"]
TODO_SHOW = CLI_SURFACE["todo"].subcommands["show"]

BUGS_REPORT = CLI_SURFACE["bugs"].subcommands["report"]
BUGS_LIST = CLI_SURFACE["bugs"].subcommands["list"]
BUGS_SUPPRESS = CLI_SURFACE["bugs"].subcommands["suppress"]
BUGS_SUPPRESSIONS = CLI_SURFACE["bugs"].subcommands["suppressions"]
BUGS_UNSUPPRESS = CLI_SURFACE["bugs"].subcommands["unsuppress"]


DOCS_INDEX = CLI_SURFACE["docs"].subcommands["index"]
DOCS_GET = CLI_SURFACE["docs"].subcommands["get"]

MEMORIES_LIST = CLI_SURFACE["memories"].subcommands["list"]
MEMORIES_SEARCH = CLI_SURFACE["memories"].subcommands["search"]
MEMORIES_SAVE = CLI_SURFACE["memories"].subcommands["save"]
MEMORIES_DELETE = CLI_SURFACE["memories"].subcommands["delete"]
MEMORIES_TIMELINE = CLI_SURFACE["memories"].subcommands["timeline"]
MEMORIES_SCOPE = CLI_SURFACE["memories"].subcommands["scope"]
MEMORIES_ADD = CLI_SURFACE["memories"].subcommands["add"]
MEMORIES_UPDATE = CLI_SURFACE["memories"].subcommands["update"]
MEMORIES_RETIRE = CLI_SURFACE["memories"].subcommands["retire"]
MEMORIES_PROSPECT = CLI_SURFACE["memories"].subcommands["prospect"]
MEMORIES_ADVANCE = CLI_SURFACE["memories"].subcommands["advance"]
MEMORIES_EXTRACTION_READ = CLI_SURFACE["memories"].subcommands["extraction"].subcommands["read"]
MEMORIES_EXTRACTION_COMPLETE = CLI_SURFACE["memories"].subcommands["extraction"].subcommands["complete"]
MEMORIES_EXTRACTION_FAIL = CLI_SURFACE["memories"].subcommands["extraction"].subcommands["fail"]

MESSAGE = CLI_SURFACE["message"]
AUDIO = CLI_SURFACE["audio"].subcommands["stt"]

SYNC = CLI_SURFACE["sync"]

APP_STATUS = CLI_SURFACE["app"].subcommands["status"]
APP_START = CLI_SURFACE["app"].subcommands["start"]
APP_STOP = CLI_SURFACE["app"].subcommands["stop"]
APP_RESTART = CLI_SURFACE["app"].subcommands["restart"]
APP_INSTALL = CLI_SURFACE["app"].subcommands["install"]
APP_ROLLBACK = CLI_SURFACE["app"].subcommands["rollback"]
APP_ASSESSED = CLI_SURFACE["app"].subcommands["assessed"]

CONTENT_DUMP = CLI_SURFACE["content"].subcommands["dump"]

EVENTS_LIST = CLI_SURFACE["events"].subcommands[EventCommand.LIST.value]
EVENTS_SCHEMA = CLI_SURFACE["events"].subcommands[EventCommand.SCHEMA.value]

MCP_LIST = CLI_SURFACE["mcp"].subcommands["list"]
MCP_LIST_TOOLS = CLI_SURFACE["mcp"].subcommands["list-tools"]
MCP_CALL = CLI_SURFACE["mcp"].subcommands["call"]

REPO_BLUEPRINT_AFFECTED = CLI_SURFACE["repo"].subcommands["blueprint"].subcommands["affected"]
REPO_LINT = CLI_SURFACE["repo"].subcommands["lint"]
REPO_TEST = CLI_SURFACE["repo"].subcommands["test"]
REPO_FORMAT = CLI_SURFACE["repo"].subcommands["format"]
REPO_ADD = CLI_SURFACE["repo"].subcommands["add"]
REPO_OWNERS = CLI_SURFACE["repo"].subcommands["owners"]
REPO_COMMIT = CLI_SURFACE["repo"].subcommands["commit"]
REPO_STAMP = CLI_SURFACE["repo"].subcommands["stamp"]
REPO_MAINTENANCE_STATUS = CLI_SURFACE["repo"].subcommands["maintenance"].subcommands["status"]
REPO_MAINTENANCE_DRAIN = CLI_SURFACE["repo"].subcommands["maintenance"].subcommands["drain"]
REPO_MAINTENANCE_RETRY = CLI_SURFACE["repo"].subcommands["maintenance"].subcommands["retry"]

CONFIG_TTS_DEPROVISION = CLI_SURFACE["config"].subcommands["tts"].subcommands["deprovision"]
CONFIG_VALIDATE = CLI_SURFACE["config"].subcommands["validate"]
CONFIG_ENV_LIST = CLI_SURFACE["config"].subcommands["env"].subcommands["list"]
CONFIG_ENV_SET = CLI_SURFACE["config"].subcommands["env"].subcommands["set"]

CONFIG_COMPUTER_LIST = CLI_SURFACE["config"].subcommands["computer"].subcommands["list"]
CONFIG_COMPUTER_GET = CLI_SURFACE["config"].subcommands["computer"].subcommands["get"]
CONFIG_COMPUTER_INIT = CLI_SURFACE["config"].subcommands["computer"].subcommands["init"]
CONFIG_COMPUTER_PATCH = CLI_SURFACE["config"].subcommands["computer"].subcommands["patch"]
CONFIG_GLOBAL_LIST = CLI_SURFACE["config"].subcommands["global"].subcommands["list"]
CONFIG_GLOBAL_GET = CLI_SURFACE["config"].subcommands["global"].subcommands["get"]
CONFIG_GLOBAL_INIT = CLI_SURFACE["config"].subcommands["global"].subcommands["init"]
CONFIG_GLOBAL_PATCH = CLI_SURFACE["config"].subcommands["global"].subcommands["patch"]
CONFIG_PERSON_LIST = CLI_SURFACE["config"].subcommands["person"].subcommands["list"]
CONFIG_PERSON_GET = CLI_SURFACE["config"].subcommands["person"].subcommands["get"]
CONFIG_PERSON_INIT = CLI_SURFACE["config"].subcommands["person"].subcommands["init"]
CONFIG_PERSON_PATCH = CLI_SURFACE["config"].subcommands["person"].subcommands["patch"]
CONFIG_PERSON_INVITE = CLI_SURFACE["config"].subcommands["person"].subcommands["invite"]
CONFIG_PERSON_DISCORD_VOICE_BOT = CLI_SURFACE["config"].subcommands["person"].subcommands["discord-voice-bot"]
CONFIG_COMPANY_LIST = CLI_SURFACE["config"].subcommands["company"].subcommands["list"]
CONFIG_COMPANY_GET = CLI_SURFACE["config"].subcommands["company"].subcommands["get"]
CONFIG_COMPANY_INIT = CLI_SURFACE["config"].subcommands["company"].subcommands["init"]
CONFIG_COMPANY_PATCH = CLI_SURFACE["config"].subcommands["company"].subcommands["patch"]
CONFIG_PROJECT_LIST = CLI_SURFACE["config"].subcommands["project"].subcommands["list"]
CONFIG_PROJECT_GET = CLI_SURFACE["config"].subcommands["project"].subcommands["get"]
CONFIG_PROJECT_CREATE = CLI_SURFACE["config"].subcommands["project"].subcommands["create"]
CONFIG_PROJECT_ADOPT = CLI_SURFACE["config"].subcommands["project"].subcommands["adopt"]
CONFIG_PROJECT_PATCH = CLI_SURFACE["config"].subcommands["project"].subcommands["patch"]
CONFIG_COMPANY_HELP_DESK_LINKS = CLI_SURFACE["config"].subcommands["company"].subcommands["help-desk-links"]
CONFIG_PROJECT_HELP_DESK_LINKS = CLI_SURFACE["config"].subcommands["project"].subcommands["help-desk-links"]

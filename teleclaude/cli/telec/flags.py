"""Every ``Flag`` the telec CLI surface declares, as named module constants.

Handlers recognize an option by importing the same ``Flag`` object the
surface attaches to a ``CommandDef`` — never by comparing argv tokens to a
hand-copied literal. A flag is named once here; a command that needs a
distinct arity or description for the same concept gets its own constant
(``FLAG_COMPUTER_MANY`` beside ``FLAG_COMPUTER``, for example) rather than a
second inline declaration.
"""

from __future__ import annotations

from dataclasses import replace

from teleclaude.agent_registry import AgentName
from teleclaude.constants import TAXONOMY_TYPES
from teleclaude.snippet_scope import SnippetScope
from teleclaude.types.todo_kind import TODO_KIND_USAGE

from .surface_types import Flag, FlagArity

SWITCH = FlagArity.SWITCH
VALUE = FlagArity.VALUE
REPEATED = FlagArity.REPEATED
GREEDY = FlagArity.GREEDY
OPTIONAL_VALUE = FlagArity.OPTIONAL_VALUE

SCOPE_VALUES = "|".join(member.value for member in SnippetScope)

# =============================================================================
# Cross-command shared concepts
# =============================================================================

FLAG_HELP = Flag("--help", "-h", "Show usage information", hidden=True, arity=SWITCH)
FLAG_COMPUTER = Flag("--computer", "-c", "Target computer (optional; defaults to local)", arity=VALUE)
FLAG_COMPUTER_MANY = replace(
    FLAG_COMPUTER,
    arity=GREEDY,
    desc="Query one or more remote computers via daemon API",
)
FLAG_AGENT = Flag("--agent", desc=f"Agent: {', '.join(AgentName)}", arity=VALUE)
FLAG_MODE = Flag("--mode", desc="Thinking mode: fast, med, slow", arity=VALUE)
FLAG_DETACH = Flag(
    "--detach",
    desc="Fire-and-forget: inherit context but skip listener registration",
    hidden=True,
    arity=SWITCH,
)
FLAG_PATH = Flag("--path", desc="Path to the project directory (optional; defaults to cwd)", arity=VALUE)
FLAG_COMPANY = Flag("--company", desc="Company this session operates the business of", arity=VALUE)
FLAG_PROJECT_FILTER = Flag("--project", desc="Filter by project name", arity=VALUE)
FLAG_PROJECT_TRUSTED = Flag("--project", desc="Project name or slug from the project registry", arity=VALUE)
FLAG_SESSION = Flag("--session", "-s", "Session ID", arity=VALUE)
FLAG_THINKING = Flag("--thinking", desc="Include thinking blocks", arity=SWITCH)
FLAG_LIMIT_20 = Flag("--limit", desc="Max results (default: 20)", arity=VALUE)
FLAG_AFTER_DEPS = Flag("--after", desc="Comma-separated dependency slugs", arity=REPEATED)
FLAG_HUMAN_INVOLVED = Flag(
    "--human-involved",
    desc=(
        "Report a human's presence at this act, measured from their last input. The non-empty reason "
        "stays ephemeral; an observation outside the recency window records false without failing the "
        "act; omission records false and never inherits from another action."
    ),
    arity=VALUE,
)
FLAG_JSON_MACHINE_READABLE = Flag("--json", desc="Emit machine-readable JSON output", arity=SWITCH)

# =============================================================================
# sessions
# =============================================================================

FLAG_SESSIONS_LIST_ALL = Flag("--all", desc="Show all sessions, unattended procedure agents included", arity=SWITCH)
FLAG_SESSIONS_LIST_CLOSED = Flag("--closed", desc="Include closed sessions", arity=SWITCH)
FLAG_SESSIONS_LIST_JOB = Flag("--job", desc="Filter by job value", arity=VALUE)
FLAG_SESSIONS_SHOW_FULL = Flag(
    "--full",
    desc="Show the complete stored record instead of the grouped detail",
    arity=SWITCH,
)

FLAG_MESSAGE = Flag("--message", desc="Initial message to send", arity=VALUE)
FLAG_DIRECT_START = Flag(
    "--direct", desc="Conversation mode: create direct link with caller and bypass listeners", arity=SWITCH
)
FLAG_DIRECT_SEND = Flag("--direct", desc="Conversation mode: create shared direct link", arity=SWITCH)
FLAG_CLOSE_LINK = Flag("--close-link", desc="Close direct link with target session (alias: --close_link)", arity=SWITCH)
FLAG_CLOSE_LINK_ALIAS = Flag("--close_link", desc="Legacy alias for --close-link", hidden=True, arity=SWITCH)
FLAG_MESSAGE_ALIAS = Flag("--message", "-m", desc="Legacy alias for the positional message", hidden=True, arity=VALUE)

FLAG_TAIL_SINCE = Flag("--since", desc="ISO8601 timestamp filter", arity=VALUE)
FLAG_TAIL_TOOLS = Flag("--tools", desc="Include tool use entries", arity=SWITCH)
FLAG_TAIL_FULL = Flag("--full", desc="Show all projected messages instead of the latest user turn", arity=SWITCH)
FLAG_TAIL_PANE = Flag("--pane", desc="Show the current terminal pane instead of transcript messages", arity=SWITCH)

FLAG_RUN_COMMAND = Flag(
    "--command", desc="Entry procedure snippet ID (e.g. sdlc/procedure/lifecycle/work/build)", arity=VALUE
)
FLAG_RUN_ARGS = Flag("--args", desc="Command arguments", arity=VALUE)
FLAG_RUN_SUBFOLDER = Flag("--subfolder", desc="Subdirectory within the project", arity=VALUE)
FLAG_RUN_ADDITIONAL_CONTEXT = Flag(
    "--additional-context", desc="Additional context for the worker, appended to startup message", arity=VALUE
)
FLAG_REVIVE_AGENT = Flag("--agent", desc="Treat session_id as native agent session ID for the given agent", arity=VALUE)
FLAG_REVIVE_ATTACH = Flag("--attach", desc="Attach to tmux session after revive", arity=SWITCH)
FLAG_HANDOFF = Flag("--handoff", desc="Continue with automatic or named successor agent", arity=OPTIONAL_VALUE)

FLAG_RESULT_FORMAT = Flag("--format", desc="Output format: markdown, html", arity=VALUE)
FLAG_RESULT_CONTENT_ALIAS = Flag(
    "--content", desc="Legacy alias for the positional <content>", hidden=True, arity=VALUE
)

FLAG_FILE_PATH = Flag("--path", desc="File path on the daemon host", arity=VALUE)
FLAG_FILE_FILENAME = Flag("--filename", desc="Display filename", arity=VALUE)
FLAG_FILE_CAPTION = Flag("--caption", desc="Optional caption", arity=VALUE)

FLAG_ESCALATE_CUSTOMER = Flag("--customer", desc="Customer name", arity=VALUE)
FLAG_ESCALATE_REASON = Flag("--reason", desc="Reason for escalation", arity=VALUE)
FLAG_ESCALATE_SUMMARY = Flag("--summary", desc="Context summary for the people notified", arity=VALUE)

# =============================================================================
# reminders
# =============================================================================

FLAG_REMINDER_AFTER = Flag("--after", desc="Relative duration such as 30s, 5m, 2h, or 1d", arity=VALUE)
FLAG_REMINDER_AT = Flag("--at", desc="Absolute RFC3339 instant", arity=VALUE)
FLAG_REMINDER_INTENT = Flag("--intent", desc="Agent-authored generic reminder intent", arity=VALUE)
FLAG_REMINDER_REPEAT = Flag("--repeat", desc="Repeat a relative generic reminder", arity=SWITCH)
FLAG_REMINDER_SLUG = Flag("--slug", desc="Target work slug for orchestration-watch", arity=VALUE)
FLAG_REMINDER_CANCEL_ALL = Flag("--all", desc="Cancel all reminders owned by the calling session", arity=SWITCH)

# =============================================================================
# companies / agents
# =============================================================================

FLAG_COMPANY_SLUG = Flag("--slug", desc="Company slug (optional; derived from the name when omitted)", arity=VALUE)
FLAG_PROJECT_COMPANY = Flag(
    "--company", desc="Create the project in this company's home, owned by the company (company members)", arity=VALUE
)
FLAG_PROJECT_PATH = Flag(
    "--path",
    desc="Create an ownerless platform project at this folder outside every home (platform administrators)",
    arity=VALUE,
)

FLAG_AGENT_STATUS = Flag("--status", desc="Status: available, unavailable, degraded", arity=VALUE)
FLAG_AGENT_STATUS_REASON = Flag("--reason", desc="Reason for status change", arity=VALUE)
FLAG_AGENT_STATUS_MODEL = Flag("--model", desc="Scope the status to one declared model", arity=VALUE)
FLAG_AGENT_STATUS_UNTIL = Flag("--until", desc="ISO8601 UTC expiry for unavailable or degraded", arity=VALUE)
FLAG_AGENT_STATUS_CLEAR = Flag("--clear", desc="Reset to available immediately", arity=SWITCH)

# =============================================================================
# message
# =============================================================================

FLAG_MSG_RECIPIENT = Flag("--recipient", desc="Person slug; defaults to the caller's authority", arity=VALUE)
FLAG_MSG_FILE = Flag("--file", desc="Path to a single file to attach (Telegram, Discord, email only)", arity=VALUE)
FLAG_MSG_SUBJECT = Flag(
    "--subject", desc="Email subject line; ignored on channels without a subject concept", arity=VALUE
)
FLAG_MSG_CHANNEL = Flag("--channel", desc="Override channel: telegram, discord, whatsapp, email", arity=VALUE)

# =============================================================================
# audio
# =============================================================================

FLAG_AUDIO_URL = Flag("--url", desc="Audio URL to transcribe", arity=VALUE)
FLAG_AUDIO_PATH = Flag("--path", desc="Local audio file to transcribe", arity=VALUE)
FLAG_AUDIO_LANGUAGE = Flag("--language", desc="Optional language code hint", arity=VALUE)

# =============================================================================
# docs
# =============================================================================

FLAG_DOCS_BASELINE_ONLY = Flag("--baseline-only", "-b", "Show only baseline snippets", arity=SWITCH)
FLAG_DOCS_THIRD_PARTY = Flag("--third-party", "-t", "Include third-party docs", arity=SWITCH)
FLAG_DOCS_AREAS = Flag(
    "--areas", "-a", f"Filter by taxonomy type ({'|'.join(TAXONOMY_TYPES)}); omit for all", arity=VALUE
)
FLAG_DOCS_DOMAINS = Flag("--domains", "-d", "Filter by published domain; omit for all", arity=VALUE)
FLAG_DOCS_SCOPE = Flag(
    "--scope",
    desc=f"Filter by snippet kind ({SCOPE_VALUES}); a no-op with --local",
    arity=VALUE,
)
FLAG_DOCS_GET_SCOPE = Flag(
    "--scope",
    desc=f"Filter by snippet kind ({SCOPE_VALUES})",
    arity=VALUE,
)
FLAG_DOCS_PROJECT = Flag("--project", desc="Select the project's published snippets by slug", arity=VALUE)
FLAG_DOCS_PERSON = Flag("--person", desc="Select the person's published snippets by slug", arity=VALUE)
FLAG_DOCS_COMPANY = Flag("--company", desc="Select the company's published snippets by slug", arity=VALUE)
FLAG_DOCS_LOCAL = Flag("--local", desc="Select local snippets from the named or landed home", arity=SWITCH)
FLAG_DOCS_TARGET = Flag("--target", desc="Filter to snippets delivered by slug", arity=VALUE)
FLAG_DOCS_GET_CLOSURE = Flag(
    "--closure",
    desc="Fetch an activatable procedure's eligible required-read closure in one pass",
    hidden=True,
    arity=SWITCH,
)
FLAG_DOCS_GET_TARGET = Flag(
    "--target",
    desc="Include the slug's planned sections and companion replacement body (default: strip all)",
    arity=VALUE,
)

# =============================================================================
# todo create
# =============================================================================

FLAG_TODO_SCHEDULE = Flag(
    "--schedule",
    desc="Task-only schedule: ISO-8601 instant or cron:<minute hour day month weekday> (0/7=Sunday)",
    arity=VALUE,
)
FLAG_TODO_KIND = Flag(
    "--kind",
    desc=(
        f"The work-unit's entry point into the lifecycle: {TODO_KIND_USAGE}. Required "
        "when creating a todo. --kind task is side-effect-only and never touches the repo "
        "(sdlc/spec/todo-kind-task) — code work is change/feature/bug."
    ),
    arity=VALUE,
)
FLAG_TODO_CREATE_APPROVED = Flag(
    "--approved",
    desc=(
        "Declares the pre-creation decisions were faced. Without it a complete creation "
        "request creates nothing and points to "
        "sdlc/policy/todo-creation-discipline."
    ),
    arity=SWITCH,
)
FLAG_TODO_ICEBOX = Flag("--icebox", desc="Create future todo parked in the icebox; does not auto-spawn", arity=SWITCH)
FLAG_TODO_PROJECT_ROOT = Flag(
    "--project-root", "-p", desc="Target an explicit project root instead of the invocation cwd", arity=VALUE
)
FLAG_TODO_GROUP = Flag(
    "--group",
    desc=(
        "Attach the new todo as a child of <parent-slug>, making the parent a holder. Grouping moves the "
        "parent's pending documentation ownership to the first grouped child: every in-body marker, companion "
        "filename, and delivered_by membership naming the parent is rewritten to that child and committed as part "
        "of the same transition."
    ),
    arity=VALUE,
)
FLAG_TODO_PLAN = Flag(
    "--plan",
    desc=(
        "For --kind change, content seeds implementation-plan as a draft basis; for --kind "
        "task, content is the pre-authorized task-plan."
    ),
    arity=SWITCH,
)
FLAG_TODO_CREATE_HOLD = Flag(
    "--hold",
    desc=(
        "Exceptional create-time brake for valid work awaiting an external gate; suppresses "
        "future dispatch until release."
    ),
    hidden=True,
    arity=SWITCH,
)
FLAG_TODO_CREATE_REASON = Flag(
    "--reason",
    desc="State why the hold exists or name the gate or owner it awaits; valid only with --hold.",
    hidden=True,
    arity=VALUE,
)
FLAG_TODO_SYNC_PROJECT = Flag(
    "--project",
    desc="Comma-separated project slugs whose todo state is copied",
    arity=VALUE,
)
FLAG_TODO_SYNC_TO = Flag(
    "--to",
    desc="Comma-separated target computer names",
    arity=VALUE,
)

# =============================================================================
# todo list
# =============================================================================

FLAG_TODO_LIST_INCLUDE_ICEBOX = Flag("--include-icebox", "-i", "Include icebox items", arity=SWITCH)
FLAG_TODO_LIST_ICEBOX_ONLY = Flag("--icebox-only", "-o", "Show only icebox items", arity=SWITCH)
FLAG_TODO_LIST_INCLUDE_DELIVERED = Flag("--include-delivered", "-d", "Include delivered items", arity=SWITCH)
FLAG_TODO_LIST_DELIVERED_ONLY = Flag("--delivered-only", desc="Show only delivered items", arity=SWITCH)
FLAG_TODO_LIST_INCLUDE_REMOVED = Flag("--include-removed", "-r", "Include soft-removed items", arity=SWITCH)
FLAG_TODO_LIST_REMOVED_ONLY = Flag("--removed-only", desc="Show only soft-removed items", arity=SWITCH)
FLAG_TODO_LIST_SINCE = Flag(
    "--since",
    desc=(
        "Only delivered entries at/after this point: duration (7d, 72h, 2w) or ISO date "
        "(2026-05-01). Implies --include-delivered."
    ),
    arity=VALUE,
)
FLAG_TODO_LIST_JSON = Flag(
    "--json", desc="Output as a sectioned JSON object (active/delivered/icebox/removed trees)", arity=SWITCH
)

# =============================================================================
# todo integrate
# =============================================================================

FLAG_TODO_INTEGRATE_ABANDON = Flag(
    "--abandon",
    desc=(
        "Park a CONTENT_GATE_BLOCKED candidate or a held clean uncommitted attempt. "
        "The state machine resets only the integration worktree to its frozen pre-merge SHA; "
        "clean attempts refuse unless held, conflict-free and still at that SHA."
    ),
    arity=SWITCH,
)

# =============================================================================
# todo remove / deliver / update / show / reactivate
# =============================================================================

FLAG_TODO_REMOVE_FORCE = Flag("--force", desc="Override live-work removal refusal", arity=SWITCH)

FLAG_TODO_DELIVER_COMMIT = Flag(
    "--commit",
    desc=(
        "The commit that delivered the slug. The integrator always supplies its own pushed "
        "commit and withholds delivery until that commit is confirmed on origin/main. Never "
        "inferred from HEAD, which is routinely an unrelated commit. It is required for "
        "feature, change, and bug deliveries; task deliveries may omit it."
    ),
    arity=VALUE,
)

FLAG_TODO_UPDATE_SLUG = Flag("--slug", desc="New todo slug; delegates to the durable rename engine", arity=VALUE)
FLAG_TODO_UPDATE_GROUP = Flag(
    "--group",
    desc="Move into this holder or pre-prepared todo; pass an empty value to remove the todo from its group",
    arity=VALUE,
)
FLAG_TODO_UPDATE_AFTER = Flag(
    "--after",
    desc=(
        "Dependency slug(s); replaces the full set. "
        "CSV accepted: --after parent-a,parent-b. "
        "Repeated flags accepted for compatibility: --after parent-a --after parent-b. "
        'Use --after "" to clear all dependencies.'
    ),
    arity=REPEATED,
)
FLAG_TODO_UPDATE_SCHEDULE = Flag(
    "--schedule", desc="Task-only schedule; pass an empty value to clear (cron weekday 0/7=Sunday)", arity=VALUE
)
FLAG_TODO_UPDATE_KIND = Flag("--kind", desc=f"New todo kind: {TODO_KIND_USAGE}", arity=VALUE)
FLAG_TODO_UPDATE_HOLD = Flag("--hold", desc="Set the per-todo automatic dispatch brake", arity=SWITCH)
FLAG_TODO_UPDATE_REASON = Flag(
    "--reason", desc="State why a --hold waits, or the gate or owner it awaits; required with --hold", arity=VALUE
)
FLAG_TODO_UPDATE_RELEASE = Flag("--release", desc="Release the per-todo automatic dispatch brake", arity=SWITCH)
FLAG_TODO_UPDATE_UNCLAIM = Flag(
    "--unclaim", desc="Release the caller-owned runner claim without ending the session", arity=SWITCH
)
FLAG_TODO_UPDATE_FORCE = Flag(
    "--force", desc="Allow permanent orphan-artifact handling for kind migrations", arity=SWITCH
)

FLAG_TODO_SHOW_INCLUDE_REMOVED = Flag("--include-removed", desc="Also search soft-removed entries", arity=SWITCH)
FLAG_TODO_SHOW_INCLUDE_ARTIFACT_CONTENT = Flag(
    "--include-artifact-content",
    desc="Include artifact body content under artifact_content in the payload",
    arity=SWITCH,
)

FLAG_TODO_REACTIVATE_ID = Flag("--id", desc="Restore a specific retained row by durable id", arity=VALUE)
FLAG_TODO_RETURN_REASON = Flag(
    "--reason", desc="Why independently established code-conformance evidence requires another work cycle", arity=VALUE
)
FLAG_TODO_RETURN_EVIDENCE = Flag("--evidence", desc="Address of the code-conformance finding", arity=VALUE)

# =============================================================================
# todo stamp
# =============================================================================

FLAG_STAMP_VERDICT = Flag("--verdict", desc="approve | changes_requested | needs_work | needs_decision", arity=VALUE)
FLAG_STAMP_PHASE = Flag(
    "--phase",
    desc="Review phase the verdict belongs to (prd_review, architecture_review, plan_review, build_review)",
    arity=VALUE,
)
FLAG_STAMP_PRD_APPROVED = Flag("--prd-approved", desc="Mark PRD as approved by the human", arity=SWITCH)
FLAG_STAMP_TASK_APPROVED = Flag("--task-approved", desc="Authorize the current task-plan for a task", arity=SWITCH)
FLAG_STAMP_ARCHITECTURE_SKIPPED = Flag(
    "--architecture-skipped", desc="Skip architecture phase with a reason", arity=VALUE
)
FLAG_STAMP_DRIFT_REVIEWED = Flag(
    "--drift-reviewed", desc="Record drift review: <artifact> <substantive|cosmetic> <reason>", arity=GREEDY
)
FLAG_STAMP_BUILD_COMPLETE = Flag(
    "--build-complete",
    desc="Record the worker's build-complete claim; gates run on the next telec todo work dispatch",
    arity=SWITCH,
)
FLAG_STAMP_FINALIZE_READY = Flag("--finalize-ready", desc="Mark worktree as ready for finalize handoff", arity=SWITCH)
FLAG_STAMP_KICKBACK = Flag(
    "--kickback",
    desc=(
        "Work-orchestrator-only: send an unbuildable todo back to plan drafting; "
        "the platform then releases the claim and ends this work lane"
    ),
    arity=SWITCH,
)
FLAG_STAMP_REASON = Flag(
    "--reason",
    desc=("Reason recorded to input (required with --kickback / --task-outcome error / --diagnosis-unresolved)"),
    arity=VALUE,
)
FLAG_STAMP_TASK_OUTCOME = Flag(
    "--task-outcome",
    desc="Durable task firing outcome: success delivers/clears, error holds with --reason",
    arity=VALUE,
)
FLAG_STAMP_DIAGNOSIS_SETTLED = Flag(
    "--diagnosis-settled",
    desc=(
        "Bug lane: record the diagnosis artifact's current digest as the settled "
        "cause; a later revision invalidates the stamp"
    ),
    arity=SWITCH,
)
FLAG_STAMP_DIAGNOSIS_UNRESOLVED = Flag(
    "--diagnosis-unresolved",
    desc="Bug lane: hold the todo when the dispatched peer's diagnosis could not be settled; requires --reason",
    arity=SWITCH,
)
# Legacy creative-lifecycle and bookkeeping booleans: recognized by the handler
# today but absent from the documented surface. Declared hidden so the parser
# recognizes them without adding to the public --help/usage output.
FLAG_STAMP_REQUIREMENTS_READY = Flag("--requirements-ready", hidden=True, arity=SWITCH)
FLAG_STAMP_PLAN_READY = Flag("--plan-ready", hidden=True, arity=SWITCH)
FLAG_STAMP_DEFERRALS_PROCESSED = Flag("--deferrals-processed", hidden=True, arity=SWITCH)
FLAG_STAMP_DESIGN_SPEC_CONFIRMED = Flag("--design-spec-confirmed", hidden=True, arity=SWITCH)
FLAG_STAMP_ART_APPROVED = Flag("--art-approved", hidden=True, arity=SWITCH)
FLAG_STAMP_VISUALS_APPROVED = Flag("--visuals-approved", hidden=True, arity=SWITCH)
# Retired token: declared so the handler's own redirect message still fires
# instead of a generic "Unknown option" (see `_handle_todo_stamp`).
FLAG_STAMP_BUILD_STARTED = Flag("--build-started", hidden=True, arity=SWITCH)

# =============================================================================
# bugs
# =============================================================================

FLAG_BUG_SLUG = Flag("--slug", desc="Custom slug (default: auto-generated)", arity=VALUE)
FLAG_BUG_BODY = Flag("--body", desc="Detailed description body for bug.md", arity=VALUE)
FLAG_BUG_PROJECT = Flag(
    "--project",
    desc=(
        "Project that owns the defective code (registry name or slug). Defaults to the "
        "invoking cwd — where the symptom was OBSERVED, which is often not where the "
        "code lives. Set it whenever the two differ."
    ),
    arity=VALUE,
)
# Hidden pre-filing acknowledgment, recognized by the handler today but never
# declared on the surface (the interrogation gate is discovery-by-design).
FLAG_BUG_APPROVED = Flag("--approved", desc="Declares the pre-filing decisions were faced.", hidden=True, arity=SWITCH)

FLAG_SUPPRESS_REASON = Flag("--reason", desc="Human-readable justification (required)", arity=VALUE)
FLAG_SUPPRESS_MATCH = Flag("--match", desc="Match mode: substring (default, literal) or regex", arity=VALUE)
FLAG_SUPPRESS_DISPOSITION = Flag(
    "--disposition", desc="expected or wontfix (default: wontfix); record-only", arity=VALUE
)
FLAG_SUPPRESS_SOURCE_BUG = Flag(
    "--source-bug", desc="Slug of the originating bug whose triage produced this suppression", arity=VALUE
)
FLAG_SUPPRESS_EXPIRES = Flag(
    "--expires", desc="Optional ISO-8601 expiry after which the suppression lapses", arity=VALUE
)

# =============================================================================
# content dump
# =============================================================================

FLAG_CONTENT_SLUG = Flag("--slug", desc="Custom slug (default: auto-generated from text)", arity=VALUE)
FLAG_CONTENT_TAGS = Flag("--tags", desc="Comma-separated tags", arity=VALUE)
FLAG_CONTENT_AUTHOR = Flag("--author", desc="Author identity (default: daemon-resolved principal)", arity=VALUE)

# =============================================================================
# jobs report
# =============================================================================

FLAG_JOB_SUCCESS = Flag("--success", desc="Whether the job completed successfully", arity=VALUE)
FLAG_JOB_MESSAGE = Flag("--message", desc="Human-readable outcome summary", arity=VALUE)
FLAG_JOB_ITEMS_PROCESSED = Flag("--items-processed", desc="Count of processed items (default: 0)", arity=VALUE)
FLAG_JOB_ERROR = Flag("--error", desc="Error detail; repeat for multiple errors", arity=REPEATED)
FLAG_JOB_STATE_JSON = Flag("--state-json", desc="Opaque checkpoint replacement as a JSON object", arity=VALUE)

# =============================================================================
# events / mcp
# =============================================================================

FLAG_EVENTS_DOMAIN = Flag("--domain", desc="Filter by owner: the first segment of the type name", arity=VALUE)

FLAG_MCP_EXCLUDE = Flag("--exclude", desc="Server slug to omit; repeat for specialized procedures", arity=REPEATED)
FLAG_MCP_JSON = Flag("--json", desc="Print raw JSON response", arity=SWITCH)
FLAG_MCP_CALL_JSON = Flag("--json", desc="JSON object arguments for the selected tool", arity=VALUE)

# =============================================================================
# config
# =============================================================================

FLAG_CONFIG_FORMAT = Flag("--format", "-f", desc="Output format: yaml or json", arity=VALUE)
FLAG_CONFIG_FROM_FILE = Flag("--from-file", desc="Read patch YAML from this file path", arity=VALUE)
FLAG_CONFIG_YAML = Flag("--yaml", "-y", "Inline YAML patch", arity=VALUE)
FLAG_CONFIG_REVISION = Flag("--revision", desc="The subject's revision read before this patch", arity=VALUE)
FLAG_CONFIG_REMOVE = Flag("--remove", desc="Remove the addressed instance instead of patching it", arity=SWITCH)

FLAG_PEOPLE_EMAIL = Flag("--email", desc="Person's email address", arity=VALUE)
FLAG_PEOPLE_ROLE = Flag("--role", desc="Person's role", arity=VALUE)
FLAG_PEOPLE_USERNAME = Flag("--username", desc="Person's username", arity=VALUE)
FLAG_PEOPLE_SLUG = Flag("--slug", desc="Person slug (optional; derived from the name when omitted)", arity=VALUE)
FLAG_PEOPLE_DELETE_DIR = Flag(
    "--delete-dir", desc="Also delete the person's directory under ~/.teleclaude/people", arity=SWITCH
)

FLAG_TTS_YES = Flag("--yes", desc="Confirm the destructive dependency removal", arity=SWITCH)

# =============================================================================
# history
# =============================================================================

FLAG_HISTORY_AGENT = Flag("--agent", "-a", "Agent name(s) or 'all' (default: all)", arity=VALUE)
FLAG_HISTORY_SHOW_AGENT = Flag("--agent", "-a", "Agent name or 'all' (default: all)", arity=VALUE)
FLAG_HISTORY_LIMIT = Flag("--limit", "-l", "Max results to show (default: 20)", arity=VALUE)
FLAG_HISTORY_INCLUDE_FOCUSED = Flag(
    "--include-focused", desc="Also search focused-role sessions (reviewers, builders)", arity=SWITCH
)
FLAG_HISTORY_INCLUDE_WORKERS_ALIAS = Flag(
    "--include-workers", desc="Legacy alias for --include-focused", hidden=True, arity=SWITCH
)
FLAG_HISTORY_IDENTITY = Flag("--identity", desc="Filter by human identity or transcript source identity", arity=VALUE)
FLAG_HISTORY_JSON = Flag("--json", desc="Emit machine-readable JSON", arity=SWITCH)
FLAG_HISTORY_RAW = Flag("--raw", desc="Show raw transcript instead of mirror text", arity=SWITCH)

# =============================================================================
# memories
# =============================================================================

FLAG_MEMORIES_LIMIT = Flag("--limit", desc="Max results (default: 50)", arity=VALUE)
FLAG_MEMORIES_TYPE = Flag("--type", desc="Filter by observation type stored in the schema", arity=VALUE)
FLAG_MEMORIES_SAVE_TITLE = Flag("--title", desc="Observation title", arity=VALUE)
FLAG_MEMORIES_SAVE_TYPE = Flag("--type", desc="Observation type", arity=VALUE)
FLAG_MEMORIES_SAVE_PROJECT = Flag("--project", desc="Project name", arity=VALUE)
FLAG_MEMORIES_BEFORE = Flag("--before", desc="Observations before anchor (default: 3)", arity=VALUE)
FLAG_MEMORIES_AFTER = Flag("--after", desc="Observations after anchor (default: 3)", arity=VALUE)
FLAG_MEMORIES_CURATION_SESSION = Flag(
    "--session", "-s", "The conversation session whose memories are curated", arity=VALUE
)
FLAG_MEMORIES_CURATION_TYPE = Flag("--type", desc="Observation type", arity=VALUE)
FLAG_MEMORIES_IDENTITY = Flag(
    "--identity",
    desc="The person (person:<slug>) or provider account (<provider>:<account>) memories are about",
    arity=VALUE,
)
FLAG_MEMORIES_DESK = Flag(
    "--desk", desc="The help desk (hd-company-<slug> or hd-project-<slug>) the memories are kept at", arity=VALUE
)
FLAG_MEMORIES_EXTRACTION = Flag("--extraction", desc="The extraction the change is made for", arity=VALUE)
FLAG_MEMORIES_FAIL_REASON = Flag("--reason", desc="Why the extraction could not be finished", arity=VALUE)
FLAG_MEMORIES_ADVANCE_TO = Flag("--to", desc="Timestamp (ISO8601) of the newest conversation entry read", arity=VALUE)

# =============================================================================
# code
# =============================================================================

FLAG_CODE_ALL_LINT = Flag("--all", desc="Run against all configured sources, skip workspace scoping", arity=SWITCH)
FLAG_CODE_ALL_TEST = Flag("--all", desc="Run all tests, skip workspace scoping", arity=SWITCH)
FLAG_CODE_UPDATE_SNAPSHOTS = Flag(
    "--update-snapshots",
    desc=(
        "Update snapshot files after reading diffs. Use only when test failures show "
        "snapshot deltas that match your intended change."
    ),
    arity=SWITCH,
)
FLAG_CODE_ALL_FORMAT = Flag("--all", desc="Format all configured sources, skip workspace scoping", arity=SWITCH)
FLAG_PUBLISH_BEFORE_SHA = Flag("--before-sha", desc="Literal range start commit id", hidden=True, arity=VALUE)
FLAG_PUBLISH_AFTER_SHA = Flag("--after-sha", desc="Literal publication commit id", hidden=True, arity=VALUE)
FLAG_MAINTENANCE_AFTER_SHA = Flag("--after-sha", desc="Recorded activation tip", hidden=True, arity=VALUE)
FLAG_MAINTENANCE_EVENT_ID = Flag("--event-id", desc="Recorded event activation id", hidden=True, arity=VALUE)
FLAG_MAINTENANCE_ACTION = Flag("--action", desc="Recorded maintenance action id", hidden=True, arity=VALUE)
FLAG_COMMIT_APPROVED = Flag(
    "--approved",
    desc=(
        "Agent-owned sealed commit gate. Required to commit; bare main invocation prints "
        "commit-first and review-routing guidance."
    ),
    arity=SWITCH,
)
FLAG_COMMIT_INCLUDE = Flag(
    "--include",
    desc="Declare files outside workspace scope to add to this commit (space-separated paths).",
    arity=GREEDY,
)
FLAG_COMMIT_ONLY = Flag(
    "--only",
    desc=(
        "Commit exactly these paths instead of the resolved workspace scope; intended for "
        "splitting a dirty scope into multiple commits."
    ),
    arity=GREEDY,
)
FLAG_COMMIT_TODO = Flag(
    "--todo",
    desc="Associate this commit with a recorded or planned todo slug",
    arity=VALUE,
)
FLAG_HUMAN_INVOLVED_COMMIT = FLAG_HUMAN_INVOLVED
FLAG_CODE_STAMP_VERDICT = Flag(
    "--verdict",
    desc="Outcome recorded on each commit: approve | request_changes",
    arity=VALUE,
)
FLAG_CODE_STAMP_REASON = Flag(
    "--reason",
    desc="Why the stamp was given; the author's discard of a candidate that owes no review names it here",
    arity=VALUE,
)
FLAG_SYNC_LIST = Flag("--list", desc="Show the steps a run would perform and run nothing", arity=SWITCH)

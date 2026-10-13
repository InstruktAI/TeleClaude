# TeleClaude CLI Surface

## `telec sessions`

Manage agent sessions

### `telec sessions list`

List sessions (default: spawned by current, --all for all)

**Usage:** `telec sessions list [--all] [--closed] [--job <value>] [--computer <host>]`

**Flags:**

- `--all`: Show all sessions, unattended procedure agents included
- `--closed`: Include closed sessions
- `--job`: Filter by job value
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Procedure agents that run unattended are listed only with --all (or by session id).
- An agent caller's default listing keeps its own children even with --job; `--all --job <procedure>` finds a procedure's agents.

### `telec sessions show`

Show one session's stored record (default: your own session)

**Usage:** `telec sessions show [<session_id>|self] [--computer <host>] [--full]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)
- `--full`: Show the complete stored record instead of the grouped detail

**Notes:**

- Default output groups the record as identity, origin, role, state, and wiring.
- --full shows the complete stored record, decoded, without the last-output text, the accepted-input fingerprint, the help-desk relay exchange, and the agent-status counter.
- A session is shown only when you could list it; `telec sessions list` shows what you can reach.
- For what a session said, use `telec sessions tail <session_id>` or `telec history show`.
- For the roster and a session's children, use `telec sessions list`.

### `telec sessions coordinate`

Adopt this session as the project's single coordinator (human-directed only; refuses if one is live)

### `telec sessions start`

Start a new agent session

**Usage:** `telec sessions start [--computer <host>] [--path <path>] [--agent <name>] [--mode <mode>] [--message <msg>] [--direct] [--company <slug>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)
- `--path`: Path to the project directory (optional; defaults to cwd)
- `--agent`: Agent: claude, codex, gemini, deepseek
- `--mode`: Thinking mode: fast, med, slow
- `--message`: Initial message to send
- `--direct`: Conversation mode: create direct link with caller and bypass listeners
- `--company`: Company this session operates the business of

**Notes:**

- Use --direct for peer conversation mode when you want shared linked output instead of worker supervision notifications.
- --detach: do not use unless explicitly instructed. Sanctioned only for a personal-assistant dispatching an orchestrator to a project. --detach disables notifications — you will not learn when the child finishes, so omit it whenever your next step depends on the result.

### `telec sessions send`

Send a message to a running session

**Usage:** `telec sessions send <session_id> [<message>] [--computer <host>] [--direct] [--close-link]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)
- `--direct`: Conversation mode: create shared direct link
- `--close-link`: Close direct link with target session (alias: --close_link)
- `--session` (`-s`): Session ID

**Notes:**

- Positional form is canonical: telec sessions send <session_id> <message>.
- One-time ignition: sending once with --direct establishes the link.
- After link creation, turn-complete outputs from linked peers are cross-shared automatically.
- Only one party needs to send with --direct to establish the link.
- Use --close-link to sever the direct link for all members.

### `telec sessions tail`

Get recent messages from a session's transcript

**Usage:** `telec sessions tail <session_id> [--since <ts>] [--tools] [--thinking] [--full] [--pane]`

**Flags:**

- `--session` (`-s`): Session ID
- `--since`: ISO8601 timestamp filter
- `--tools`: Include tool use entries
- `--thinking`: Include thinking blocks
- `--full`: Show all projected messages instead of the latest user turn
- `--pane`: Show the current terminal pane instead of transcript messages
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec sessions run`

Run a canonical command on a new agent session

**Usage:** `telec sessions run [--command <cmd>] [--path <path>] [--args <val>] [--agent <name>] [--mode <mode>] [--computer <host>] [--subfolder <dir>] [--additional-context <ctx>] [--company <slug>]`

**Flags:**

- `--command`: Bare canonical command (e.g. build)
- `--path`: Path to the project directory (optional; defaults to cwd)
- `--args`: Command arguments
- `--agent`: Agent: claude, codex, gemini, deepseek
- `--mode`: Thinking mode: fast, med, slow
- `--computer` (`-c`): Target computer (optional; defaults to local)
- `--subfolder`: Subdirectory within the project
- `--additional-context`: Additional context for the worker, appended to startup message
- `--company`: Company this session operates the business of

**Notes:**

- Creates a fresh session and runs the bare canonical command as the first agent message.
- Worker lifecycle commands: build, review-build, finalize.
- --detach: do not use unless explicitly instructed. Sanctioned only for a personal-assistant dispatching an orchestrator to a project. --detach disables notifications — you will not learn when the child finishes, so omit it whenever your next step depends on the result.

### `telec sessions run-pa`

Start the caller's personal assistant in their own workspace

**Usage:** `telec sessions run-pa [<brief>]`

### `telec sessions revive`

Revive session by TeleClaude session ID

**Usage:** `telec sessions revive <session_id>`

**Flags:**

- `--agent`: Treat session_id as native agent session ID for the given agent
- `--attach`: Attach to tmux session after revive
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Restarts an ended session's agent with the full prior transcript, so the agent resumes with its original context intact.
- Without --agent, session_id is a TeleClaude session ID.
- With --agent, session_id is a native agent session ID resolved via the specified agent.

### `telec sessions end`

End a session, or every direct child of the calling session when targetless

**Usage:** `telec sessions end [<session_id>] [--computer <host>]`

**Flags:**

- `--session` (`-s`): Session ID
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- With no target, closes every live direct child of the calling session across computers.
- Targetless cleanup is idempotent and rejects --computer so caller scope cannot be narrowed.

### `telec sessions unsubscribe`

Stop receiving notifications from a session

**Usage:** `telec sessions unsubscribe <session_id>`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec sessions restart`

Restart an agent session ('self' to restart own session)

**Usage:** `telec sessions restart <session_id> [--handoff [<agent>]]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)
- `--handoff`: Continue with automatic or named successor agent

### `telec sessions result`

Send a formatted result to the session's user

**Usage:** `telec sessions result <content> [--format <fmt>]`

**Flags:**

- `--format`: Output format: markdown, html

### `telec sessions file`

Send a file to the session's user

**Usage:** `telec sessions file [--path <path>] [--filename <name>] [--caption <text>]`

**Flags:**

- `--path`: File path on the daemon host
- `--filename`: Display filename
- `--caption`: Optional caption

### `telec sessions escalate`

Escalate a help-desk visitor to everyone in the desk's scope in its escalation thread

**Usage:** `telec sessions escalate [--customer <name>] [--reason <text>] [--summary <text>]`

**Flags:**

- `--customer`: Customer name
- `--reason`: Reason for escalation
- `--summary`: Context summary for the people notified

## `telec reminders`

Manage durable reminders for the calling session

### `telec reminders set`

Arm or atomically replace a session-local reminder

**Usage:** `telec reminders set <slug> [--after <duration> | --at <RFC3339>] [--intent <text>] [--repeat] [--slug <target>]`

**Flags:**

- `--after`: Relative duration such as 30s, 5m, 2h, or 1d
- `--at`: Absolute RFC3339 instant
- `--intent`: Agent-authored generic reminder intent
- `--repeat`: Repeat a relative generic reminder
- `--slug`: Target work slug for orchestration-watch

### `telec reminders list`

List every live reminder owned by the calling session

### `telec reminders cancel`

Idempotently cancel one or all caller-owned reminders

**Usage:** `telec reminders cancel [<slug>] [--all]`

**Flags:**

- `--all`: Cancel all reminders owned by the calling session

## `telec computers`

Manage computer inventory

### `telec computers list`

List available computers (local + cached remote)

## `telec projects`

Manage project inventory and plumbing

### `telec projects list`

List projects on local and remote computers

**Usage:** `telec projects list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

## `telec agents`

Manage agent dispatch status and availability

### `telec agents availability`

Get current availability for all agents

**Usage:** `telec agents availability [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec agents status`

Set dispatch status for a specific agent

**Usage:** `telec agents status <agent> [--status <val>] [--reason <text>] [--model <model>] [--until <ts>] [--clear] [--computer <host>]`

**Flags:**

- `--status`: Status: available, unavailable, degraded
- `--reason`: Reason for status change
- `--model`: Scope the status to one declared model
- `--until`: ISO8601 UTC expiry for unavailable or degraded
- `--clear`: Reset to available immediately
- `--computer` (`-c`): Target computer (optional; defaults to local)

## `telec operations`

Inspect durable long-running operations

### `telec operations get`

Fetch durable operation status by operation_id

**Usage:** `telec operations get <operation_id> [-c/--computer <computer>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

## `telec version`

Print version, channel, and commit

## `telec message`

Send a message to a person

**Usage:** `telec message <text> [--recipient <slug>] [--file <path>] [--subject <text>] [--channel <name>]`

**Flags:**

- `--recipient`: Person slug; defaults to the caller's authority
- `--file`: Path to a single file to attach (Telegram, Discord, email only)
- `--subject`: Email subject line; ignored on channels without a subject concept
- `--channel`: Override channel: telegram, discord, whatsapp, email

**Notes:**

- Recipient-owned routing: defaults to the person's configured preferred_channel (email when unset).
- Without --recipient, the recipient is the person the calling session runs under; system authority defaults to platform admins.
- The message text is the file's caption on Telegram/Discord; on email it is the body and the file is an attachment.
- A file directed at a WhatsApp delivery is an actionable error — WhatsApp has no media-send capability here.
- Discover a person's slug via 'telec config person list' to use with --recipient.

## `telec docs`

Query documentation snippets

**Notes:**

- Two-phase flow: use 'telec docs index' to discover IDs, then 'telec docs get <id...>' to fetch content.
- Omitting --areas and/or --domains returns all values for that dimension; pass a comma-separated subset to filter.
- Example phase 1: telec docs index --areas policy,procedure --domains sdlc
- Example phase 2: telec docs get sdlc/policy/testing local/projects/teleclaude/spec/command-surface

### `telec docs index`

List snippet IDs and metadata (phase 1)

**Usage:** `telec docs index [--baseline-only] [--third-party] [--areas <principle|concept|policy|procedure|design|spec|adr>] [--domains <domain>] [--scope <global|project|person|company>] [--project <slug>] [--person <slug>] [--company <slug>] [--local] [--target <slug>]`

**Flags:**

- `--baseline-only` (`-b`): Show only baseline snippets
- `--third-party` (`-t`): Include third-party docs
- `--areas` (`-a`): Filter by taxonomy type (principle|concept|policy|procedure|design|spec|adr); omit for all
- `--domains` (`-d`): Filter by published domain; omit for all
- `--scope`: Filter by snippet kind (global|project|person|company); a no-op with --local
- `--project`: Select the project's published snippets by slug
- `--person`: Select the person's published snippets by slug
- `--company`: Select the company's published snippets by slug
- `--local`: Select local snippets from the named or landed home
- `--target`: Filter to snippets delivered by slug

**Notes:**

- Pending snippets (those with delivered_by) append ` (delivered by: slug1,slug2)` at the end of the phase-1 line.

### `telec docs get`

Fetch full snippet content by ID (phase 2)

**Usage:** `telec docs get <id> [id...] [--scope <global|project|person|company>] [--project <slug>] [--person <slug>] [--company <slug>] [--target <slug>]`

**Flags:**

- `--scope`: Filter by snippet kind (global|project|person|company)
- `--project`: Select the project's published snippets by slug
- `--person`: Select the person's published snippets by slug
- `--company`: Select the company's published snippets by slug
- `--target`: Include the slug's planned sections and companion replacement body (default: strip all)

## `telec todo`

Manage work items

### `telec todo sync`

Copy todo state to other computers

**Usage:** `telec todo sync --project <slug>[,<slug>] --to <computer>[,<computer>]`

**Flags:**

- `--project`: Comma-separated project slugs whose todo state is copied
- `--to`: Comma-separated target computer names

**Notes:**

- The origin's todo state replaces each target checkout's todo state; todo state is not merged.
- The origin daemon does not need to run. The admin is responsible for stopping work on the origin before syncing.
- The target database is checked for integrity after each copy; each project and target pair reports its own outcome.
- The installer provisions sqlite3_rsync on every computer; run make install on both sides before syncing.

### `telec todo create`

Create a todo with substantive content

**Usage:** `telec todo create <slug> <content> --kind <feature|change|bug|task> [--approved] [--after <deps>] [--schedule <value>] [--icebox] [--project-root <path>] [--group <parent-slug>] [--plan] [--human-involved <reason>] [--computer <host>]`

**Flags:**

- `--after`: Comma-separated dependency slugs
- `--schedule`: Task-only schedule: ISO-8601 instant or cron:<minute hour day month weekday> (0/7=Sunday)
- `--kind`: The work-unit's entry point into the lifecycle: feature|change|bug|task. Required when creating a todo. --kind task is side-effect-only and never touches the repo (sdlc/spec/todo-kind-task) — code work is change/feature/bug.
- `--approved`: Declares the pre-creation decisions were faced. Without it a complete creation request creates nothing and points to sdlc/policy/todo-creation-discipline.
- `--icebox`: Create future todo parked in the icebox; does not auto-spawn
- `--project-root` (`-p`): Target an explicit project root instead of the invocation cwd
- `--group`: Attach the new todo as a child of <parent-slug>, making the parent a holder. Grouping moves the parent's pending documentation ownership to the first grouped child: every in-body marker, companion filename, and delivered_by membership naming the parent is rewritten to that child and committed as part of the same transition.
- `--plan`: For --kind change, content seeds implementation-plan as a draft basis; for --kind task, content is the pre-authorized task-plan.
- `--human-involved`: Report a human's presence at this act, measured from their last input. The non-empty reason stays ephemeral; an observation outside the recency window records false without failing the act; omission records false and never inherits from another action.
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Creates the todo entry, canonical state, and stores content as the input artifact.
- --human-involved requires a non-empty reason and resolves the record from observed recency: a stale declaration records false and the todo is still created. The reason is never stored; omission records false and does not affect later actions.
- Content IS the input artifact — the author's INTENT: WHAT and WHY in operator language, affected surfaces, acceptance shape, brownfield grounding. HOW and doc routing are preparation's to derive. Per sdlc/policy/preparation-artifact-quality (Input artifact quality): HOW is the prepare phase's hypothesis to verify, doc routing is not the input's (general/policy/documentation-discipline), and an ADR is governed by general/policy/adr-discipline (default none, never by process step). Any HOW or doc instruction left in content is an unverified hypothesis, not a directive. (--plan is the deliberate exception: its content is a complete implementation-plan, not an input.)
- Use --icebox for ideas and future work at any stage; an iced todo enters the lifecycle when unfrozen, once valid. Hidden --hold is an exceptional brake for valid work awaiting an external gate. --group <parent-slug> creates a complete grouped child in one call and makes the parent a structural holder via the existing derivation; the first grouped child strips the parent's todo_state while preserving all its artifacts as frozen evidence, and is refused once the parent's lifecycle_phase has reached prepared or the work lane, so build, review, and finalize state is never shredded. Grouping also moves the parent's pending documentation ownership to the first grouped child: every in-body marker, companion filename, and delivered_by membership naming the parent is rewritten to that child and committed as part of the same transition.
- The filer always supplies --kind, choosing one of the four lifecycle entry points.
- --plan is valid with --kind change or --kind task.
- Settled, bounded work is executed in context (sdlc/policy/todo-creation-discipline).
- Process changes are agent-owned (sdlc/policy/process-change-authority): file them on the ordinary path; only a consequence on the closed list of general/policy/human-contract waits for the human.

### `telec todo list`

List todo entries (source of truth for todo status)

**Usage:** `telec todo list [--include-icebox] [--icebox-only] [--include-delivered] [--delivered-only] [--include-removed] [--removed-only] [--since <when>] [--json] [--computer <host>]`

**Flags:**

- `--include-icebox` (`-i`): Include icebox items
- `--icebox-only` (`-o`): Show only icebox items
- `--include-delivered` (`-d`): Include delivered items
- `--delivered-only`: Show only delivered items
- `--include-removed` (`-r`): Include soft-removed items
- `--removed-only`: Show only soft-removed items
- `--since`: Only delivered entries at/after this point: duration (7d, 72h, 2w) or ISO date (2026-05-01). Implies --include-delivered.
- `--json`: Output as a sectioned JSON object (active/delivered/icebox/removed trees)
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Output is sectioned into active/delivered/icebox/removed trees; delivered history groups by membership and sorts newest first.
- CONTRACT CHANGE: --json now emits a nested object keyed by section (active/delivered/icebox/removed), each a tree with `children`; previously a flat list. Empty todo list emits `{}`. Text output no longer appends a [status] suffix.
- --include-delivered returns the full delivery history; scope it with --since.
- --since accepts a relative duration (7d, 72h, 2w) or an ISO date/timestamp.
- --since alone implies --include-delivered; combine with --delivered-only to exclude active items.
- --include-removed interleaves soft-removed entries; each removed row renders with its todo id and removed_at age.

### `telec todo design`

Run the creative state machine

**Usage:** `telec todo design [<slug>] [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec todo remove`

Soft-remove a todo: the durable record (todo entry + state + all artifacts and version history) is retained for a fixed grace window; the working resources (worktree + branch + workspace) are released immediately. After the window elapses, background maintenance hard-purges the row by id. Reactivation is row-id-addressed (see the downstream recovery surface) and fail-closed on a live same-slug twin.

**Usage:** `telec todo remove <slug> [--force] [--computer <host>]`

**Flags:**

- `--force`: Override live-work removal refusal
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Returns an operation receipt without waiting; the outcome is delivered to the calling session and read with `telec operations get <operation_id>`.

### `telec todo freeze`

Move todo to icebox

**Usage:** `telec todo freeze <slug> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec todo unfreeze`

Promote todo from icebox

**Usage:** `telec todo unfreeze <slug> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec todo deliver`

Move todo to delivered

**Usage:** `telec todo deliver <slug> [--commit <hash>] [--computer <host>]`

**Flags:**

- `--commit`: The commit that delivered the slug. The integrator always supplies its own pushed commit and withholds delivery until that commit is confirmed on origin/main. Never inferred from HEAD, which is routinely an unrelated commit. It is required for feature, change, and bug deliveries; task deliveries may omit it.
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec todo update`

Update a todo slug, group, dependencies, or kind

**Usage:** `telec todo update <slug> [--slug <new>] [--group <parent-slug>] [--after <dep>]... [--schedule <value>] [--kind <feature|change|bug|task>] [--hold --reason <text>] [--release] [--unclaim] [--force] [--computer <host>]`

**Flags:**

- `--slug`: New todo slug; delegates to the durable rename engine
- `--group`: Move into this holder or pre-prepared todo; pass an empty value to remove the todo from its group
- `--after`: Dependency slug(s); replaces the full set. CSV accepted: --after parent-a,parent-b. Repeated flags accepted for compatibility: --after parent-a --after parent-b. Use --after "" to clear all dependencies.
- `--schedule`: Task-only schedule; pass an empty value to clear (cron weekday 0/7=Sunday)
- `--kind`: New todo kind: feature|change|bug|task
- `--hold`: Set the per-todo automatic dispatch brake
- `--reason`: State why a --hold waits, or the gate or owner it awaits; required with --hold
- `--release`: Release the per-todo automatic dispatch brake
- `--unclaim`: Release the caller-owned runner claim without ending the session
- `--force`: Allow permanent orphan-artifact handling for kind migrations
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Mutates slug, group, deps, kind, or hold; --after replaces the full dependency set.
- --group uses the same holder eligibility as create --group; pass an empty value to clear membership.
- Group membership and an after dependency on the same holder or ancestor are mutually exclusive.
- Agent callers may update only an unclaimed todo or one held by their claiming group; a live foreign claim is refused with the holder named.
- Kind and slug changes are refused after build starts; --after remains allowed.
- --hold requires --reason; --reason is refused without --hold, and --hold and --release are mutually exclusive.
- --unclaim clears the caller-owned runner claim; --release only clears the dispatch brake.
- --force only applies to kind orphan handling.
- Combining --slug with other legs is staged, not a single atomic patch.
- The --slug form returns an operation receipt without waiting; the outcome is delivered to the calling session and read with `telec operations get <operation_id>`.

### `telec todo prepare`

Run the Phase A (prepare) state machine

**Usage:** `telec todo prepare <slug> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Returns an operation receipt without waiting; the outcome is delivered to the calling session and read with `telec operations get <operation_id>`.

### `telec todo work`

Run the Phase B (work) state machine

**Usage:** `telec todo work [<slug>] [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Returns an operation receipt without waiting; the outcome is delivered to the calling session and read with `telec operations get <operation_id>`.

### `telec todo integrate`

Run the Phase C (integrate) state machine

**Usage:** `telec todo integrate [<slug>] [--abandon] [--computer <host>]`

**Flags:**

- `--abandon`: Park the current CONTENT_GATE_BLOCKED candidate as an ungroundable content-gate concern. The state machine resets the integration worktree to the frozen pre-merge SHA and parks — refused when the checkpoint is not at that phase.
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Returns an operation receipt without waiting; the outcome is delivered to the calling session and read with `telec operations get <operation_id>`.

### `telec todo artifacts`

Manage todo artifacts in the database

#### `telec todo artifacts list`

List artifacts for a todo

**Usage:** `telec todo artifacts list <slug> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec todo artifacts read`

Read a todo artifact

**Usage:** `telec todo artifacts read <slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec todo artifacts write`

Write a todo artifact

**Usage:** `telec todo artifacts write <slug> <name: input|prd|architecture|diagnosis|investigation|implementation-plan|task-plan|quality-checklist|design-spec|deferrals|log|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> <content> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Legacy bug artifacts are read-only; write bug todo content to input.

#### `telec todo artifacts diff`

Show a unified diff between two artifact versions

**Usage:** `telec todo artifacts diff <slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> <old-digest> <new-digest> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Looks up both versions by digest in the artifact version history and prints a unified diff between them.
- Used by the prepare loop to show reviewers what changed since the last approved digest.

#### `telec todo artifacts remove`

Remove a todo artifact and its version history

**Usage:** `telec todo artifacts remove <slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Refuses input because it is the seed artifact for a todo.
- Missing artifacts are treated as a successful no-op.

### `telec todo show`

Show diagnostic state payload for a todo; artifact bodies are omitted by default

**Usage:** `telec todo show <slug> [--include-removed] [--include-artifact-content] [--computer <host>]`

**Flags:**

- `--include-removed`: Also search soft-removed entries
- `--include-artifact-content`: Include artifact body content under artifact_content in the payload
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec todo reactivate`

Restore a soft-removed todo

**Usage:** `telec todo reactivate <slug> | --id <row-id> [--computer <host>]`

**Flags:**

- `--id`: Restore a specific retained row by durable id
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Resolves the slug against soft-removed rows and restores the uniquely matching entry.
- Use --id after a removed-slug response identifies multiple retained rows.
- On success: status reverts to prev_status and outgoing dependencies are replayed.

### `telec todo stamp`

Stamp a verdict or readiness marker into todo state

**Usage:** `telec todo stamp <slug> [--verdict <v> --phase <p>] [--prd-approved] [--task-approved] [--architecture-skipped <reason>] [--drift-reviewed <artifact> <verdict> <reason>] [--build-complete] [--finalize-ready] [--kickback --reason <reason>] [--task-outcome <success|error> [--reason <text>]] [--diagnosis-settled] [--diagnosis-unresolved --reason <reason>] [--computer <host>]`

**Flags:**

- `--verdict`: approve | changes_requested | needs_work | needs_decision
- `--phase`: Review phase the verdict belongs to (prd_review, architecture_review, plan_review, build_review)
- `--prd-approved`: Mark PRD as approved by the human
- `--task-approved`: Authorize the current task-plan for a task
- `--architecture-skipped`: Skip architecture phase with a reason
- `--drift-reviewed`: Record drift review: <artifact> <substantive|cosmetic> <reason>
- `--build-complete`: Record the worker's build-complete claim; gates run on the next telec todo work dispatch
- `--finalize-ready`: Mark worktree as ready for finalize handoff
- `--kickback`: Work-orchestrator-only: send an unbuildable todo back to plan drafting; the platform then releases the claim and ends this work lane
- `--reason`: Reason recorded to input (required with --kickback / --task-outcome error / --diagnosis-unresolved)
- `--task-outcome`: Durable task firing outcome: success delivers/clears, error holds with --reason
- `--diagnosis-settled`: Bug lane: record the diagnosis artifact's current digest as the settled cause; a later revision invalidates the stamp
- `--diagnosis-unresolved`: Bug lane: hold the todo when the dispatched peer's diagnosis could not be settled; requires --reason
- `--computer` (`-c`): Target computer (optional; defaults to local)

## `telec bugs`

Bug reporting and tracking

### `telec bugs report`

Interrogate the pre-filing decisions before scaffolding a bug; a completed filing enters the bug lane and the lifecycle router dispatches /prepare

**Usage:** `telec bugs report <description> [--slug <slug>] [--body <text>] [--project <name>] [--human-involved <reason>] [--computer <host>]`

**Flags:**

- `--slug`: Custom slug (default: auto-generated)
- `--body`: Detailed description body for bug.md
- `--project`: Project that owns the defective code (registry name or slug). Defaults to the invoking cwd — where the symptom was OBSERVED, which is often not where the code lives. Set it whenever the two differ.
- `--human-involved`: Report a human's presence at this act, measured from their last input. The non-empty reason stays ephemeral; an observation outside the recency window records false without failing the act; omission records false and never inherits from another action.
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- An invocation carrying only the report payload does not file: it presents the required pre-filing decisions (bug or change, fix-directly, duplication, ordering, validity and ownership) and only that output names how to complete the filing.
- File against the project that OWNS the defective code, not the one you happen to be standing in. Platform behavior misbehaving inside a side project is a platform bug: pass --project so the orchestrator that picks it up can actually deliver the fix. A bug filed where the code does not live cannot be fixed there and gets re-filed later, carrying stale conclusions with it. A symptom that stops once the side project's own configuration matches a TeleClaude default (a .gitignore entry, a blessed template line) is the side project's to fix, there. When you cannot tell which project owns it, ask.
- The filing surface interrogates for duplication up front (todo list, in-flight bug lanes, suppressions); diagnose remains the deeper same-defect dedup that can still retire a twin the up-front check missed.
- Your reported todo may therefore still be removed as a duplicate at diagnose — that is expected dedup, not a dropped report. The surviving todo carries the fix.
- A report names the observed wrong behavior; what is missing and how to fix it are preparation's to derive. A bug whose cause is a process defect may correct that defect within its symptom and causal scope (sdlc/policy/process-change-authority).
- Require the observed symptom plus its trigger context verbatim in the description or --body: what happened, what was expected, and what preceded it. A report with no trigger context is unauditable later — this is the reporting invitation the schema alone cannot supply.

### `telec bugs list`

List in-flight bug fixes with status

**Usage:** `telec bugs list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec bugs suppress`

Register a known-issue suppression so the log bug hunter stops re-filing a triaged signal

**Usage:** `telec bugs suppress "<pattern>" --reason <r> [--match substring|regex] [--disposition expected|wontfix] [--project <name>] [--source-bug <slug>] [--expires <when>] [--computer <host>]`

**Flags:**

- `--reason`: Human-readable justification (required)
- `--match`: Match mode: substring (default, literal) or regex
- `--disposition`: expected or wontfix (default: wontfix); record-only
- `--project`: Project name or slug from the project registry
- `--source-bug`: Slug of the originating bug whose triage produced this suppression
- `--expires`: Optional ISO-8601 expiry after which the suppression lapses
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- The ledger is the log bug hunter's allowlist: a matched candidate error line is treated as already triaged and does not dispatch a session.
- Matching is literal (substring) or a compiled regex; a regex pattern is validated here and rejected if it does not compile.
- Author the pattern to target the invariant signal (a stable reason token), never a volatile value like a millisecond figure.

### `telec bugs suppressions`

List the active known-issue suppressions for a project

**Usage:** `telec bugs suppressions [--project <name>] [--computer <host>]`

**Flags:**

- `--project`: Project name or slug from the project registry
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec bugs unsuppress`

Remove a known-issue suppression by id so its signal is eligible for filing again

**Usage:** `telec bugs unsuppress <id> [--project <name>] [--computer <host>]`

**Flags:**

- `--project`: Project name or slug from the project registry
- `--computer` (`-c`): Target computer (optional; defaults to local)

## `telec content`

Manage content pipeline

### `telec content dump`

Fire-and-forget content dump to publications inbox

**Usage:** `telec content dump <description-or-text> [--slug <slug>] [--tags <tags>] [--author <name>]`

**Flags:**

- `--slug`: Custom slug (default: auto-generated from text)
- `--tags`: Comma-separated tags
- `--author`: Author identity (default: daemon-resolved principal)

**Notes:**

- Creates publications/inbox/YYYYMMDD-<slug>/ with content.md and meta.yaml.
- Author defaults to the principal the daemon resolves for the caller.
- Emits a content.dumped notification event if the notification service is available.
- Slug collision is handled automatically by appending a counter suffix.

## `telec jobs`

Recurring job commands

### `telec jobs list`

List jobs visible to the current project

**Usage:** `telec jobs list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec jobs status`

Show runtime status for jobs visible to the current project

**Usage:** `telec jobs status [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec jobs enable`

Subscribe the current project to a published job

**Usage:** `telec jobs enable <name> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec jobs disable`

Unsubscribe the current project from a published job

**Usage:** `telec jobs disable <name> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec jobs run`

Run a job in the current project

**Usage:** `telec jobs run <name> [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec jobs report`

Write a structured recurring job result record

**Usage:** `telec jobs report <name> --success <true|false> --message <text> [--items-processed <n>] [--error <text> ...] [--state-json <object>]`

**Flags:**

- `--success`: Whether the job completed successfully
- `--message`: Human-readable outcome summary
- `--items-processed`: Count of processed items (default: 0)
- `--error`: Error detail; repeat for multiple errors
- `--state-json`: Opaque checkpoint replacement as a JSON object

**Notes:**

- The positional is the job's declared name and identity. Validated against configured jobs; writes the current record under state/runs/<project>/<name>.json.
- --state-json replaces the opaque checkpoint object; omission preserves the previous checkpoint.
- This command writes locally and does not call the daemon.

## `telec events`

Event catalog and platform commands

### `telec events list`

List declared event types: name, version, what they are about, description

**Usage:** `telec events list [--domain <name>]`

**Flags:**

- `--domain`: Filter by owner: the first segment of the type name

### `telec events schema`

Show one event type's declaration: subject, home, related kinds, state, and data fields

**Usage:** `telec events schema <event>`

## `telec signals`

Signal pipeline status and diagnostics

### `telec signals status`

Show signal pipeline counts and last ingest time

## `telec mcp`

Use configured MCP servers through TeleClaude lazy runtime

### `telec mcp list`

List configured MCP servers without starting them

**Usage:** `telec mcp list [--exclude <slug>] [--json]`

**Flags:**

- `--exclude`: Server slug to omit; repeat for specialized procedures
- `--json`: Print raw JSON response

### `telec mcp list-tools`

Initialize one MCP server and list its tools

**Usage:** `telec mcp list-tools <slug> [--json]`

**Flags:**

- `--json`: Print raw JSON response

### `telec mcp call`

Call one MCP tool through the lazy runtime

**Usage:** `telec mcp call <slug> <tool> --json <arguments-json>`

**Flags:**

- `--json`: JSON object arguments for the selected tool

## `telec auth`

Terminal login identity commands

### `telec auth login`

Set terminal login identity for this TTY

**Usage:** `telec auth login <email>`

**Notes:**

- Stores auth state in a TTY-scoped file.
- Running login again on the same TTY overwrites the existing file.

### `telec auth whoami`

Show the identity carried by this session or terminal

### `telec auth logout`

Clear terminal login identity for this TTY

## `telec config`

Manage configuration

### `telec config computer`

Machine configuration

#### `telec config computer list`

List computer subjects (singleton)

**Usage:** `telec config computer list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config computer get`

Get the machine configuration

**Usage:** `telec config computer get [paths...] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config computer init`

Converge the machine configuration without overwriting existing values

**Usage:** `telec config computer init [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config computer patch`

Patch the machine configuration

**Usage:** `telec config computer patch --revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--revision`: The subject's revision read before this patch
- `--yaml` (`-y`): Inline YAML patch
- `--from-file`: Read patch YAML from this file path
- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec config global`

Global configuration (cross-project overlay)

#### `telec config global list`

List global subjects (singleton)

**Usage:** `telec config global list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config global get`

Get the global configuration

**Usage:** `telec config global get [paths...] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config global init`

Converge the global configuration without overwriting existing values

**Usage:** `telec config global init [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config global patch`

Patch the global configuration

**Usage:** `telec config global patch --revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--revision`: The subject's revision read before this patch
- `--yaml` (`-y`): Inline YAML patch
- `--from-file`: Read patch YAML from this file path
- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec config person`

Person configuration (identity + settings)

**Notes:**

- Patch naming `organization` is always refused — it is a read-only projection.

#### `telec config person list`

List registered person slugs

**Usage:** `telec config person list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config person get`

Get one person's configuration

**Usage:** `telec config person get <slug> [paths...] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config person init`

Create or converge a person without overwriting existing values

**Usage:** `telec config person init <name> --email <email> [--slug <slug>] [--role <role>] [--username <username>] [--computer <host>]`

**Flags:**

- `--email`: Person's email address
- `--slug`: Person slug (optional; derived from the name when omitted)
- `--role`: Person's role
- `--username`: Person's username
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config person patch`

Patch one person's configuration, or remove the person

**Usage:** `telec config person patch <slug> --revision <rev> [--yaml '...' | --from-file <path>] [--remove] [--delete-dir] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--revision`: The subject's revision read before this patch
- `--yaml` (`-y`): Inline YAML patch
- `--from-file`: Read patch YAML from this file path
- `--remove`: Remove the addressed instance instead of patching it
- `--delete-dir`: Also delete the person's directory under ~/.teleclaude/people
- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config person invite`

Generate (or rotate) invite links for a person on the mesh master

**Usage:** `telec config person invite <slug> [--json] [--computer <host>]`

**Flags:**

- `--json`: Emit machine-readable JSON output
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- The invitation runs on the mesh master from any computer: the token is issued there, where it is redeemed, and the links name the master's public bot endpoints.
- With no unique live master the command fails and changes nothing; addressing a computer that is not the master is refused with the master's name.
- A configured provider whose endpoint cannot be resolved is reported as unavailable; the other links are still returned, and so are all links when the email is not delivered.

#### `telec config person discord-voice-bot`

Bind the active Discord bot credential to a person's voice configuration

**Usage:** `telec config person discord-voice-bot <slug> [--json] [--computer <host>]`

**Flags:**

- `--json`: Emit machine-readable JSON output
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec config company`

Company configuration (roster, projects)

#### `telec config company list`

List registered company slugs

**Usage:** `telec config company list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config company get`

Get one company's configuration

**Usage:** `telec config company get <slug> [paths...] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config company init`

Scaffold a company without overwriting existing values

**Usage:** `telec config company init <name> [--slug <slug>] [--computer <host>]`

**Flags:**

- `--slug`: Company slug (optional; derived from the name when omitted)
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config company patch`

Patch one company's roster or fields

**Usage:** `telec config company patch <slug> --revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--revision`: The subject's revision read before this patch
- `--yaml` (`-y`): Inline YAML patch
- `--from-file`: Read patch YAML from this file path
- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config company help-desk-links`

Print the entry links of a company's help desk, hosted on the mesh master

**Usage:** `telec config company help-desk-links <slug> [--json] [--computer <host>]`

**Flags:**

- `--json`: Emit machine-readable JSON output
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Renders only on the mesh master and where the desk is enabled.

### `telec config project`

Project configuration

#### `telec config project list`

List registered project slugs

**Usage:** `telec config project list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config project get`

Get one project's configuration

**Usage:** `telec config project get <slug> [paths...] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config project create`

Create a new, empty project

**Usage:** `telec config project create <name> [--company <slug> | --path <dir>] [--computer <host>]`

**Flags:**

- `--company`: Create the project in this company's home, owned by the company (company members)
- `--path`: Create an ownerless platform project at this folder outside every home (platform administrators)
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Without a flag the project lands in your own projects area, owned by you.
- --company puts it in that company's projects area, owned by the company; any member of the company may. --path makes an ownerless platform project at a folder outside every home, for platform administrators; it never combines with --company.
- The name is the project's identity: an invalid name, or one another project on this computer already holds, is refused before anything is written.
- The project gets its own repository on main, declares its owner and declares no capabilities yet. Scaffold inside it, then run `telec config project adopt` there to declare them.

#### `telec config project adopt`

Register the folder you stand in as a project, where it is

**Notes:**

- Adopts the checkout that owns your current directory, or the directory itself when no repository holds it or only the global home's does.
- Inside a home the project is owned by that home and gets its own repository if it has none; a different declared owner is refused. Outside every home the declared owner stays. No file is moved.
- Writes nothing outside the project and the project registry.

#### `telec config project patch`

Patch one project's configuration

**Usage:** `telec config project patch <slug> --revision <rev> [--yaml '...' | --from-file <path>] [--format <fmt>] [--computer <host>]`

**Flags:**

- `--revision`: The subject's revision read before this patch
- `--yaml` (`-y`): Inline YAML patch
- `--from-file`: Read patch YAML from this file path
- `--format` (`-f`): Output format: yaml or json
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Writes the project's teleclaude.yml only — never commits.

#### `telec config project help-desk-links`

Print the entry links of a project's help desk, hosted on the mesh master

**Usage:** `telec config project help-desk-links <slug> [--json] [--computer <host>]`

**Flags:**

- `--json`: Emit machine-readable JSON output
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Renders only on the mesh master and where the desk is enabled.

### `telec config validate`

Full validation

**Usage:** `telec config validate [--computer <host>]`

**Flags:**

- `--json`: Emit machine-readable JSON output
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec config env`

Manage environment variables

#### `telec config env list`

List environment variables

**Usage:** `telec config env list [--computer <host>]`

**Flags:**

- `--json`: Emit machine-readable JSON output
- `--computer` (`-c`): Target computer (optional; defaults to local)

#### `telec config env set`

Set environment variables

**Usage:** `telec config env set <KEY=VALUE> ... [--json] [--computer <host>]`

**Flags:**

- `--json`: Emit machine-readable JSON output
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec config tts`

Manage TTS dependency provisioning

#### `telec config tts deprovision`

Disable TTS and remove the TTS-exclusive optional dependencies

**Usage:** `telec config tts deprovision [--yes] [--computer <host>]`

**Flags:**

- `--yes`: Confirm the destructive dependency removal
- `--computer` (`-c`): Target computer (optional; defaults to local)

**Notes:**

- Disables TTS, removes the TTS-exclusive deps (elevenlabs, the mlx text pipeline), and leaves deps shared with STT/summarization installed.
- Bare invocation prints this guard and makes no daemon call.
- Re-enabling TTS afterward lazily re-provisions the removed deps.

## `telec history`

Search and view agent session history

### `telec history search`

Search agent session transcripts

**Usage:** `telec history search [terms...] [--agent <name>] [--computer <host>] [--identity <value>] [--project <path>] [--limit <n>] [--include-workers] [--json]`

**Flags:**

- `--agent` (`-a`): Agent name(s) or 'all' (default: all)
- `--computer` (`-c`): Query one or more remote computers via daemon API
- `--limit` (`-l`): Max results to show (default: 20)
- `--include-workers`: Also search dispatched-worker sessions (reviewers, builders)
- `--identity`: Filter by human identity or transcript source identity
- `--project`: Filter by project name
- `--json`: Emit machine-readable JSON

### `telec history show`

Show full transcript for a session

**Usage:** `telec history show <session-id> [--agent <name>] [--computer <host>] [--thinking] [--raw] [--json]`

**Flags:**

- `--agent` (`-a`): Agent name or 'all' (default: all)
- `--computer` (`-c`): Query one or more remote computers via daemon API
- `--thinking`: Include thinking blocks
- `--raw`: Show raw transcript instead of mirror text
- `--json`: Emit machine-readable JSON

## `telec memories`

Read or remove durable observations about people. Memories capture meta-level things about who a person is — their relational stance, values, communication style, vision — never coding norms, architectural decisions, or operational gotchas (those live in policies, principles, and addenda). Memories are kept current by the memory agents a conversation session's end starts; other agents must never create them.

### `telec memories list`

List personal-preference observations about the human.

**Usage:** `telec memories list [--limit <n>] [--type <type>] [--project <name>]`

**Flags:**

- `--limit`: Max results (default: 50)
- `--type`: Filter by observation type stored in the schema
- `--project`: Filter by project name

### `telec memories search`

Search personal-preference observations about the human.

**Usage:** `telec memories search <query> [--limit <n>] [--type <type>] [--project <name>]`

**Flags:**

- `--limit`: Max results (default: 20)
- `--type`: Filter by observation type stored in the schema
- `--project`: Filter by project name

### `telec memories delete`

Delete a personal-preference observation by ID (typically run by the human while pruning).

**Usage:** `telec memories delete <id>`

### `telec memories scope`

Show the scope an identity (and desk) names for curation: its current memories, including those held under the person's bound provider accounts at the desk.

**Usage:** `telec memories scope --identity <identity> [--desk <desk-id>]`

**Flags:**

- `--identity`: The person (person:<slug>) or provider account (<provider>:<account>) memories are about
- `--desk`: The help desk (hd-company-<slug> or hd-project-<slug>) the memories are kept at
- `--session` (`-s`): The conversation session whose memories are curated

**Notes:**

- --session <session_id> remains accepted from workers that began before identity addressing.

### `telec memories add`

Add a current memory about the extraction's person, in the scope the extraction prepared.

**Usage:** `telec memories add --identity <identity> [--desk <desk-id>] --extraction <id> --type <type> <text>`

**Flags:**

- `--identity`: The person (person:<slug>) or provider account (<provider>:<account>) memories are about
- `--desk`: The help desk (hd-company-<slug> or hd-project-<slug>) the memories are kept at
- `--extraction`: The extraction the change is made for
- `--session` (`-s`): The conversation session whose memories are curated
- `--type`: Observation type

**Notes:**

- --session <session_id> remains accepted from workers that began before identity addressing.

### `telec memories update`

Replace the statement of a current memory in the extraction's scope.

**Usage:** `telec memories update <memory-id> --identity <identity> [--desk <desk-id>] --extraction <id> <text>`

**Flags:**

- `--identity`: The person (person:<slug>) or provider account (<provider>:<account>) memories are about
- `--desk`: The help desk (hd-company-<slug> or hd-project-<slug>) the memories are kept at
- `--extraction`: The extraction the change is made for
- `--session` (`-s`): The conversation session whose memories are curated

**Notes:**

- --session <session_id> remains accepted from workers that began before identity addressing.

### `telec memories retire`

Retire a current memory in the extraction's scope: it leaves use and stays recorded.

**Usage:** `telec memories retire <memory-id> --identity <identity> [--desk <desk-id>] --extraction <id>`

**Flags:**

- `--identity`: The person (person:<slug>) or provider account (<provider>:<account>) memories are about
- `--desk`: The help desk (hd-company-<slug> or hd-project-<slug>) the memories are kept at
- `--extraction`: The extraction the change is made for
- `--session` (`-s`): The conversation session whose memories are curated

**Notes:**

- --session <session_id> remains accepted from workers that began before identity addressing.

### `telec memories prospect`

Collect a business item from the extraction's desk conversation as a prospect for the desk's home.

**Usage:** `telec memories prospect --desk <desk-id> --extraction <id> --type <type> <text>`

**Flags:**

- `--desk`: The help desk (hd-company-<slug> or hd-project-<slug>) the memories are kept at
- `--extraction`: The extraction the change is made for
- `--session` (`-s`): The conversation session whose memories are curated
- `--type`: Observation type

**Notes:**

- --session <session_id> remains accepted from workers that began before identity addressing.

### `telec memories extraction`

Read an extraction's conversation material, or declare it finished or failed.

#### `telec memories extraction read`

Show the extraction's bounded conversation material, its coverage and scope, and the prospects already recorded from its source.

**Usage:** `telec memories extraction read <id>`

#### `telec memories extraction complete`

Declare the extraction's memory and prospect changes finished, including a read with none.

**Usage:** `telec memories extraction complete <id>`

#### `telec memories extraction fail`

Report that the extraction could not be finished; its stretch stays eligible.

**Usage:** `telec memories extraction fail <id> --reason <reason>`

**Flags:**

- `--reason`: Why the extraction could not be finished

### `telec memories advance`

Advance a conversation session's read point to the newest entry read; it never moves backwards.

**Usage:** `telec memories advance --session <session_id> --to <timestamp>`

**Flags:**

- `--session` (`-s`): The conversation session whose memories are curated
- `--to`: Timestamp (ISO8601) of the newest conversation entry read

**Notes:**

- Accepted only from workers that began before identity addressing, and only while no extraction is open.

### `telec memories timeline`

Show personal-preference observations around an anchor ID.

**Usage:** `telec memories timeline <id> [--before <n>] [--after <n>] [--project <name>]`

**Flags:**

- `--before`: Observations before anchor (default: 3)
- `--after`: Observations after anchor (default: 3)
- `--project`: Filter by project name

## `telec code`

Code quality and commit tools

**Notes:**

- test, format, install, and blueprint require the code capability.
- lint is available where code or docs is enabled; each check family follows its owning home's configuration.
- add, commit, and owners remain available when either code or docs is subscribed.

### `telec code blueprint`

Query the codebase Blueprint (structural blast-radius)

#### `telec code blueprint affected`

Print the blast-radius dependents of changed files

**Usage:** `telec code blueprint affected <changed-files>`

**Notes:**

- Maps each changed file to its symbols, runs a transitive reverse dependency traversal over the Blueprint, and prints the union of dependents with file:line.
- Waits briefly for recorded Blueprint maintenance when committed main has advanced. If no complete generation matching committed main can be established, prints unavailability and its recovery command; it never returns stale dependents as a current answer.

### `telec code lint`

Run checks selected by each owning home's configuration

**Flags:**

- `--all`: Run against all configured sources, skip workspace scoping

### `telec code test`

Run native make test

**Flags:**

- `--all`: Run all tests, skip workspace scoping
- `--update-snapshots`: Update snapshot files after reading diffs. Use only when test failures show snapshot deltas that match your intended change.

### `telec code format`

Run native make format

**Flags:**

- `--all`: Format all configured sources, skip workspace scoping

### `telec code add`

Declare files for the next commit (stages NEW, unmerged, or partial-staged tracked)

**Usage:** `telec code add <path> [<path> ...]`

**Notes:**

- Sealed equivalent of 'git add' for the three cases git's data model genuinely requires staging:
-   (1) NEW (untracked) files — must enter the index before commit pathspec can match.
-   (2) Unmerged-index files (post-conflict) — must be marked resolved before commit.
-   (3) Partial-staged tracked files (staged hunks + later working-tree delta) — must be fully (re)staged so the pathspec commit does not silently sweep in unstaged hunks. The partial-staging guard in `telec code commit` directs agents here for recovery.
- A successful call from inside the session's checkout declares its paths to session-scoping. Invoked from a different repository it stages as usual, declares nothing, and reports the paths as not declared. Modified-tracked files that are NOT partial-staged don't need staging — pathspec commits them straight from the working tree.
- A clean tracked path or a path that does not exist yet is declared the same way — declaring is bookkeeping for work about to start, not a claim about current git state, so declaring ahead of the first touch always succeeds.
- NEW files in scope are NOT auto-committed; this is the explicit declaration step. Without it, untracked files stay untracked (safety net for temp/scratch artifacts the agent may have created incidentally).
- Alternative one-shot form: telec code commit --approved '<msg>' --include <path>.

### `telec code owners`

Print live declaration owners for every dirty path in the canonical checkout

**Notes:**

- Prints one path-keyed JSON object for every dirty path of the project's canonical checkout.
- A value lists the live sessions that declared the path, or null when no live session declared it.

### `telec code commit`

Commit workspace-scoped changes via a pathspec-scoped commit (sealed; no git forwarding)

**Usage:** `telec code commit "<message>" [--approved] [--human-involved <reason>] [--include <path> ...] [--only <path> ...]`

**Flags:**

- `--approved`: Agent-owned sealed commit gate. Required to commit; bare main invocation prints commit-first and review-routing guidance.
- `--include`: Declare files outside workspace scope to add to this commit (space-separated paths).
- `--only`: Commit exactly these paths instead of the resolved workspace scope; intended for splitting a dirty scope into multiple commits.
- `--human-involved`: Report a human's presence at this act, measured from their last input. The non-empty reason stays ephemeral; an observation outside the recency window records false without failing the act; omission records false and never inherits from another action.

**Notes:**

- Accepts only: one quoted message, --approved, --human-involved <reason>, --include <path> ..., and --only <path> ... .
- Modified-tracked files in scope are auto-committed via pathspec straight from the working tree — no staging needed.
- NEW (untracked) files in scope are NOT auto-committed by default; declare them via `telec code add`, `--include`, or `--only` (safety net against incidental temp/scratch artifacts).
- --only commits exactly the declared paths and is mutually exclusive with --include.
- Unmerged-index files in pathspec are staged internally for the integrator conflict path.
- Without --approved on main: prints commit-first and review-routing guidance and exits.
- Pathspec = workspace scope plus --include paths, or exactly --only paths. Anything else in the index (foreign stage) is left untouched — there is no env-var bypass.
- The commit author is stamped as the resolved agent's bot identity (git --author); the message gains the branding line, Session:, and Human-Involved: — no Co-Authored-By trailer is ever added.
- In a todo worktree, a successful commit also publishes the branch to origin; a failed publish leaves the commit in place.

### `telec code stamp`

Record a commit-review outcome on commits that landed on main

**Usage:** `telec code stamp <sha>[,<sha>...] --verdict approve|request_changes [--reason <text>]`

**Flags:**

- `--verdict`: Outcome recorded on each commit: approve | request_changes
- `--reason`: Why the stamp was given; the author's discard of a candidate that owes no review names it here

**Notes:**

- A commit reviewer stamps its verdict on exactly the SHAs it reviewed. The author stamps approve with a reason on a review candidate that owes no review; discarding is not reviewing.
- The stamp lands in the review state of the todo whose lifecycle claim the stamping session, or the session that started it, holds; with no claim in that chain it lands on no todo.
- The record names the stamping session and the reason, so a discard stays distinguishable from a reviewer's verdict. A later stamp on a SHA supersedes the earlier one.
- A stamp covering a session's commits discharges that session's post-commit review prompt, whether the reviewer or the author gave it.
- Every SHA must be a commit reachable from main; otherwise nothing is recorded.

## `telec sync`

Run this root's maintenance on demand: the fallback for commit-boundary maintenance

**Usage:** `telec sync [--list]`

**Flags:**

- `--list`: Show the steps a run would perform and run nothing

**Notes:**

- Use it when commit-boundary maintenance did not run, or ran and left the root wrong: it performs every step the root's registry declares, in declared order, and reports each step's outcome as it completes.
- A failed step does not stop the later ones; the command exits non-zero when any step failed.
- Restarts, reloads and service deployment are never performed. When one is owed, the run ends by naming it and the command that performs it, and says so when it cannot tell.
- Uncommitted edits are named first, with the sessions holding them. Publication uses committed main state only; the other steps read the checkout as it stands.
- Runs only from the canonical checkout on main, in a directory holding its own teleclaude.yml; elsewhere it refuses and names where to run it.
- A step that an earlier commit-boundary run recorded as failed is named with its replay command; the standing integrator owns that replay.
- With --list, it prints the steps a run would perform and runs nothing.


# TeleClaude CLI Surface

## `telec sessions`

Manage agent sessions

### `telec sessions list`

List sessions (default: spawned by current, --all for all)

**Usage:** `telec sessions list [--all] [--closed] [--job <value>] [--computer <host>]`

**Flags:**

- `--all`: Show all sessions
- `--closed`: Include closed sessions
- `--job`: Filter by job value
- `--computer`: Filter to a specific computer

### `telec sessions start`

Start a new agent session

**Usage:** `telec sessions start [--computer <host>] [--path <path>] [--agent <name>] [--mode <mode>] [--message <msg>] [--direct]`

**Flags:**

- `--computer` (`-c`): Target computer (optional; defaults to local)
- `--path`: Path to the project directory (optional; defaults to cwd)
- `--agent`: Agent: claude, gemini, codex
- `--mode`: Thinking mode: fast, med, slow
- `--message`: Initial message to send
- `--direct`: Conversation mode: create direct link with caller and bypass listeners

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

**Notes:**

- Positional form is canonical: telec sessions send <session_id> <message>.
- One-time ignition: sending once with --direct establishes the link.
- After link creation, turn-complete outputs from linked peers are cross-shared automatically.
- Only one party needs to send with --direct to establish the link.
- Use --close-link to sever the direct link for all members.

### `telec sessions tail`

Get recent messages from a session's transcript

**Usage:** `telec sessions tail <session_id> [--since <ts>] [--tools] [--thinking] [--full]`

**Flags:**

- `--session` (`-s`): Session ID
- `--since`: ISO8601 timestamp filter
- `--tools`: Include tool use entries
- `--thinking`: Include thinking blocks
- `--full`: Show all projected messages instead of the latest user turn

### `telec sessions run`

Run a slash command on a new agent session

**Usage:** `telec sessions run [--command <cmd>] [--path <path>] [--args <val>] [--agent <name>] [--mode <mode>] [--computer <host>] [--subfolder <dir>] [--additional-context <ctx>]`

**Flags:**

- `--command`: Slash command (e.g. /next-build)
- `--path`: Path to the project directory (optional; defaults to cwd)
- `--args`: Command arguments
- `--agent`: Agent: claude, gemini, codex
- `--mode`: Thinking mode: fast, med, slow
- `--computer` (`-c`): Target computer (optional; defaults to local)
- `--subfolder`: Subdirectory within the project
- `--additional-context`: Additional context for the worker, appended to startup message

**Notes:**

- Creates a fresh session and runs the slash command as the first agent message.
- Worker lifecycle commands: /next-build, /next-review-build, /next-finalize.
- --detach: do not use unless explicitly instructed. Sanctioned only for a personal-assistant dispatching an orchestrator to a project. --detach disables notifications — you will not learn when the child finishes, so omit it whenever your next step depends on the result.

### `telec sessions revive`

Revive session by TeleClaude session ID

**Usage:** `telec sessions revive <session_id>`

**Flags:**

- `--agent`: Treat session_id as native agent session ID for the given agent
- `--attach`: Attach to tmux session after revive
- `--computer`: Target computer

**Notes:**

- Restarts an ended session's agent with the full prior transcript, so the agent resumes with its original context intact.
- Without --agent, session_id is a TeleClaude session ID.
- With --agent, session_id is a native agent session ID resolved via the specified agent.

### `telec sessions end`

End (terminate) a session ('self' to end own session)

**Usage:** `telec sessions end <session_id> [--computer <host>]`

**Flags:**

- `--session` (`-s`): Session ID
- `--computer` (`-c`): Target computer (optional; defaults to local)

### `telec sessions unsubscribe`

Stop receiving notifications from a session

**Usage:** `telec sessions unsubscribe <session_id>`

### `telec sessions restart`

Restart an agent session ('self' to restart own session)

**Usage:** `telec sessions restart <session_id>`

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

Escalate to an admin via Discord

**Usage:** `telec sessions escalate [--customer <name>] [--reason <text>] [--summary <text>]`

**Flags:**

- `--customer`: Customer name
- `--reason`: Reason for escalation
- `--summary`: Context summary for the admin

## `telec computers`

Manage computer inventory

### `telec computers list`

List available computers (local + cached remote)

## `telec projects`

Manage project inventory and onboarding

### `telec projects list`

List projects on local and remote computers

**Usage:** `telec projects list [--computer <host>]`

**Flags:**

- `--computer` (`-c`): Filter to a specific computer

### `telec projects init`

Initialize project plumbing and sync artifacts

**Notes:**

- Sets up git hooks, syncs artifacts, and registers the project root.
- AI-driven analysis lives in `telec projects {onboard,analyze,assess}`.

### `telec projects onboard`

Full project bootstrap: init plumbing, then dispatch config assessment and doc-snippet analysis

**Notes:**

- Runs `telec projects init` synchronously, then dispatches `telec projects assess` and `telec projects analyze`.
- AI sessions run concurrently in tmux after dispatch — monitor via `telec sessions list` according to heartbeat policy.

### `telec projects analyze`

Generate project doc snippets via AI analysis

### `telec projects assess`

Assess project quality tool configuration against blessed templates

## `telec companies`

Manage company onboarding

### `telec companies onboard`

Scaffold a company under ~/.teleclaude/companies, or dispatch doc-snippet analysis

**Usage:** `telec companies onboard <name> [--slug <value>]`

**Flags:**

- `--slug`: Company slug (optional; derived from the name when omitted)

**Notes:**

- Scaffolds companies/<slug>/{inbox (git), docs/<taxonomy>, teleclaude.yml, meta.yaml, .env} synchronously.
- Re-running reprocesses only changed inbox material (SHA-tracked in meta.yaml).
- The analysis session runs concurrently in tmux after dispatch — monitor via `telec sessions list` according to heartbeat policy.

## `telec agents`

Manage agent dispatch status and availability

### `telec agents availability`

Get current availability for all agents

### `telec agents status`

Set dispatch status for a specific agent

**Usage:** `telec agents status <agent> [--status <val>] [--reason <text>] [--until <ts>] [--clear]`

**Flags:**

- `--status`: Status: available, unavailable, degraded
- `--reason`: Reason for status change
- `--until`: ISO8601 UTC expiry for unavailable or degraded
- `--clear`: Reset to available immediately

## `telec channels`

Manage internal Redis Stream channels

### `telec channels list`

List active channels

**Usage:** `telec channels list [--project <name>]`

**Flags:**

- `--project`: Filter by project name

### `telec channels publish`

Publish a message to a channel

**Usage:** `telec channels publish <channel> [--data <json>]`

**Flags:**

- `--data`: JSON payload to publish

## `telec operations`

Inspect durable long-running operations

### `telec operations get`

Fetch durable operation status by operation_id

**Usage:** `telec operations get <operation_id>`

## `telec version`

Print version, channel, and commit

## `telec sync`

Validate doc/snippet/artifact sources (blocks on findings) and apply your edits

**Usage:** `telec sync [--skip-deploy]`

**Flags:**

- `--skip-deploy`: Validate only; do not build or deploy (read-only gate)

**Notes:**

- Validation always blocks — there is no warn-and-pass mode.
- --skip-deploy is the read-only gate (pre-commit / CI / lint); it never mutates the host.

## `telec message`

Send a message to a person by slug

**Usage:** `telec message <slug> <text> [--file <path>] [--subject <text>] [--channel <name>]`

**Flags:**

- `--file`: Path to a single file to attach (Telegram, Discord, email only)
- `--subject`: Email subject line; ignored on channels without a subject concept
- `--channel`: Override channel: telegram, discord, whatsapp, email

**Notes:**

- Recipient-owned routing: defaults to the person's configured preferred_channel (email when unset).
- The message text is the file's caption on Telegram/Discord; on email it is the body and the file is an attachment.
- A file directed at a WhatsApp delivery is an actionable error — WhatsApp has no media-send capability here.
- Discover a person's slug via 'telec config people list'.

## `telec docs`

Query documentation snippets

**Notes:**

- Two-phase flow: use 'telec docs index' to discover IDs, then 'telec docs get <id...>' to fetch content.
- Omitting --areas and/or --domains returns all values for that dimension; pass a comma-separated subset to filter.
- Example phase 1: telec docs index --areas policy,procedure --domains software-development
- Example phase 2: telec docs get software-development/policy/testing project/spec/command-surface

### `telec docs index`

List snippet IDs and metadata (phase 1)

**Usage:** `telec docs index [--baseline-only] [--third-party] [--areas <principle|concept|policy|procedure|design|spec|adr>] [--domains <domain>] [--scope <global|project>] [--project <slug>] [--target <slug>]`

**Flags:**

- `--baseline-only` (`-b`): Show only baseline snippets
- `--third-party` (`-t`): Include third-party docs
- `--areas` (`-a`): Filter by taxonomy type (principle|concept|policy|procedure|design|spec|adr); omit for all
- `--domains` (`-d`): Filter by published domain; omit for all
- `--scope`: Filter to global or project snippets (global|project)
- `--project`: Filter to a registered project's snippets by slug
- `--target`: Filter to snippets delivered by slug

**Notes:**

- Pending snippets (those with delivered_by) append ` (delivered by: slug1,slug2)` at the end of the phase-1 line.

### `telec docs get`

Fetch full snippet content by ID (phase 2)

**Usage:** `telec docs get <id> [id...] [--scope <global|project>] [--project <slug>] [--target <slug>]`

**Flags:**

- `--scope`: Filter to global or project snippets (global|project)
- `--project`: Filter to a registered project's snippets by slug
- `--target`: Include the slug's planned sections and companion replacement body (default: strip all)

## `telec todo`

Manage work items

### `telec todo create`

Create a todo with substantive content

**Usage:** `telec todo create <slug> <content> --kind <feature|change|bug|task> [--after <deps>] [--schedule <value>] [--icebox] [--project-root <path>] [--group <parent-slug>] [--plan] [--human-involved]`

**Flags:**

- `--after`: Comma-separated dependency slugs
- `--schedule`: Task-only schedule: ISO-8601 instant or cron:<minute hour day month weekday> (0/7=Sunday)
- `--kind`: The work-unit's entry point into the lifecycle: feature|change|bug|task. Always set it when creating via the CLI — agents classify their own todos; omitting it is the TUI dump path only. --kind task is side-effect-only and never touches the repo (software-development/spec/todo-kind-task) — code work is change/feature/bug.
- `--icebox`: Create future todo parked in the icebox; does not auto-spawn
- `--project-root` (`-p`): Target an explicit project root instead of the invocation cwd
- `--group`: Attach the new todo as a child of <parent-slug>, making the parent a holder
- `--plan`: For --kind change, content seeds implementation-plan as a draft basis; for --kind task, content is the pre-authorized task-plan.
- `--human-involved`: Declares a human was in the conversation that produced this filing — saw it, asked for it, or shaped it. Agent-caller only; a human door (TUI/CLI login/web) derives this automatically and ignores the flag. Omitting it for an agent filing records false — a forgotten flag lands the todo in the started-without-me audit bucket, never a hidden autonomous filing.

**Notes:**

- Creates the todo entry, canonical state, and stores content as the input artifact.
- Include the observed trigger — what happened, what was asked, or what shaped this filing — verbatim in <content> whenever a human conversation produced it, and pass --human-involved. The gap this closes is the reporting invitation, not the schema: a filing whose trigger context lives nowhere is unauditable later.
- Content IS the input artifact — the author's INTENT (WHAT/WHY in operator language, affected surfaces, acceptance shape, brownfield grounding), never a work order. Do NOT prescribe HOW (file paths, mechanisms, edit/step instructions) or doc-layer deliverables — in particular never instruct authoring an ADR or which snippets to write. Per software-development/policy/preparation-artifact-quality (Input artifact quality): HOW is the prepare phase's hypothesis to verify, doc routing is intake's, and an ADR is governed by general/policy/adr-discipline (default none, never by process step). Any HOW or doc instruction left in content is an unverified hypothesis, not a directive. (--plan is the deliberate exception: its content is a complete implementation-plan, not an input.)
- Use --icebox to place unfleshed future ideas directly into the icebox, while --hold is the human requested create-time parking flag for todos needing fleshing out progressively. --group <parent-slug> creates a complete grouped child in one call and makes the parent a structural holder via the existing derivation; the first grouped child strips the parent's todo_state while preserving all its artifacts as frozen evidence, and is refused once the parent's lifecycle_phase has reached prepared or the work lane, so build, review, and finalize state is never shredded.
- ALWAYS pass --kind — an agent that authored a todo's scope owns its classification. Omitting --kind (kind-less) is reserved for the TUI's direct-primitive dump path, where human intent is still unknown and /analyze-todo-input classifies it later. It is NOT a CLI shortcut to skip classifying work you understand.
- --plan is valid with --kind change or --kind task.
- Do NOT create a todo for work you can finish yourself in under ~5 minutes — do it inline and stay on it. Todos are for substantial, dispatchable work, never a way to defer a small fix you were asked to make now.
- Process changes are decided by humans (software-development/policy/process-change-authority): when the intent implies a behavioral delta to a process-layer contract (lifecycle state machines, gate composition, review lanes, lifecycle procedures, todo/state semantics), file it only on a human decision from the live conversation. Holding no such decision, do NOT file the todo: escalate the proposal to the human and go idle. The prepare orchestrator refuses process-change intents it cannot trace to a human decision.

### `telec todo list`

List todo entries (source of truth for todo status)

**Usage:** `telec todo list [--include-icebox] [--icebox-only] [--include-delivered] [--delivered-only] [--include-removed] [--removed-only] [--since <when>] [--json]`

**Flags:**

- `--include-icebox` (`-i`): Include icebox items
- `--icebox-only` (`-o`): Show only icebox items
- `--include-delivered` (`-d`): Include delivered items
- `--delivered-only`: Show only delivered items
- `--include-removed` (`-r`): Include soft-removed items
- `--removed-only`: Show only soft-removed items
- `--since`: Only delivered entries at/after this point: duration (7d, 72h, 2w) or ISO date (2026-05-01). Implies --include-delivered.
- `--json`: Output as a sectioned JSON object (active/delivered/icebox/removed trees)

**Notes:**

- Output is sectioned into active/delivered/icebox/removed dependency trees.
- CONTRACT CHANGE: --json now emits a nested object keyed by section (active/delivered/icebox/removed), each a tree with `children`; previously a flat list. Empty todo list emits `{}`. Text output no longer appends a [status] suffix.
- --include-delivered returns the full delivery history; scope it with --since.
- --since accepts a relative duration (7d, 72h, 2w) or an ISO date/timestamp.
- --since alone implies --include-delivered; combine with --delivered-only to exclude active items.
- --include-removed interleaves soft-removed entries; each removed row renders with its todo id and removed_at age.

### `telec todo design`

Run the creative state machine

**Usage:** `telec todo design [<slug>]`

### `telec todo remove`

Soft-remove a todo: the durable record (todo entry + state + all artifacts and version history) is retained for a fixed grace window; the working resources (worktree + branch + workspace) are released immediately. After the window elapses, background maintenance hard-purges the row by id. Reactivation is row-id-addressed (see the downstream recovery surface) and fail-closed on a live same-slug twin.

**Usage:** `telec todo remove <slug>`

### `telec todo freeze`

Move todo to icebox

**Usage:** `telec todo freeze <slug>`

### `telec todo unfreeze`

Promote todo from icebox

**Usage:** `telec todo unfreeze <slug>`

### `telec todo deliver`

Move todo to delivered

**Usage:** `telec todo deliver <slug> [--commit <hash>]`

**Flags:**

- `--commit`: The commit that delivered the slug. The integrator always supplies its own pushed commit and withholds delivery until that commit is confirmed on origin/main. Never inferred from HEAD, which is routinely an unrelated commit; omitting it therefore records a delivery with no provenance.

### `telec todo update`

Update a todo slug, dependencies, or kind

**Usage:** `telec todo update <slug> [--slug <new>] [--after <dep>]... [--schedule <value>] [--kind <feature|change|bug|task>] [--hold] [--release] [--unclaim] [--force]`

**Flags:**

- `--slug`: New todo slug; delegates to the durable rename engine
- `--after`: Dependency slug(s); replaces the full set. CSV accepted: --after parent-a,parent-b. Repeated flags accepted for compatibility: --after parent-a --after parent-b. Use --after "" to clear all dependencies.
- `--schedule`: Task-only schedule; pass an empty value to clear (cron weekday 0/7=Sunday)
- `--kind`: New todo kind: feature|change|bug|task
- `--hold`: Set the per-todo automatic dispatch brake
- `--release`: Release the per-todo automatic dispatch brake
- `--unclaim`: Release the caller-owned runner claim without ending the session
- `--force`: Allow permanent orphan-artifact handling for kind migrations

**Notes:**

- Mutates slug, deps, kind, or hold; --after replaces the full dependency set.
- Kind and slug changes are refused after build starts; --after remains allowed.
- --hold and --release are mutually exclusive and compose with dependency updates.
- --unclaim clears the caller-owned runner claim; --release only clears the dispatch brake.
- --force only applies to kind orphan handling.
- Combining --slug with other legs is staged, not a single atomic patch.

### `telec todo prepare`

Run the Phase A (prepare) state machine

**Usage:** `telec todo prepare <slug>`

### `telec todo work`

Run the Phase B (work) state machine

**Usage:** `telec todo work [<slug>]`

### `telec todo integrate`

Run the Phase C (integrate) state machine

**Usage:** `telec todo integrate [<slug>]`

### `telec todo artifacts`

Manage todo artifacts in the database

#### `telec todo artifacts list`

List artifacts for a todo

**Usage:** `telec todo artifacts list <slug>`

#### `telec todo artifacts read`

Read a todo artifact

**Usage:** `telec todo artifacts read <slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings>`

#### `telec todo artifacts write`

Write a todo artifact

**Usage:** `telec todo artifacts write <slug> <name: input|prd|architecture|diagnosis|investigation|implementation-plan|task-plan|quality-checklist|design-spec|deferrals|log|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> <content>`

**Notes:**

- Legacy bug artifacts are read-only; write bug todo content to input.

#### `telec todo artifacts diff`

Show a unified diff between two artifact versions

**Usage:** `telec todo artifacts diff <slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings> <old-digest> <new-digest>`

**Notes:**

- Looks up both versions by digest in the artifact version history and prints a unified diff between them.
- Used by the prepare loop to show reviewers what changed since the last approved digest.

#### `telec todo artifacts remove`

Remove a todo artifact and its version history

**Usage:** `telec todo artifacts remove <slug> <name: input|prd|requirements|architecture|diagnosis|investigation|implementation-plan|task-plan|bug|quality-checklist|design-spec|deferrals|log|requirements-review-findings|prd-review-findings|architecture-review-findings|plan-review-findings|review-findings>`

**Notes:**

- Refuses input because it is the seed artifact for a todo.
- Missing artifacts are treated as a successful no-op.

### `telec todo show`

Show diagnostic state payload for a todo; artifact bodies are omitted by default

**Usage:** `telec todo show <slug> [--include-removed] [--include-artifact-content]`

**Flags:**

- `--include-removed`: Also search soft-removed entries
- `--include-artifact-content`: Include artifact body content under artifact_content in the payload

### `telec todo reactivate`

Restore a soft-removed todo

**Usage:** `telec todo reactivate <slug>`

**Notes:**

- Resolves the slug against soft-removed rows and restores the uniquely matching entry.
- On success: status reverts to prev_status and outgoing dependencies are replayed.

### `telec todo stamp`

Stamp a verdict or readiness marker into todo state

**Usage:** `telec todo stamp <slug> [--verdict <v> --phase <p>] [--prd-approved] [--task-approved] [--architecture-skipped <reason>] [--drift-reviewed <artifact> <verdict> <reason>] [--kind-assign <feature|change|bug|task> [<content>]] [--build-complete] [--finalize-ready] [--kickback --reason <reason>] [--task-outcome <success|error> [--reason <text>]] [--diagnosis-settled] [--diagnosis-unresolved --reason <reason>]`

**Flags:**

- `--verdict`: approve | changes_requested | needs_work | needs_decision
- `--phase`: Review phase the verdict belongs to (prd_review, architecture_review, plan_review, build_review)
- `--prd-approved`: Mark PRD as approved by the human
- `--task-approved`: Authorize the current task-plan for a task
- `--architecture-skipped`: Skip architecture phase with a reason
- `--drift-reviewed`: Record drift review: <artifact> <substantive|cosmetic> <reason>
- `--kind-assign`: Assign kind and enter that kind's lifecycle entry phase: <feature|change|bug|task> [content]. task is side-effect-only and never touches the repo (software-development/spec/todo-kind-task).
- `--build-complete`: Record the worker's build-complete claim; gates run on the next telec todo work dispatch
- `--finalize-ready`: Mark worktree as ready for finalize handoff
- `--kickback`: Work-orchestrator-only: send an unbuildable todo back to plan drafting
- `--reason`: Reason recorded to input (required with --kickback / --task-outcome error / --diagnosis-unresolved)
- `--task-outcome`: Durable task firing outcome: success delivers/clears, error holds with --reason
- `--diagnosis-settled`: Bug lane: record the diagnosis artifact's current digest as the settled cause; a later revision invalidates the stamp
- `--diagnosis-unresolved`: Bug lane: hold the todo when the dispatched peer's diagnosis could not be settled; requires --reason

## `telec bugs`

Bug reporting and tracking

### `telec bugs report`

Interrogate the pre-filing decisions before scaffolding a bug; a completed filing enters the bug lane and the lifecycle router dispatches /next-prepare

**Usage:** `telec bugs report <description> [--slug <slug>] [--body <text>] [--project <name>] [--human-involved]`

**Flags:**

- `--slug`: Custom slug (default: auto-generated)
- `--body`: Detailed description body for bug.md
- `--project`: Project that owns the defective code (from trusted_dirs). Defaults to the invoking cwd — where the symptom was OBSERVED, which is often not where the code lives. Set it whenever the two differ.
- `--human-involved`: Declares a human was in the conversation that produced this filing — saw it, asked for it, or shaped it. Agent-caller only; a human door (TUI/CLI login/web) derives this automatically and ignores the flag. Omitting it for an agent filing records false — a forgotten flag lands the todo in the started-without-me audit bucket, never a hidden autonomous filing.

**Notes:**

- An invocation carrying only the report payload does not file: it presents the required pre-filing decisions (fix-directly, duplication, ordering, validity and ownership) and only that output names how to complete the filing.
- File against the project that OWNS the defective code, not the one you happen to be standing in. Platform behavior misbehaving inside a side project is a platform bug: pass --project so the orchestrator that picks it up can actually deliver the fix. A bug filed where the code does not live cannot be fixed there and gets re-filed later, carrying stale conclusions with it. When you cannot tell which project owns it, ask.
- The filing surface interrogates for duplication up front (todo list, in-flight bug lanes, suppressions); diagnose remains the deeper same-defect dedup that can still retire a twin the up-front check missed.
- Your reported todo may therefore still be removed as a duplicate at diagnose — that is expected dedup, not a dropped report. The surviving todo carries the fix; do not re-report the same bug.
- Report the OBSERVED wrong behavior, never a missing capability or a solution ('X has no way to do Y' is a fix wearing a symptom's clothes). A bug fix stays within the existing process contract (software-development/policy/process-change-authority): when the defect seems to demand a behavioral delta to a process-layer contract (lifecycle state machines, gate composition, review lanes, lifecycle procedures), do NOT file it as a bug — escalate the process proposal to the human instead.
- Require the observed symptom plus its trigger context verbatim in the description or --body: what happened, what was expected, and what preceded it. A report with no trigger context is unauditable later — this is the reporting invitation the schema alone cannot supply.

### `telec bugs list`

List in-flight bug fixes with status

### `telec bugs suppress`

Register a known-issue suppression so the log bug hunter stops re-filing a triaged signal

**Usage:** `telec bugs suppress "<pattern>" --reason <r> [--match substring|regex] [--disposition expected|wontfix] [--project <name>] [--source-bug <slug>] [--expires <when>]`

**Flags:**

- `--reason`: Human-readable justification (required)
- `--match`: Match mode: substring (default, literal) or regex
- `--disposition`: expected or wontfix (default: wontfix); record-only
- `--project`: Project name (from trusted_dirs)
- `--source-bug`: Slug of the originating bug whose triage produced this suppression
- `--expires`: Optional ISO-8601 expiry after which the suppression lapses

**Notes:**

- The ledger is the log bug hunter's allowlist: a matched candidate error line is treated as already triaged and does not dispatch a session.
- Matching is literal (substring) or a compiled regex; a regex pattern is validated here and rejected if it does not compile.
- Author the pattern to target the invariant signal (a stable reason token), never a volatile value like a millisecond figure.

### `telec bugs suppressions`

List the active known-issue suppressions for a project

**Usage:** `telec bugs suppressions [--project <name>]`

**Flags:**

- `--project`: Project name (from trusted_dirs)

### `telec bugs unsuppress`

Remove a known-issue suppression by id so its signal is eligible for filing again

**Usage:** `telec bugs unsuppress <id> [--project <name>]`

**Flags:**

- `--project`: Project name (from trusted_dirs)

## `telec content`

Manage content pipeline

### `telec content dump`

Fire-and-forget content dump to publications inbox

**Usage:** `telec content dump <description-or-text> [--slug <slug>] [--tags <tags>] [--author <name>]`

**Flags:**

- `--slug`: Custom slug (default: auto-generated from text)
- `--tags`: Comma-separated tags
- `--author`: Author identity (default: terminal auth)

**Notes:**

- Creates publications/inbox/YYYYMMDD-<slug>/ with content.md and meta.yaml.
- Author defaults to terminal auth identity (telec auth whoami) or 'unknown'.
- Emits a content.dumped notification event if the notification service is available.
- Slug collision is handled automatically by appending a counter suffix.

## `telec jobs`

Recurring job commands

### `telec jobs report`

Write a structured recurring job result record

**Usage:** `telec jobs report <job_name> --success <true|false> --message <text> [--items-processed <n>] [--error <text> ...]`

**Flags:**

- `--success`: Whether the job completed successfully
- `--message`: Human-readable outcome summary
- `--items-processed`: Count of processed items (default: 0)
- `--error`: Error detail; repeat for multiple errors

**Notes:**

- Validates job_name against configured jobs and writes JSON under ~/.teleclaude/jobs/{job}/runs/.
- This command writes locally and does not call the daemon.

## `telec events`

Event catalog and platform commands

### `telec events list`

List event schemas: type, level, domain, visibility, description, actionable

**Usage:** `telec events list [--domain <name>]`

**Flags:**

- `--domain`: Filter by domain

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

Show terminal login identity for this TTY

### `telec auth logout`

Clear terminal login identity for this TTY

## `telec config`

Manage configuration

### `telec config wizard`

Open the interactive configuration wizard

### `telec config get`

Get config values

**Usage:** `telec config get [paths...]`

### `telec config patch`

Patch config values

**Usage:** `telec config patch [--yaml '...']`

**Flags:**

- `--yaml` (`-y`): Inline YAML patch

### `telec config validate`

Full validation

### `telec config people`

Manage people

**Notes:**

- To edit people's subscriptions, modify the person config: ~/.teleclaude/people/{name}/teleclaude.yml
- --expertise JSON shape: {"<domain>": "<level>", "<domain>": {"<sub-area>": "<level>"}}. Levels: novice, intermediate, advanced, expert. Example: '{"python": "expert", "typescript": {"backend": "advanced", "frontend": "intermediate"}}'

#### `telec config people list`

List people

#### `telec config people add`

Add a person

**Usage:** `telec config people add <name> --email <email> --role <role> [--expertise '<json>'] [--telegram-user <user>] [--telegram-id <id>]`

#### `telec config people edit`

Edit a person

**Usage:** `telec config people edit <name> [--email <email>] [--role <role>] [--expertise '<json>'] [--telegram-user <user>] [--telegram-id <id>]`

#### `telec config people remove`

Remove a person

**Usage:** `telec config people remove <name>`

#### `telec config people invite`

Generate invite links for a person

**Usage:** `telec config people invite <name> [--json]`

**Flags:**

- `--json`: Emit machine-readable JSON output

### `telec config env`

Manage environment variables

#### `telec config env list`

List environment variables

#### `telec config env set`

Set environment variables

### `telec config notify`

Toggle notification settings

### `telec config tts`

Manage TTS dependency provisioning

#### `telec config tts deprovision`

Disable TTS and remove the TTS-exclusive optional dependencies

**Usage:** `telec config tts deprovision [--yes]`

**Flags:**

- `--yes`: Confirm the destructive dependency removal

**Notes:**

- Disables TTS, removes the TTS-exclusive deps (elevenlabs, the mlx text pipeline), and leaves deps shared with STT/summarization installed.
- Bare invocation prints this guard and makes no daemon call.
- Re-enabling TTS afterward lazily re-provisions the removed deps.

## `telec history`

Search and view agent session history

### `telec history list`

List session summaries from mirrors

**Usage:** `telec history list [--identity <email>] [--project <name>] [--limit <n>]`

**Flags:**

- `--identity`: Filter by human identity (email or key)
- `--project`: Filter by project name
- `--limit`: Max results (default: 20)

### `telec history search`

Search agent session transcripts

**Usage:** `telec history search [terms...] [--agent <name>] [--computer <host>] [--limit <n>] [--include-workers]`

**Flags:**

- `--agent` (`-a`): Agent name(s) or 'all' (default: all)
- `--computer` (`-c`): Query one or more remote computers via daemon API
- `--limit` (`-l`): Max results to show (default: 20)
- `--include-workers`: Also search dispatched-worker sessions (reviewers, builders)

### `telec history show`

Show full transcript for a session

**Usage:** `telec history show <session-id> [--agent <name>] [--computer <host>] [--thinking] [--raw] [--tail <n>]`

**Flags:**

- `--agent` (`-a`): Agent name or 'all' (default: all)
- `--computer` (`-c`): Fetch from a remote computer
- `--thinking`: Include thinking blocks
- `--raw`: Show raw transcript instead of mirror text
- `--tail`: Limit output to last N chars (0=unlimited)

## `telec memories`

Read or remove durable personal-preference observations about the human. Memories capture meta-level things about who the human is — their relational stance, values, communication style, vision — never coding norms, architectural decisions, or operational gotchas (those live in policies, principles, and addenda). Memories are written exclusively by the session memory extraction agent (the memory scraper, invoked via /extract-memory); other agents must never create them.

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

- lint, test, format, install, and blueprint require the code capability.
- changed, add, and commit remain available when either code or docs is subscribed.

### `telec code blueprint`

Query the codebase Blueprint (structural blast-radius)

#### `telec code blueprint affected`

Print the blast-radius dependents of changed files

**Usage:** `telec code blueprint affected <changed-files>`

**Notes:**

- Maps each changed file to its symbols, runs a transitive reverse dependency traversal over the Blueprint, and prints the union of dependents with file:line.
- When the Blueprint is missing or stale (manifest baseline != current main), prints a fallback notice and exits 0 — fall back to manual exploration; blast-radius is never silently skipped.

### `telec code lint`

Run native make lint plus TeleClaude guardrails

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

### `telec code install`

Run native make install

### `telec code changed`

List workspace-scoped changed files

### `telec code add`

Stage files for the next commit (NEW, unmerged, or partial-staged tracked)

**Usage:** `telec code add <path> [<path> ...]`

**Notes:**

- Sealed equivalent of 'git add' for the three cases git's data model genuinely requires staging:
- (1) NEW (untracked) files — must enter the index before commit pathspec can match.
- (2) Unmerged-index files (post-conflict) — must be marked resolved before commit.
- (3) Partial-staged tracked files (staged hunks + later working-tree delta) — must be fully (re)staged so the pathspec commit does not silently sweep in unstaged hunks. The partial-staging guard in `telec code commit` directs agents here for recovery.
- Modified-tracked files that are NOT partial-staged don't need staging — pathspec commits them straight from the working tree.
- NEW files in scope are NOT auto-committed; this is the explicit declaration step. Without it, untracked files stay untracked (safety net for temp/scratch artifacts the agent may have created incidentally).
- Alternative one-shot form: telec code commit --approved '<msg>' --include <path>.

### `telec code commit`

Commit workspace-scoped changes via a pathspec-scoped commit (sealed; no git forwarding)

**Usage:** `telec code commit "<message>" [--approved] [--human-involved] [--include <path> ...] [--only <path> ...]`

**Flags:**

- `--approved`: Agent-owned sealed commit gate. Required to commit; bare main invocation prints commit-first and review-routing guidance.
- `--include`: Declare files outside workspace scope to add to this commit (space-separated paths).
- `--only`: Commit exactly these paths instead of the resolved workspace scope; intended for splitting a dirty scope into multiple commits.
- `--human-involved`: Declare that a human was genuinely present in this session. Carried as Human-Involved: true in the commit footer; absent when not passed (defaults to false). Never derived from the todo record.

**Notes:**

- Accepts only: one quoted message, --approved, --human-involved, --include <path> ..., and --only <path> ... .
- Modified-tracked files in scope are auto-committed via pathspec straight from the working tree — no staging needed.
- NEW (untracked) files in scope are NOT auto-committed by default; declare them via `telec code add`, `--include`, or `--only` (safety net against incidental temp/scratch artifacts).
- --only commits exactly the declared paths and is mutually exclusive with --include.
- Unmerged-index files in pathspec are staged internally for the integrator conflict path.
- Without --approved on main: prints commit-first and review-routing guidance and exits.
- Pathspec = workspace scope plus --include paths, or exactly --only paths. Anything else in the index (foreign stage) is left untouched — there is no env-var bypass.
- The commit author is stamped as the resolved agent's bot identity (git --author); the message gains the branding line, Session:, and Human-Involved: — no Co-Authored-By trailer is ever added.

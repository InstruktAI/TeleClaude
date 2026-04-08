# TeleClaude CLI Surface

## `telec sessions`

Manage agent sessions

### `telec sessions list`

List sessions (default: spawned by current, --all for all)

**Flags:**

- `--all`: Show all sessions
- `--closed`: Include closed sessions
- `--job`: Filter by session_metadata.job value

### `telec sessions start`

Start a new agent session

**Flags:**

- `--computer`: Target computer (optional; defaults to local)
- `--project`: Project directory path (optional; defaults to cwd)
- `--agent`: Agent: claude, gemini, codex
- `--mode`: Thinking mode: fast, med, slow
- `--message`: Initial message to send
- `--title`: Session title
- `--direct`: Conversation mode: create direct link with caller and bypass listeners
- `--detach`: Fire-and-forget: inherit context but skip listener registration

**Notes:**

- Use --direct for peer conversation mode when you want shared linked output instead of worker supervision notifications.
- Use --detach for fire-and-forget dispatch: child inherits identity but caller receives no notifications.

### `telec sessions send`

Send a message to a running session

**Usage:** `telec sessions send <session_id> [<message>]`

**Flags:**

- `--session` (`-s`): Session ID (compatibility form)
- `--message` (`-m`): Message text (compatibility form)
- `--direct`: Conversation mode: create shared direct link
- `--close-link`: Close direct link with target session (alias: --close_link)

**Notes:**

- Positional form is canonical: telec sessions send <session_id> <message>.
- One-time ignition: sending once with --direct establishes the link.
- After link creation, turn-complete outputs from linked peers are cross-shared automatically.
- Only one party needs to send with --direct to establish the link.
- Use --close-link to sever the direct link for all members.
- Compatibility flags (--session/--message) are accepted for scripts and older clients.

### `telec sessions tail`

Get recent messages from a session's transcript

**Usage:** `telec sessions tail <session_id>`

**Flags:**

- `--session` (`-s`): Session ID
- `--since`: ISO8601 timestamp filter
- `--tools`: Include tool use entries
- `--thinking`: Include thinking blocks

### `telec sessions run`

Run a slash command on a new agent session

**Flags:**

- `--command`: Slash command (e.g. /next-build)
- `--project`: Project directory path (optional; defaults to cwd)
- `--args`: Command arguments
- `--agent`: Agent: claude, gemini, codex
- `--mode`: Thinking mode: fast, med, slow
- `--computer`: Target computer (optional; defaults to local)
- `--subfolder`: Subdirectory within the project
- `--detach`: Fire-and-forget: inherit context but skip listener registration
- `--additional-context`: Additional context for the worker, appended to startup message

**Notes:**

- Creates a fresh session and runs the slash command as the first agent message.
- Worker lifecycle commands: /next-build, /next-review-build, /next-fix-review, /next-finalize.
- Example: telec sessions run --command /next-build --args my-slug
- Use --detach for fire-and-forget dispatch: child inherits identity but caller receives no notifications.

### `telec sessions revive`

Revive session by TeleClaude session ID

**Usage:** `telec sessions revive <session_id>`

**Flags:**

- `--agent`: Treat session_id as native agent session ID for the given agent
- `--attach`: Attach to tmux session after revive

**Notes:**

- Restarts an ended session's agent with the full prior transcript, so the agent resumes with its original context intact.
- Without --agent, session_id is a TeleClaude session ID.
- With --agent, session_id is a native agent session ID resolved via the specified agent.

### `telec sessions end`

End (terminate) a session

**Usage:** `telec sessions end <session_id>`

**Flags:**

- `--session` (`-s`): Session ID
- `--computer`: Target computer (optional; defaults to local)

### `telec sessions unsubscribe`

Stop receiving notifications from a session

**Usage:** `telec sessions unsubscribe <session_id>`

### `telec sessions restart`

Restart an agent session ('self' to restart own session)

**Usage:** `telec sessions restart <session_id>`

### `telec sessions result`

Send a formatted result to the session's user

**Usage:** `telec sessions result <content>`

**Flags:**

- `--format`: Output format: markdown, html

### `telec sessions file`

Send a file to the session's user

**Flags:**

- `--path`: File path on the daemon host
- `--filename`: Display filename
- `--caption`: Optional caption

### `telec sessions widget`

Render a rich widget to the session's user

**Flags:**

- `--data`: Widget expression as JSON

### `telec sessions escalate`

Escalate to an admin via Discord

**Flags:**

- `--customer`: Customer name
- `--reason`: Reason for escalation
- `--summary`: Context summary for the admin

## `telec computers`

Manage computer inventory

### `telec computers list`

List available computers (local + cached remote)

## `telec projects`

Manage project inventory

### `telec projects list`

List projects on local and remote computers

**Flags:**

- `--computer`: Filter to a specific computer

## `telec agents`

Manage agent dispatch status and availability

### `telec agents availability`

Get current availability for all agents

### `telec agents status`

Set dispatch status for a specific agent

**Usage:** `telec agents status <agent>`

**Flags:**

- `--status`: Status: available, unavailable, degraded
- `--reason`: Reason for status change
- `--until`: ISO8601 UTC expiry for unavailable
- `--clear`: Reset to available immediately

## `telec channels`

Manage internal Redis Stream channels

### `telec channels list`

List active channels

**Flags:**

- `--project`: Filter by project name

### `telec channels publish`

Publish a message to a channel

**Usage:** `telec channels publish <channel>`

**Flags:**

- `--data`: JSON payload to publish

## `telec operations`

Inspect durable long-running operations

### `telec operations get`

Fetch durable operation status by operation_id

**Usage:** `telec operations get <operation_id>`

## `telec init`

Initialize docs sync, auto-rebuild watcher, and optional project enrichment

**Notes:**

- Sets up git hooks, syncs artifacts, installs file watchers.
- Optionally runs AI-driven project analysis to generate doc snippets.
- First init offers enrichment; re-init offers refresh of existing analysis.
- Prompts for release-channel enrollment (alpha/beta/stable).

## `telec version`

Print version, channel, and commit

## `telec sync`

Validate, build indexes, and deploy artifacts

**Flags:**

- `--warn-only`: Warn but don't fail
- `--validate-only`: Validate without building

## `telec docs`

Query documentation snippets

**Notes:**

- Two-phase flow: use 'telec docs index' to discover IDs, then 'telec docs get <id...>' to fetch content.
- Example phase 1: telec docs index --areas policy,procedure --domains software-development
- Example phase 2: telec docs get software-development/policy/testing project/spec/command-surface

### `telec docs index`

List snippet IDs and metadata (phase 1)

**Flags:**

- `--baseline-only` (`-b`): Show only baseline snippets
- `--third-party` (`-t`): Include third-party docs
- `--areas` (`-a`): Filter by taxonomy type
- `--domains` (`-d`): Filter by domain

### `telec docs get`

Fetch full snippet content by ID (phase 2)

**Usage:** `telec docs get <id> [id...]`

## `telec todo`

Manage work items

### `telec todo co-create`

Run the creative state machine

**Usage:** `telec todo co-create [<slug>]`

### `telec todo remove`

Remove a todo and its roadmap entry

**Usage:** `telec todo remove <slug>`

### `telec todo validate`

Validate todo files and state.yaml schema

**Usage:** `telec todo validate [slug]`

**Notes:**

- If slug is omitted, all active todos are checked.

### `telec todo prepare`

Run the Phase A (prepare) state machine

**Usage:** `telec todo prepare [<slug>]`

**Flags:**

- `--invalidate-check`: Scan all active todos and invalidate stale preparations
- `--changed-paths`: Comma-separated file paths for invalidation check

### `telec todo work`

Run the Phase B (work) state machine

**Usage:** `telec todo work [<slug>]`

### `telec todo integrate`

Run the Phase C (integrate) state machine

**Usage:** `telec todo integrate [<slug>]`

### `telec todo mark-phase`

Mark a work or prepare phase in state.yaml

**Usage:** `telec todo mark-phase <slug>`

**Flags:**

- `--phase`: Phase: build, review, prepare, requirements_review, plan_review
- `--status`: Work: pending/started/complete/approved/changes_requested; Prepare verdict: approve/needs_work/needs_decision; Prepare lifecycle: prepared, gate, etc.

### `telec todo mark-ready`

Sets build: pending. Fast-track a todo to work-ready state, bypassing prepare lifecycle

**Usage:** `telec todo mark-ready <slug> [<slug> ...]`

**Notes:**

- Promotes input.md → requirements.md, generates implementation-plan.md and quality-checklist.md.
- Sets DOR 8, prepare_phase=prepared, grounding=valid, reviews=approved.
- Use for straightforward work items that don't need the full prepare ceremony.
- Accepts multiple slugs to fast-track a batch in one call.

### `telec todo mark-finalize-ready`

Record finalize readiness in worktree state.yaml

**Usage:** `telec todo mark-finalize-ready <slug>`

**Flags:**

- `--worker-session-id`: Finalizer worker session that reported FINALIZE_READY

### `telec todo state`

Inspect state, fire transition, or rewind

**Usage:** `telec todo state <slug> [<transition>]`

**Flags:**

- `--rewind`: Rewind to previous state

### `telec todo set-deps`

Set dependencies for a work item in the roadmap

**Usage:** `telec todo set-deps <slug>`

**Flags:**

- `--after`: Dependency slug (repeatable)

### `telec todo verify-artifacts`

Mechanically verify artifacts for a phase (build or review)

**Usage:** `telec todo verify-artifacts <slug>`

**Flags:**

- `--phase`: Phase: build or review

**Notes:**

- Exits 0 on pass, 1 on failure.
- Checks artifact presence and consistency — does not run tests or demo.
- Integrated into next_work() before dispatching review.

### `telec todo dump`

Fire-and-forget brain dump with notification trigger

**Usage:** `telec todo dump <slug> <content>`

**Flags:**

- `--after`: Comma-separated dependency slugs

**Notes:**

- Emits todo.dumped notification for autonomous processing.

### `telec todo split`

Split a todo into child items (container transition)

**Usage:** `telec todo split <slug>`

**Flags:**

- `--into`: Child slug (repeatable, at least one required)

**Notes:**

- Scaffolds children, cleans parent artifacts, sets container state.
- Children inherit parent's approved prepare phase: if requirements were approved, children start at plan_drafting; if the plan was approved, children start at prepared (ready for build).

### `telec todo from-main`

Create a reviewed todo from uncommitted changes on main

**Usage:** `telec todo from-main --slug <name> [--description <desc>]`

**Flags:**

- `--slug`: Meaningful slug name for the todo
- `--description`: Optional description of the changes

**Notes:**

- Transfers uncommitted changes from main into a worktree for review.
- File scoping is automatic: only files touched by the current session are transferred.
- Creates todo scaffold, sets state to build:complete, ready for review.
- After running, follow the printed instructions to commit and dispatch.

## `telec roadmap`

Manage the work item roadmap

### `telec roadmap list`

List roadmap entries (source of truth for todo status)

**Flags:**

- `--include-icebox` (`-i`): Include icebox items
- `--icebox-only` (`-o`): Show only icebox items
- `--include-delivered` (`-d`): Include delivered items
- `--delivered-only`: Show only delivered items
- `--json`: Output as JSON

### `telec roadmap add`

Add entry to the roadmap

**Usage:** `telec roadmap add <slug>`

**Flags:**

- `--group`: Visual grouping label
- `--after`: Comma-separated dependency slugs
- `--before`: Insert before this slug (default: append)
- `--description`: Summary description

### `telec roadmap remove`

Remove entry from the roadmap

**Usage:** `telec roadmap remove <slug>`

### `telec roadmap move`

Reorder an entry in the roadmap

**Usage:** `telec roadmap move <slug>`

**Flags:**

- `--before`: Move before this slug
- `--after`: Move after this slug

### `telec roadmap deps`

Set dependencies for an entry

**Usage:** `telec roadmap deps <slug>`

**Flags:**

- `--after`: Comma-separated dependency slugs

### `telec roadmap freeze`

Move entry to icebox

**Usage:** `telec roadmap freeze <slug>`

### `telec roadmap unfreeze`

Promote entry from icebox to roadmap

**Usage:** `telec roadmap unfreeze <slug>`

### `telec roadmap migrate-icebox`

One-time migration: move icebox folders into todos/_icebox/

### `telec roadmap deliver`

Move entry to delivered

**Usage:** `telec roadmap deliver <slug>`

**Flags:**

- `--commit`: Commit hash (auto-detects HEAD if omitted)

## `telec bugs`

Bug reporting and tracking

### `telec bugs report`

Report a bug, scaffold, and dispatch fix

**Usage:** `telec bugs report <description>`

**Flags:**

- `--slug`: Custom slug (default: auto-generated)
- `--body`: Detailed description body for bug.md
- `--project`: Project name (from trusted_dirs)

### `telec bugs create`

Scaffold bug files for a slug

**Usage:** `telec bugs create <slug>`

**Flags:**

- `--project`: Project name (from trusted_dirs)

### `telec bugs list`

List in-flight bug fixes with status

## `telec content`

Manage content pipeline

### `telec content dump`

Fire-and-forget content dump to publications inbox

**Usage:** `telec content dump <description-or-text>`

**Flags:**

- `--slug`: Custom slug (default: auto-generated from text)
- `--tags`: Comma-separated tags
- `--author`: Author identity (default: terminal auth)

**Notes:**

- Creates publications/inbox/YYYYMMDD-<slug>/ with content.md and meta.yaml.
- Author defaults to terminal auth identity (telec auth whoami) or 'unknown'.
- Emits a content.dumped notification event if the notification service is available.
- Slug collision is handled automatically by appending a counter suffix.

## `telec events`

Event catalog and platform commands

### `telec events list`

List event schemas: type, level, domain, visibility, description, actionable

**Flags:**

- `--domain`: Filter by domain

## `telec signals`

Signal pipeline status and diagnostics

### `telec signals status`

Show signal pipeline counts and last ingest time

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

### `telec config validate`

Full validation

### `telec config people`

Manage people

**Notes:**

- To edit people's subscriptions, modify the person config: ~/.teleclaude/people/{name}/teleclaude.yml

#### `telec config people list`

List people

#### `telec config people add`

Add a person

#### `telec config people edit`

Edit a person

#### `telec config people remove`

Remove a person

### `telec config env`

Manage environment variables

#### `telec config env list`

List environment variables

#### `telec config env set`

Set environment variables

### `telec config notify`

Toggle notification settings

### `telec config invite`

Generate invite links for a person

## `telec history`

Search and view agent session history

### `telec history search`

Search agent session transcripts

**Usage:** `telec history search [terms...]`

**Flags:**

- `--agent` (`-a`): Agent name(s) or 'all' (default: all)
- `--computer`: Query one or more remote computers via daemon API
- `--limit` (`-l`): Max results to show (default: 20)

### `telec history show`

Show full transcript for a session

**Usage:** `telec history show <session-id>`

**Flags:**

- `--agent` (`-a`): Agent name or 'all' (default: all)
- `--computer`: Fetch from a remote computer
- `--thinking`: Include thinking blocks
- `--raw`: Show raw transcript instead of mirror text
- `--tail`: Limit output to last N chars (0=unlimited)

## `telec memories`

Search and manage memory observations

### `telec memories list`

List memory observations

**Flags:**

- `--limit`: Max results (default: 50)
- `--type`: Filter by type: preference, decision, discovery, gotcha, pattern, friction, context
- `--project`: Filter by project name

### `telec memories search`

Search memory observations

**Usage:** `telec memories search <query>`

**Flags:**

- `--limit`: Max results (default: 20)
- `--type`: Filter by type: preference, decision, discovery, gotcha, pattern, friction, context
- `--project`: Filter by project name

### `telec memories save`

Save a memory observation

**Usage:** `telec memories save <text>`

**Flags:**

- `--title`: Observation title
- `--type`: Type: preference, decision, discovery, gotcha, pattern, friction, context
- `--project`: Project name

### `telec memories delete`

Delete a memory observation by ID

**Usage:** `telec memories delete <id>`

### `telec memories timeline`

Show observations around an anchor ID

**Usage:** `telec memories timeline <id>`

**Flags:**

- `--before`: Observations before anchor (default: 3)
- `--after`: Observations after anchor (default: 3)
- `--project`: Filter by project name


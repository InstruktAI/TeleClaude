---
description: Authoritative surface for the telec command-line tool.
id: project/spec/telec-cli-surface
scope: project
type: spec
visibility: public
delivered_by:
  - task-kind-and-kindless-intake
---

# CLI Surface — Spec

## What it is

The `telec` command-line tool is the primary interface for human operators. This specification defines the stable subcommands, arguments, and flags.

## Canonical fields

### Machine-Readable Surface

```yaml
tool: telec
subcommands:
  sessions:
    description: 'Manage agent sessions (list, start, send, tail, run, end, etc.).'
    subcommands:
      list:
        description: 'List active sessions.'
      start:
        description: 'Start a new agent session.'
      send:
        description: 'Send a message to a running session.'
      tail:
        description: 'Retrieve session messages (default latest user turn; --since/--full widen the window; transcript chain with unified tmux/session-data fallback).'
      run:
        description: 'Run an agent command in a new session.'
        flags:
          --command: 'Slash command to run (e.g. /next-build).'
          --project: 'Project directory path.'
          --args: 'Command arguments.'
          --agent: 'Agent: claude, gemini, codex.'
          --mode: 'Thinking mode: fast, med, slow.'
          --additional-context: 'Extra context injected into the worker startup frontmatter (e.g., artifact diffs for re-dispatch).'
      end:
        description: 'End a session.'
      unsubscribe:
        description: 'Stop notifications from a session.'
      result:
        description: 'Send a formatted result to the session user.'
      file:
        description: 'Send a file to the session user.'
      widget:
        description: 'Render a rich widget expression.'
      escalate:
        description: 'Escalate a customer session.'
  computers:
    description: 'List available computers in the network.'
  projects:
    description: 'List available project directories.'
  agents:
    description: 'Manage agent dispatch status and availability.'
    subcommands:
      availability:
        description: 'Get availability for all agents.'
      status:
        description: 'Set dispatch status for a specific agent.'
  auth:
    description: 'Manage terminal session authentication.'
    subcommands:
      login:
        args:
          - email: 'string'
      whoami:
        description: 'Show current terminal auth identity.'
      logout:
        description: 'Clear current terminal auth identity.'
  channels:
    description: 'Manage internal Redis stream channels.'
    subcommands:
      list:
        description: 'List active channels.'
      publish:
        description: 'Publish a message to a channel.'
  operations:
    description: 'Inspect durable long-running operations.'
    subcommands:
      get:
        args:
          - operation_id: 'UUID'
        description: 'Fetch durable operation status by operation_id.'
  revive:
    description: 'Revive session by TeleClaude session ID.'
    args:
      - session_id: 'UUID'
    flags:
      --attach: 'Attach to tmux session after revive.'
  init:
    description: 'Initialize project plumbing, sync artifacts, and optionally enrich docs.'
  version:
    description: 'Print version, channel, and commit hash.'
  sync:
    description: 'Validate (always blocks), then build doc artifacts and deploy.'
    flags:
      --skip-deploy: 'Validate only; do not build or deploy (read-only gate for pre-commit / CI / lint).'
      --project-root: 'Project root (default: cwd).'
  docs:
    description: 'Query documentation snippets.'
    flags:
      -b, --baseline-only: 'Show only baseline snippets.'
      -t, --third-party: 'Include third-party docs.'
      -a, --areas: 'Filter by taxonomy type.'
      -d, --domains: 'Filter by domain.'
      -p, --project-root: 'Project root (default: cwd).'
  todo:
    description: 'Manage work items.'
    subcommands:
      create:
        description: 'Create a substantive todo with content. Content is REQUIRED — an empty-content invocation is refused at the workflow service boundary and writes nothing (no roadmap row, no state row, no artifact row, no artifact-version row, no workflow.todo.created event). Replaces the v1 empty-skeleton path that produced misleading (stage=draft, phase=draft, state=in_progress) rows with no input artifact. The substantive-create outcome is identical regardless of which surface (`telec todo create` or `telec workflow todo create`) was invoked. (delivered_by v2-workflow-cli-refinement-commands; authoritative contract: project/spec/domain/workflow UC-WFL-1, UC-WFL-2.)'
        args:
          - slug: 'string'
          - content: 'string (REQUIRED)'
        flags:
          --project-root: 'Project root (default: cwd).'
          --after: 'Dependency slug (repeatable `--after <slug>` per PRD); comma-separated lists are also accepted as a shorthand. Multiple invocations append.'
          --kind: 'Optional. Todo kind: feature | change | bug | task. Omit to create a kind-less todo — the content is stored as the input artifact and /analyze-todo-input classifies it, proposing a kind for human approval (it proposes only; it never executes). task is a non-SDLC action lane, created silent and grooming a task-plan.'
          --group: 'Optional grouping label for the todo entry.'
          --description: 'Optional todo-entry description.'
          --silent: 'Persist without triggering autonomous pickup dispatch. The workflow.todo.created event is still emitted with creation_mode=silent and pickup_requested=false so cache/audit consumers observe the new aggregate; only the pickup dispatch consumers gate themselves on pickup_requested. (delivered_by v2-workflow-cli-refinement-commands; authoritative contract: UC-WFL-19.)'
      list:
        description: 'List todo entries grouped into sections (active, optionally delivered, optionally icebox, optionally removed). Default output shows only active entries; each visibility section opts in via its own flag pair (`--include-*` to interleave, `--*-only` to isolate). Each section''s tree is independent — cross-section edges drop out automatically. Soft-removed entries (status=removed) are hidden by default and only appear under the explicit `--include-removed` / `--removed-only` opt-in (UC-WFL-14); each removed row renders with its durable row id and `removed_at` age so the operator sees how much grace window remains. (active/delivered/icebox visibility is current; the removed-row visibility opt-in is pending, delivered_by roadmap-trash-reveal-ui.)'
        flags:
          --include-icebox: 'Interleave iceboxed entries alongside active entries.'
          --icebox-only: 'Show only iceboxed entries.'
          --include-delivered: 'Interleave the recent delivery history alongside active entries (defaults to a recent window; combine with --since).'
          --delivered-only: 'Show only delivered entries.'
          --since: 'Delivered-section window — duration (7d, 72h, 2w) or ISO date. Implies --include-delivered.'
          --include-removed: 'Interleave soft-removed entries alongside active entries; each removed row renders with `removed_at` age. (delivered_by roadmap-trash-reveal-ui.)'
          --removed-only: 'Show only soft-removed entries (no active/icebox/delivered). (delivered_by roadmap-trash-reveal-ui.)'
          --json: 'Emit a sectioned JSON object keyed by section name.'
        notes:
          - 'The --include-removed / --removed-only reveal is strictly opt-in; the default and every other read surface continue to hide soft-removed entries (workflow domain spec, "Removed entries are invisible to every default read path" invariant).'
      mark-phase:
        description: 'Operator override for the authoritative lifecycle phase field.'
        args:
          - slug: 'string'
        flags:
          --phase: 'Phase value matching a canonical lifecycle phase enum member.'
        notes:
          - 'Validates only the target phase prerequisites, then sets the lifecycle pointer to that phase.'
          - 'Preserves artifacts, but clears downstream authoritative stamps so old approvals do not reactivate future phases.'
      reconcile:
        description: 'Re-evaluate current todo evidence and align lifecycle_phase within one stage.'
        args:
          - slug: 'string'
        flags:
          --stage: 'Optional stage override: prepare or work.'
        notes:
          - 'Infers stage from the current lifecycle phase when --stage is omitted.'
          - 'Prepare reconciliation ignores work evidence; work reconciliation ignores prepare evidence.'
          - 'Does not dispatch work. Run telec todo prepare or telec todo work afterward.'
      validate:
        args:
          - slug: 'string (optional)'
        flags:
          --project-root: 'Project root (default: cwd).'
      split:
        description: 'Split a todo into child items. The parent roadmap row becomes a stateless holder derived from child group_slug rows: no todo_state row, no lifecycle phase, no non-input artifacts. The original parent input artifact is retained as frozen source material and cloned to each child at split time; it cannot be edited or removed afterward. Children bootstrap with fresh default_state() at lifecycle_phase=draft.'
        args:
          - slug: 'string'
        flags:
          --into: 'Space-separated child slugs.'
          --project-root: 'Project root (default: cwd).'
      remove:
        description: 'Soft-remove a todo: its roadmap row is marked `removed` with a `removed_at` tombstone, `prev_status`, and a `removed_deps` snapshot of its outgoing dependency edges; state, artifacts, and full version history are retained and the todo disappears from all default reads. ALL slug-keyed teardown happens now (while the slug unambiguously names this entry): both directions of its roadmap_deps edges are scrubbed and its worktree, local + remote branch, and workspace dir are removed. After a fixed recovery window a routine sweep hard-purges the row by durable row id (FK-cascaded state/artifacts/versions only — zero slug-keyed operations, so a reused-slug live todo is never touched). A fail-closed reactivation primitive (addressed by roadmap row id) restores a not-yet-purged removed todo (prev_status + replayed removed_deps) until then. (delivered_by roadmap-soft-delete-retention; authoritative contract: project/spec/domain/workflow.)'
        args:
          - slug: 'string'
        flags:
          --project-root: 'Project root (default: cwd).'
      freeze:
        description: 'Move a todo to the icebox so it no longer appears in the default active todo list or participates in active dependency resolution.'
        args:
          - slug: 'string'
      unfreeze:
        description: 'Promote an iceboxed todo back to the active todo list.'
        args:
          - slug: 'string'
      deliver:
        description: 'Move a todo to delivered and stamp the delivery commit.'
        args:
          - slug: 'string'
        flags:
          --commit: 'Commit hash (auto-detects HEAD if omitted).'
      rename:
        description: 'Atomically rename a live todo''s slug across todos.db, doc-snippet delivered_by frontmatter, and the on-disk worktree/branch/workspace. All-or-nothing with rollback if any leg fails; refused if the new slug is held by any non-removed entry, or if in-flight work is bound to the old slug. On success prints a summary naming old→new and the surfaces moved. Receipt-backed async (delivered_by telec-todo-rename).'
        args:
          - old_slug: 'string'
          - new_slug: 'string'
        flags:
          --project-root: 'Project root (default: cwd).'
      reactivate:
        description: 'Restore a soft-removed todo addressed by slug. Resolves the slug against the set of removed rows for that slug (UC-WFL-14) and dispatches the row-id-addressed reactivation primitive (UC-WFL-12). Fail-closed: refuses with a typed diagnostic and changes nothing when the slug names no removed row, when multiple removed rows share the slug (ambiguous — the diagnostic lists each candidate''s roadmap row id and removed_at so the operator can disambiguate via the reveal surface), or when a live (active/icebox) entry already holds the slug (live_twin_exists — carries the primitive''s structured reason). On success the entry''s footprint is restored (prev_status, replayed removed_deps, retained state/artifacts/versions become addressable again) and the daemon fires `todo_updated` so cached views refresh. (delivered_by roadmap-trash-reveal-ui; authoritative contract: project/spec/domain/workflow UC-WFL-12, UC-WFL-15.)'
        args:
          - slug: 'string'
        auth:
          system: '_SYS_ORCH'
          human: '_HR_MEMBER'
        auth_rationale: 'Mirrors telec todo remove (the inverse operation) and the icebox restore (same trust shape: an operator/member restoring a recoverable state on a todo they own).'
      show:
        description: 'Display the diagnostic state payload for a todo by slug. The default payload is artifact-body-light and diagnostic-rich: lifecycle state, roadmap facts, approvals, review verdicts, drift stamps, work/finalize progress, audit/events, next command hints, and artifact provenance are included, while `artifacts` is only a list of artifact names. Artifact bodies are omitted by default and can be restored under a separate `artifact_content` object with `--include-artifact-content`. Default soft-remove behavior is unchanged — a soft-removed slug refuses with a not-found diagnostic (default-hide invariant). With `--include-removed`, the resolver also searches removed rows for that slug and surfaces the show payload when exactly one removed row matches; ambiguous-slug and no-removed-row diagnostics use the same structured-reason vocabulary as `telec todo reactivate`. (the default behavior and artifact-content opt-in are current; the `--include-removed` opt-in is pending, delivered_by roadmap-trash-reveal-ui.)'
        args:
          - slug: 'string'
        flags:
          --include-artifact-content: 'Include artifact body content under the `artifact_content` object. The `artifacts` field remains a list of artifact names.'
          --include-removed: 'Also resolve the slug against the set of soft-removed rows; surfaces the show payload for a uniquely-matching removed row, or a typed ambiguity/no-match diagnostic — never returns a live row through this flag. (delivered_by roadmap-trash-reveal-ui.)'
      artifacts:
        description: 'Manage todo artifacts in todos.db.'
        subcommands:
          list:
            description: 'List artifact names for a todo.'
            args:
              - slug: 'string'
          read:
            description: 'Read one named artifact.'
            args:
              - slug: 'string'
              - name: 'artifact name'
          write:
            description: 'Write one named artifact and append version history.'
            args:
              - slug: 'string'
              - name: 'artifact name'
              - content: 'string'
          diff:
            description: 'Show a unified diff between two stored artifact versions.'
            args:
              - slug: 'string'
              - name: 'artifact name'
              - old_digest: 'string'
              - new_digest: 'string'
          remove:
            description: 'Hard-delete one non-input artifact and all version rows for that artifact. Missing artifacts are a successful no-op.'
            args:
              - slug: 'string'
              - name: 'artifact name (input is refused)'
            notes:
              - 'Refuses input because input is the seed artifact for a todo.'
      stamp:
        description: 'Record an authoritative lifecycle signal.'
        args:
          - slug: 'string'
        flags:
          --verdict: 'approve | changes_requested | needs_work | needs_decision'
          --phase: 'Review phase for --verdict: architecture_review | plan_review | build_review'
          --prd-approved: 'Mark PRD approved by the real human.'
          --architecture-skipped: 'Skip architecture phase with a reason.'
          --drift-reviewed: 'Record drift review: artifact, substantive|cosmetic, reason.'
          --deferrals-processed: 'Mark the deferrals artifact as processed.'
          --design-spec-confirmed: 'Confirm creative design-spec human gate.'
          --art-approved: 'Approve creative art human gate.'
          --visuals-approved: 'Approve creative visuals human gate.'
          --build-started: 'Start work from prepared and move to build_started.'
          --build-complete: 'Complete implementation work and move to build_complete.'
          --finalize-ready: 'Mark the reviewed worktree ready for finalize handoff.'
  workflow:
    description: 'Target v2 bounded-context namespace for workflow operations. Mirrors the workflow service contract and is the durable surface that survives the v1→v2 cutover. `telec todo ...` remains as transition compatibility; both spellings route to the same workflow service. (delivered_by v2-workflow-cli-refinement-commands.)'
    subcommands:
      todo:
        description: 'Workflow-namespace todo operations.'
        subcommands:
          create:
            description: 'Create a substantive todo with content via the target v2 namespace. Semantics are identical to `telec todo create` (UC-WFL-1, UC-WFL-19). (delivered_by v2-workflow-cli-refinement-commands.)'
            args:
              - slug: 'string'
              - content: 'string (REQUIRED)'
            flags:
              --project-root: 'Project root (default: cwd).'
              --after: 'Dependency slug (repeatable `--after <slug>` per PRD); comma-separated lists are also accepted as a shorthand. Multiple invocations append.'
              --kind: 'Todo kind.'
              --group: 'Optional grouping label.'
              --description: 'Optional todo-entry description.'
              --silent: 'Persist with creation_mode=silent and pickup_requested=false (cache/audit consumers still observe the event; pickup dispatch is suppressed).'
              --input-file: 'Read content from path instead of positional argument.'
          update:
            description: 'Atomically update a live todo''s metadata, dependencies, kind, and/or content. All supplied fields apply in a single transaction with rollback on partial failure. Dependency inputs REPLACE the entire `after` set (not patch). Positional content writes a new artifact version (default `input`, or the kind named by `--artifact`); implementation-plan content is selected explicitly with `--artifact implementation-plan` plus the appropriate kind. Update can NEVER move lifecycle phase — phase movement remains the prepare/work/integrate/stamp/reconcile state-machine verbs. Refuses YAML/JSON patch blobs; only typed parameter inputs are accepted. Writes through canonical artifact-kind validation; unknown kinds are refused before mutation. On success emits workflow.todo.updated with a change_summary listing the mutated fields. (delivered_by v2-workflow-cli-refinement-commands; authoritative contract: project/spec/domain/workflow UC-WFL-17.)'
            args:
              - slug: 'string'
              - content: 'string (optional)'
            flags:
              --project-root: 'Project root (default: cwd).'
              --artifact: 'Artifact kind to write the positional content as (default `input`). Must be a canonical artifact kind per ARTIFACT_NAMES.'
              --after: 'Dependency slug (repeatable `--after <slug>` per PRD); comma-separated lists are also accepted as a shorthand. The supplied set REPLACES the existing dependency set in full (not patched/appended).'
              --group: 'New grouping label.'
              --description: 'New todo-entry description.'
              --kind: 'New todo kind (validated against the canonical set).'
          rename:
            description: 'Workflow-namespace alias for `telec todo rename`. Atomically rename a live todo''s slug across todos.db, doc-snippet delivered_by frontmatter, and the on-disk worktree/branch/workspace. (delivered_by telec-todo-rename + v2-workflow-cli-refinement-commands; authoritative contract: project/spec/domain/workflow UC-WFL-13.)'
            args:
              - old_slug: 'string'
              - new_slug: 'string'
            flags:
              --project-root: 'Project root (default: cwd).'
          diff:
            description: 'Refinement diff for a single todo. Gathers, for the named slug only: each workflow-artifact diff between the artifact''s current version digest and its most recent approved/reviewed baseline digest (notably prd, architecture index, implementation-plan); PLUS each doc snippet whose frontmatter `delivered_by` list includes the slug, diffed against the git SHA that was current when the snippet acquired the slug (or against `main` HEAD for snippets without recorded provenance). Output is anchored by digest (artifacts) and git SHA (snippets) so a reviewer can re-verify deterministically. Reports nothing for slugs that own no artifact deltas and no delivered_by snippet membership. Implemented in terms of the low-level `workflow artifacts diff` primitive; never bypasses the digest-anchored version history. (delivered_by v2-workflow-cli-refinement-commands; authoritative contract: project/spec/domain/workflow UC-WFL-18.)'
            args:
              - slug: 'string'
            flags:
              --project-root: 'Project root (default: cwd).'
      artifacts:
        description: 'Workflow-namespace artifact operations.'
        subcommands:
          diff:
            description: 'Low-level artifact diff primitive — unified diff between two exact artifact versions resolved by digest in the artifact-version history. The todo-scoped `telec workflow todo diff` (UC-WFL-18) is implemented in terms of this primitive. (delivered_by v2-workflow-cli-refinement-commands.)'
            args:
              - slug: 'string'
              - name: 'artifact kind'
              - old_digest: 'string'
              - new_digest: 'string'
            flags:
              --project-root: 'Project root (default: cwd).'
  events:
    description: 'Event catalog and platform commands.'
    subcommands:
      list:
        description: 'List event schemas: type, level, domain, visibility, description, actionable.'
        flags:
          --domain: 'Filter by domain.'
  content:
    description: 'Manage content pipeline.'
    subcommands:
      dump:
        description: 'Fire-and-forget content dump to publications inbox.'
        args:
          - text: 'string (description or raw content to dump)'
        flags:
          --slug: 'Custom slug (default: auto-generated from text).'
          --tags: 'Comma-separated tags.'
          --author: 'Author identity (default: terminal auth).'
  bugs:
    description: 'Manage bug reports and fixes.'
    subcommands:
      report:
        description: 'Scaffold a bug from a description; lifecycle router dispatches /next-work.'
      create:
        description: 'Scaffold a bug from a description; lifecycle router dispatches /next-work. Accepts positional <description> or --description <text>; slug is auto-generated or overridden with --slug.'
      list:
        description: 'List in-flight bug fixes with status (prefers worktree state when present).'
  auth:
    description: 'Terminal login identity commands.'
    subcommands:
      login:
        args:
          - email: 'string'
        description: 'Set terminal login identity for this TTY.'
      whoami:
        description: 'Show terminal login identity for this TTY.'
      logout:
        description: 'Clear terminal login identity for this TTY.'
  config:
    description: 'Interactive setup wizard (canonical setup surface) plus get/patch/validate subcommands.'
    subcommands:
      wizard:
        description: 'Open the interactive configuration wizard — the canonical single human-facing setup surface for every TeleClaude-persisted setup value. During normal setup no other TeleClaude-owned interactive prompt collects those values; prompts owned by external systems (OS permission dialogs, OAuth browser login, WhatsApp Business Cloud API token setup, agent CLI permission probes) are explicit exceptions. Behavioural contract: project/spec/feature/config/setup-wizard.'
      get:
        args:
          - paths: 'string... (optional dot-separated config paths)'
        flags:
          -p, --project-root: 'Project root (default: cwd).'
          -f, --format: 'Output format (yaml|json).'
      patch:
        flags:
          -p, --project-root: 'Project root (default: cwd).'
          -f, --format: 'Output format (yaml|json).'
          --yaml: 'Inline YAML patch.'
          --from-file: 'Path to YAML patch file.'
      validate:
        flags:
          -p, --project-root: 'Project root (default: cwd).'
  history:
    description: 'Search and view agent session history.'
    subcommands:
      search:
        description: 'Search agent session transcripts.'
        args:
          - terms: 'string...'
        flags:
          -a, --agent: 'Agent name(s) or all (default: all).'
          -l, --limit: 'Max results (default: 20).'
      show:
        description: 'Show full transcript for a session.'
        args:
          - session_id: 'string'
        flags:
          -a, --agent: 'Agent name or all (default: all).'
          --thinking: 'Include thinking blocks.'
          --tail: 'Limit output to last N chars.'
  memories:
    description: 'Read or remove durable personal-preference observations about the human. Memories capture meta-level things about who the human is — relational stance, values, communication style, vision — never coding norms, architectural decisions, or operational gotchas (those live in policies, principles, and addenda). Memories are written exclusively by the session memory extraction agent (the memory scraper, invoked via /extract-memory); other agents must never create them.'
    subcommands:
      search:
        description: 'Search personal-preference observations about the human.'
        args:
          - query: 'string'
        flags:
          --limit: 'Max results (default: 20).'
          --type: 'Filter by observation type stored in the schema.'
          --project: 'Filter by project name.'
      save:
        description: 'Persist a memory observation. Reserved for the session memory extraction agent (the memory scraper, invoked via /extract-memory) — other agents must never call this. Hidden from the baseline surface (omitted from subcommand listings, flag-group sections, and shell completion); reachable only by explicit name, e.g. `telec memories save -h`.'
        args:
          - text: 'string'
        flags:
          --title: 'Observation title.'
          --type: 'Observation type.'
          --project: 'Project name.'
      delete:
        description: 'Delete a personal-preference observation by ID (typically run by the human while pruning).'
        args:
          - id: 'integer'
      timeline:
        description: 'Show personal-preference observations around an anchor ID.'
        args:
          - id: 'integer'
        flags:
          --before: 'Observations before anchor (default: 3).'
          --after: 'Observations after anchor (default: 3).'
          --project: 'Filter by project name.'
  signals:
    description: 'Signal pipeline status and diagnostics.'
    subcommands:
      status:
        description: 'Show signal pipeline counts and last ingest time.'
  code:
    description: 'Code quality and commit tools. The git wrapper blocks raw `git add` and `git commit` for agents inside tmux; this namespace is the sanctioned channel for both.'
    subcommands:
      lint:
        description: 'Run language-aware lint pipeline using project-managed tool entrypoints.'
        flags:
          --step: 'Run a single pipeline step (e.g. guardrails, ruff_check).'
          --all: 'Run against all configured sources, skip workspace scoping.'
      test:
        description: 'Run language-aware test suite using project-managed tool entrypoints.'
        flags:
          --expensive: 'Include expensive/slow tests.'
          --all: 'Run all tests, skip workspace scoping.'
          --update-snapshots: 'Update snapshot files after reading diffs. Use only when test failures show snapshot deltas that match your intended change.'
      format:
        description: 'Run language-aware code formatter.'
        flags:
          --all: 'Format all configured sources, skip workspace scoping.'
      changed:
        description: 'List workspace-scoped changed files — the set telec would consider for the next commit.'
      add:
        description: 'Stage files for the next commit. Sealed equivalent of `git add` for the three cases git''s data model genuinely requires staging: (1) NEW untracked files (must enter the index before commit pathspec can match), (2) unmerged-index files post-conflict (must be marked resolved), (3) partial-staged tracked files — staged hunks plus later working-tree delta — which must be fully (re)staged so the pathspec commit does not silently sweep in unstaged hunks; this is the recovery path the partial-staging guard in `telec code commit` directs agents to. Modified-tracked files that are NOT partial-staged do not need staging; `telec code commit` picks them up via pathspec straight from the working tree.'
        args:
          - paths: 'one or more paths (positional)'
      commit:
        description: 'Commit workspace-scoped changes via a pathspec-scoped commit. Sealed contract — exactly one quoted message, optionally `--approved` and `--include <path> ...`. Nothing is forwarded to git (no `-m`, `-F`, `--`, bare pathspecs, or git flags). Modified-tracked files in scope that are NOT partial-staged are auto-included via pathspec and ride straight from the working tree. Partial-staged tracked files in the pathspec are BLOCKED by the partial-staging guard (because `git commit -- <path>` would otherwise sweep unstaged hunks the agent did not declare); the agent recovers by running `telec code add <path>` to fully restage, then retries the commit. NEW (untracked) files in scope are NOT auto-committed and must be declared via `telec code add` or `--include` (safety net against incidental temp/scratch artifacts). Unmerged-index files (post-conflict) in the pathspec are staged internally for the integrator conflict path. On main + non-integrator a bare invocation surfaces the Path A/B/C classification card and exits; `--approved` is the gate to actually commit.'
        args:
          - message: 'one quoted commit message (required with --approved)'
        flags:
          --approved: 'Human-approved commit gate. Required to actually commit; absence on main prints Path A/B/C and exits.'
          --include: 'Declare files outside the resolved workspace scope to add to this commit. Space-separated paths; each must contribute a change. Place after the message (or after --approved) so the collector does not swallow the message.'
  operations:
    description: 'Inspect durable long-running operations.'
    subcommands:
      get:
        description: 'Fetch durable operation status by operation_id.'
        args:
          - operation_id: 'string'
```

## Known caveats

- Subcommand removals or renames are considered breaking changes (Minor bump).
- Changes to argument order or required flags are considered breaking changes.
- Adding a new subcommand is a feature addition (Minor bump).
- Changes to descriptions only are patches.

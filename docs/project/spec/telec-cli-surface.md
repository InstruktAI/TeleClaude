---
id: 'project/spec/telec-cli-surface'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for the telec command-line tool.'
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
        description: 'Retrieve session messages (transcript chain with unified tmux/session-data fallback).'
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
    description: 'Validate refs and build doc artifacts.'
    flags:
      --warn-only: "Warn but don't fail."
      --validate-only: 'Validate without building.'
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
        args:
          - slug: 'string'
        flags:
          --project-root: 'Project root (default: cwd).'
          --after: 'Comma-separated dependency slugs.'
      mark-phase:
        description: 'Operator override for the authoritative lifecycle phase field.'
        args:
          - slug: 'string'
        flags:
          --phase: 'Phase value matching a canonical lifecycle phase enum member.'
        notes:
          - 'Validates only the target phase prerequisites, then sets the lifecycle pointer to that phase.'
          - 'Preserves artifacts, but clears downstream authoritative stamps so old approvals do not reactivate future phases.'
      validate:
        args:
          - slug: 'string (optional)'
        flags:
          --project-root: 'Project root (default: cwd).'
      split:
        description: 'Split a todo into child items. Children inherit the parent approved prepare phase: requirements-approved → children start at plan_drafting; plan-approved → children start at prepared (ready for build).'
        args:
          - slug: 'string'
        flags:
          --into: 'Space-separated child slugs.'
          --project-root: 'Project root (default: cwd).'
      remove:
        args:
          - slug: 'string'
        flags:
          --project-root: 'Project root (default: cwd).'
      stamp:
        description: 'Record an authoritative lifecycle signal.'
        args:
          - slug: 'string'
        flags:
          --verdict: 'approve | changes_requested | needs_work | needs_decision'
          --phase: 'Review phase for --verdict: requirements_review | test_spec_review | plan_review | build_review'
          --dor-score: 'DOR score (integer). Evidence only unless paired with a status.'
          --dor-status: 'pass | needs_work | needs_decision'
          --requirements-ready: 'Complete discovery/requirements authoring and advance to requirements_review.'
          --grounding-invalidated: 'Invalidate grounding and route to re_grounding.'
          --specs-built: 'Complete test-spec authoring and advance to test_spec_review.'
          --plan-ready: 'Complete plan authoring and advance to plan_review.'
          --build-started: 'Start work from prepared and move to build_started.'
          --build-complete: 'Complete implementation work and move to build_complete.'
          --finalize-ready: 'Mark the reviewed worktree ready for finalize handoff.'
  roadmap:
    description: 'View and manage the work item roadmap.'
    subcommands:
      add:
        args:
          - slug: 'string'
        flags:
          --group: 'Slug of holder todo.'
          --after: 'Comma-separated dependency slugs.'
          --before: 'Insert before this slug.'
          --description: 'Summary description.'
          --project-root: 'Project root (default: cwd).'
      remove:
        args:
          - slug: 'string'
        flags:
          --project-root: 'Project root (default: cwd).'
      move:
        args:
          - slug: 'string'
        flags:
          --before: 'Move before this slug.'
          --after: 'Move after this slug.'
          --project-root: 'Project root (default: cwd).'
      deps:
        args:
          - slug: 'string'
        flags:
          --after: 'Comma-separated dependency slugs.'
          --project-root: 'Project root (default: cwd).'
      freeze:
        args:
          - slug: 'string'
        flags:
          --project-root: 'Project root (default: cwd).'
      deliver:
        args:
          - slug: 'string'
        flags:
          --commit: 'Commit hash.'
          --title: 'Delivery title.'
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
        description: 'Scaffold a bug from an explicit slug; lifecycle router dispatches /next-work.'
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
    description: 'Interactive configuration (or get/patch/validate subcommands).'
    subcommands:
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
    description: 'Search and manage memory observations.'
    subcommands:
      search:
        description: 'Search memory observations.'
        args:
          - query: 'string'
        flags:
          --limit: 'Max results (default: 20).'
          --type: 'Filter by type.'
          --project: 'Filter by project name.'
      save:
        description: 'Save a memory observation.'
        args:
          - text: 'string'
        flags:
          --title: 'Observation title.'
          --type: 'Observation type.'
          --project: 'Project name.'
      delete:
        description: 'Delete a memory observation by ID.'
        args:
          - id: 'integer'
      timeline:
        description: 'Show observations around an anchor ID.'
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
    description: 'Code quality and commit tools.'
    subcommands:
      lint:
        description: 'Run language-aware lint pipeline.'
        flags:
          --step: 'Run a single pipeline step (e.g. guardrails, ruff_check).'
      test:
        description: 'Run language-aware test suite.'
        flags:
          --expensive: 'Include expensive/slow tests.'
      format:
        description: 'Run language-aware code formatter.'
      commit:
        description: 'Stage session-scoped files, lint, format, and commit.'
        flags:
          -m: 'Commit message. Other args pass through to git commit.'
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

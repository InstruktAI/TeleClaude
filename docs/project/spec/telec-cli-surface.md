---
id: 'project/spec/telec-cli-surface'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for the telec command-line tool.'
---

# CLI Surface — Spec

## Definition

The `telec` command-line tool is the primary interface for human operators. This specification defines the stable subcommands, arguments, and flags.

## Machine-Readable Surface

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
        description: 'Retrieve session messages.'
      run:
        description: 'Run an agent command in a new session.'
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
  deploy:
    description: 'Deploy latest code to remote computers.'
  agents:
    description: 'Manage agent dispatch status and availability.'
    subcommands:
      availability:
        description: 'Get availability for all agents.'
      status:
        description: 'Set dispatch status for a specific agent.'
  channels:
    description: 'Manage internal Redis stream channels.'
    subcommands:
      list:
        description: 'List active channels.'
      publish:
        description: 'Publish a message to a channel.'
  revive:
    description: 'Revive session by TeleClaude session ID.'
    args:
      - session_id: 'UUID'
    flags:
      --attach: 'Attach to tmux session after revive.'
  init:
    description: 'Initialize docs sync and auto-rebuild watcher.'
  sync:
    description: 'Validate refs and build doc artifacts.'
    flags:
      --warn-only: "Warn but don't fail."
      --validate-only: 'Validate without building.'
      --project-root: 'Project root (default: cwd).'
  watch:
    description: 'Watch project for changes and auto-sync.'
    flags:
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
      validate:
        args:
          - slug: 'string (optional)'
        flags:
          --project-root: 'Project root (default: cwd).'
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
  bugs:
    description: 'Manage bug reports and fixes.'
    subcommands:
      report:
        description: 'Report a bug, scaffold, and dispatch fix.'
      create:
        description: 'Scaffold bug files for a slug.'
      list:
        description: 'List in-flight bug fixes with status.'
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
```

## Constraints

- Subcommand removals or renames are considered breaking changes (Minor bump).
- Changes to argument order or required flags are considered breaking changes.
- Adding a new subcommand is a feature addition (Minor bump).
- Changes to descriptions only are patches.

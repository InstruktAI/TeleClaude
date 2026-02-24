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
  list:
    description: 'List active TeleClaude sessions across all computers.'
  claude:
    description: 'Start interactive Claude Code session.'
    args:
      - mode: 'fast|med|slow'
      - prompt: 'string (optional)'
  gemini:
    description: 'Start interactive Gemini session.'
    args:
      - mode: 'fast|med|slow'
      - prompt: 'string (optional)'
  codex:
    description: 'Start interactive Codex session.'
    args:
      - mode: 'fast|med|slow|deep'
      - prompt: 'string (optional)'
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
      demo:
        args:
          - slug: 'string (optional)'
        flags:
          --project-root: 'Project root (default: cwd).'
      remove:
        args:
          - slug: 'string'
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
        args:
          - description: 'string'
        flags:
          --slug: 'string (optional)'
          --project-root: 'Project root (default: cwd).'
      create:
        args:
          - slug: 'string'
        flags:
          --project-root: 'Project root (default: cwd).'
      list:
        flags:
          --project-root: 'Project root (default: cwd).'
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
      people:
        description: 'Manage people (list/add/edit/remove).'
      env:
        description: 'Manage environment variables (list/set).'
      notify:
        description: 'Toggle notification settings.'
      invite:
        description: 'Generate invite links for a person.'
  onboard:
    description: 'Guided onboarding wizard for first-run setup.'
```

## Constraints

- Subcommand removals or renames are considered breaking changes (Minor bump).
- Changes to argument order or required flags are considered breaking changes.
- Adding a new subcommand is a feature addition (Minor bump).
- Changes to descriptions only are patches.

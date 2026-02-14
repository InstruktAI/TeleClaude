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
      --project-root: 'Project root directory.'
  watch:
    description: 'Watch project for changes and auto-sync.'
    flags:
      --project-root: 'Project root directory.'
  docs:
    description: 'Query documentation snippets.'
    flags:
      -b, --baseline-only: 'Show only baseline snippets.'
      -t, --third-party: 'Include third-party docs.'
      -a, --areas: 'Filter by taxonomy type.'
      -d, --domains: 'Filter by domain.'
      -p, --project-root: 'Project root directory.'
  todo:
    description: 'Manage work items.'
    subcommands:
      create:
        args:
          - slug: 'string'
        flags:
          --project-root: 'Project root directory.'
          --after: 'Comma-separated dependency slugs.'
      validate:
        args:
          - slug: 'string (optional)'
        flags:
          --project-root: 'Project root directory.'
  config:
    description: 'Interactive configuration (or get/patch/validate subcommands).'
    subcommands:
      get:
        args:
          - paths: 'string... (optional dot-separated config paths)'
        flags:
          -p, --project-root: 'Project root directory.'
          -f, --format: 'Output format (yaml|json).'
      patch:
        flags:
          -p, --project-root: 'Project root directory.'
          -f, --format: 'Output format (yaml|json).'
          --yaml: 'Inline YAML patch.'
          --from-file: 'Path to YAML patch file.'
      validate:
        flags:
          -p, --project-root: 'Project root directory.'
  onboard:
    description: 'Guided onboarding wizard for first-run setup.'
```

## Constraints

- Subcommand removals or renames are considered breaking changes (Minor bump).
- Changes to argument order or required flags are considered breaking changes.
- Adding a new subcommand is a feature addition (Minor bump).
- Changes to descriptions only are patches.

## See Also

- project/spec/mcp-tool-surface

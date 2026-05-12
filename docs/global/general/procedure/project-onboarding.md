---
id: 'general/procedure/project-onboarding'
type: 'procedure'
domain: 'general'
scope: 'global'
description: 'AI-driven project onboarding via telec projects onboard / analyze / assess — runs init plumbing then dispatches doc-snippet analysis and quality-config assessment agent sessions.'
---

# Project Onboarding — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/project-initialization.md
- @~/.teleclaude/docs/software-development/procedure/project-analysis.md
- @~/.teleclaude/docs/software-development/spec/init-scaffolding.md

## Goal

Onboard a project end-to-end to TeleClaude: install plumbing, generate project-specific
documentation snippets that make the codebase legible to AI, and assess the project's
quality-tool configuration against blessed templates.

This is the AI-driven counterpart to `telec init`. `init` handles plumbing; onboarding
adds the intelligence layer.

## Preconditions

- `telec` CLI is available and the daemon is running.
- At least one agent is enabled for session dispatch.
- The current working directory is a project root (or will become one).

## Steps

### Option A — `telec projects onboard` (full bootstrap)

Runs in three stages:

1. **Init plumbing** (synchronous, blocking): executes `init_project` — agent CLIs,
   git filters, pre-commit hooks, artifact sync, slug derivation, project registration,
   release-channel prompt, event-domain seeding. See the project-initialization
   procedure for the per-step contract.
2. **Config assessment dispatch** (fire-and-forget): spawns a `/projects-assess-config`
   agent session that compares the project's quality tooling against
   `templates/quality/{language}/`.
3. **Doc-snippet analysis dispatch** (fire-and-forget): spawns a `/projects-analyze`
   agent session that follows the project-analysis procedure and emits schema-valid
   snippets under `docs/project/`.

The two agent sessions run concurrently in tmux after dispatch. Monitor progress
via `telec sessions list` or the TUI.

### Option B — `telec projects analyze` (analysis only)

Targeted re-run of the doc-snippet analysis. Skips `init` and the config assessment.
Useful when codebase structure has shifted and the project snippets need refreshing.

### Option C — `telec projects assess` (assessment only)

Targeted re-run of the quality-tool config assessment. Skips `init` and the doc-snippet
analysis. Useful after the team adopts a new quality rule or upgrades blessed
templates.

## Outputs

- Schema-valid project doc snippets under `docs/project/` with
  `generated_by: telec-init` frontmatter (internal marker — unchanged for
  backward compatibility with existing analyzed projects).
- `.telec-init-meta.yaml` metadata recording the analysis run.
- Per-language quality-config assessment report (Present / Missing / Recommendations)
  printed in the assess session's transcript.

## Recovery

- All dispatches are idempotent and dedup against running sessions: re-invoking
  `telec projects onboard` while a previous run is in flight skips the live session
  rather than spawning a duplicate.
- If dispatch fails (non-zero return code, timeout, OS error), the failure is logged
  and a manual retry command is printed.
- The `init` stage of `onboard` is itself idempotent — re-running it is safe and
  will skip already-configured steps.

## See Also

- ~/.teleclaude/docs/general/procedure/project-initialization.md
- ~/.teleclaude/docs/software-development/procedure/project-analysis.md
- ~/.teleclaude/docs/software-development/spec/init-scaffolding.md
- ~/.teleclaude/docs/general/policy/snippet-value-contract.md

---
description: 'AI-driven project onboarding — initialize the project with telec config project init, then explicitly start the quality-config assessment and doc-snippet analysis sessions.'
visibility: 'public'
---

# Project Onboarding — Procedure

## Required reads

- @~/.teleclaude/docs/general/procedure/project-initialization.md
- @~/.teleclaude/docs/sdlc/procedure/project-analysis.md
- @~/.teleclaude/docs/sdlc/spec/init-scaffolding.md

## Goal

Onboard a project end-to-end to TeleClaude: install plumbing, generate project-specific
documentation snippets that make the codebase legible to AI, and assess the project's
quality-tool configuration against blessed templates.

Initialization handles plumbing and starts no agent. The intelligence layer is added by
agent sessions the operator starts explicitly through `telec sessions`, the only command
surface that starts agents.

## Preconditions

- `telec` CLI is available and the daemon is running.
- At least one agent is enabled for session dispatch.
- The current working directory is a project root (or will become one).

## Steps

1. **Initialize.** From the project root, run `telec config project init`. It executes
   project artifact sync, slug derivation, project registration, the release-channel
   prompt, and event-domain seeding; see the project-initialization procedure for the
   per-step contract. It returns when plumbing is complete and starts no session.
2. **Check for sessions already in flight.** Run `telec sessions list` and look for an
   open session whose project path is this root and whose command is the one about to
   be started. Starting a second one duplicates work; the sessions surface does not
   deduplicate on the caller's behalf.
3. **Assess the quality configuration.** Start
   `telec sessions run --command /projects-assess-config --path <project-root>`. The
   session compares the project's quality tooling against
   `templates/quality/{language}/`.
4. **Analyze the codebase.** Start
   `telec sessions run --command /projects-analyze --path <project-root>`. The session
   follows the project-analysis procedure and emits schema-valid snippets under
   `docs/local/`.

Steps 3 and 4 run concurrently once started, and either can be started again on its own
later: re-run the analysis when codebase structure has shifted, and the assessment after
the team adopts a new quality rule or upgrades blessed templates.

## Outputs

- Schema-valid project doc snippets under `docs/local/` with
  `generated_by: telec-init` frontmatter (internal marker — unchanged for
  backward compatibility with existing analyzed projects).
- `.telec-init-meta.yaml` metadata recording the analysis run.
- Per-language quality-config assessment report (Present / Missing / Recommendations)
  printed in the assess session's transcript.

## Recovery

- `telec config project init` is idempotent — re-running it is safe and will skip
  already-configured steps.
- If `telec sessions run` fails to start a session, it reports the failure; start it
  again once the cause is resolved.

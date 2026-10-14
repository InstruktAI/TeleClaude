---
description: 'AI-driven project onboarding — adopt the project with telec config project adopt, then explicitly start the quality-config assessment and doc-snippet analysis sessions.'
visibility: 'public'
role: helper
dispatch:
  agent: [claude, codex, gemini, deepseek]
  thinking_mode: slow
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

<!-- planned:role-scoped-cli-context -->

When this procedure is your session’s launch assignment, retrieve its focused tool
help with `telec -h --expand-role` before starting the assigned work. When reading
it inline, retain your current session’s tool context. Use `telec <command> -h`
for individual commands.
<!-- /planned:role-scoped-cli-context -->

1. **Adopt.** From the project root, run `telec config project adopt`. It
   registers the project where it is: it gives the folder its own repository when
   needed, checks placement and owner, declares capabilities, converges plumbing,
   and derives the slug; see the project-initialization procedure for the
   per-step contract. It returns when plumbing is complete and starts no session.
   Running it again in a project already registered converges that project.

2. **Check for sessions already in flight.** Run `telec sessions list` and look for an
   open session whose project path is this root and whose command is the one about to
   be started. Starting a second one duplicates work; the sessions surface does not
   deduplicate on the caller's behalf.
3. **Assess the quality configuration.** Start
   `telec sessions run --command sdlc/procedure/code-config-assessment --path <project-root>`. The
   session compares the project's quality tooling against
   `templates/quality/{language}/`.
4. **Analyze the codebase.** Start
   `telec sessions run --command sdlc/procedure/project-analysis --path <project-root>`. The session
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

- `telec config project adopt` is idempotent — re-running it is safe and will
  skip already-configured steps.
- If `telec sessions run` fails to start a session, it reports the failure; start it
  again once the cause is resolved.

## Discipline

Run the commands exactly as the procedure states them; a remembered command from an earlier
onboarding may no longer exist. Before an analysis or assessment session starts for this root,
check `telec sessions list` so a second one is not started beside a live one.

---
description: 'Governance for agent-artifact sources, transforms, and ownership: master files are locked thin wrappers, generated entrypoints and runtime homes are never edited, knowledge lives in snippets.'
visibility: 'public'
---

# Agent Artifact Governance — Policy

## Rules

- Project-local agent artifacts live under `.agents/`. Artifact types are treated equally: `agents/`, `commands/`, and `skills/` are all published and distributed.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- **Agent artifacts are authored in-context on `main`, never routed through a todo.** Agent artifacts (commands, skills, agents) are standalone agent-infrastructure plumbing with no coupling to code. What they should say is the human's decision; writing them is the agent's work, executed directly on `main` in the live session where that decision was made — never routed through a todo or the build lifecycle, never authored by a dispatched builder in a slug worktree. The gate is the human's presence in the session, which the agent detects; it is neither a separate approval step nor a requirement that the human edit or commit the file. Having no code to gate against, artifacts carry no pending markers and no `delivered_by`; the agent commits the complete artifact and `telec sync` deploys it.
- Any `AGENTS.master.md` in a project is inflated by `telec sync` into an adjacent `AGENTS.md`.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- **Agent artifacts are authored in-context on `main`, never routed through a todo.** Agent artifacts (commands, skills, agents) are standalone agent-infrastructure plumbing with no coupling to code. What they should say is the human's decision; writing them is the agent's work, executed directly on `main` in the live session where that decision was made — never routed through a todo or the build lifecycle, never authored by a dispatched builder in a slug worktree. The gate is the human's presence in the session, which the agent detects; it is neither a separate approval step nor a requirement that the human edit or commit the file. Having no code to gate against, artifacts carry no pending markers and no `delivered_by`; the agent commits the complete artifact and validates its sources with bare `telec sync`. The watcher publishes after source activity settles.
- A deployment pass inflates any `AGENTS.master.md` in a project into an adjacent `AGENTS.md`.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->
<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Master files are thin wrappers. Their only authored contents are `## Purpose` and `## Required reads`. Only the repository-root `AGENTS.master.md` produces the project entrypoint and receives the `telec sync`-generated project baseline index and project activatable-procedure catalog. A nested master produces a directory-local entrypoint from its own authored content and required reads; it never inherits project-wide baseline material. They are never a knowledge home — all knowledge lives in doc snippets under `docs/`, and developer-experience prose lives in the README. A contract, procedure, architecture note, or operational note authored into a master file is a defect to be relocated to its rightful snippet.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Master files are thin wrappers. Their only authored contents are `## Purpose` and `## Required reads`. Only the repository-root `AGENTS.master.md` produces the project entrypoint and receives the deployment-generated project baseline index and project activatable-procedure catalog. A nested master produces a directory-local entrypoint from its own authored content and required reads; it never inherits project-wide baseline material. They are never a knowledge home — all knowledge lives in doc snippets under `docs/`, and developer-experience prose lives in the README. A contract, procedure, architecture note, or operational note authored into a master file is a defect to be relocated to its rightful snippet.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Master files are locked against unprompted edits: an agent never edits a master file on its own initiative or as a side effect of other work — only when the human raises the change in the session, and then the agent makes the edit. The lock guards the wrapper against accreting knowledge; it does not route typing to the human. It is declared by a `LOCKED_FILE` sentinel at the top and bottom of each master file.
- A `CLAUDE.md` companion is always created or replaced next to each `AGENTS.master.md` with a single line: `@./AGENTS.md`.
- Generated outputs under `dist/` are build artifacts. Do not edit them directly.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- The generated per-agent entrypoint files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) are build outputs of `telec sync` — never edit them directly. Author the source artifacts and run `telec sync`; new instruction text belongs in a source addendum, never in a generated file.
- Deployed runtime directories (`~/.claude/`, `~/.codex/`, `~/.gemini/`) are also build outputs — never create or edit files there directly. Always author in source and run `telec sync`. This applies to any future agent runtime: `~/.{agent}/` directories are always deployment targets, never sources.
- Documentation indexes (for example `docs/index.yaml` and baseline index blocks in generated `AGENTS.md`) are generated by `telec sync`; do not hand-edit them.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- The generated per-agent entrypoint files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`) are build outputs of the deployment pipeline — never edit them directly. Author the source artifacts, then use bare `telec sync` to validate; new instruction text belongs in a source addendum, never in a generated file.
- Deployed runtime directories (`~/.claude/`, `~/.codex/`, `~/.gemini/`) are also build outputs — never create or edit files there directly. Always author in source; the watcher publishes validated sources after activity settles. This applies to any future agent runtime: `~/.{agent}/` directories are always deployment targets, never sources.
- Documentation indexes (for example `docs/index.yaml` and baseline index blocks in generated `AGENTS.md`) are generated by the deployment pipeline; do not hand-edit them.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Inline references are expanded for Claude, Codex, and Gemini outputs.
- Frontmatter is preserved by default; `hooks` are only emitted for Claude outputs.
- Every skill entrypoint keeps a small universal identity contract: `SKILL.md`
  must declare non-empty `name` and `description` frontmatter, and `name` must
  equal the containing folder. Supporting Markdown remains package content and
  is not graded against TeleClaude's artifact taxonomy.
- `teleclaude_taxonomy: true` is the explicit opt-in for a TeleClaude-authored
  skill body. Only those skill entrypoints are validated against TeleClaude's
  heading, section-order, Required-reads, inline-reference, and See Also rules.
  Without that field, the skill body retains its upstream structure. Both forms
  use the same rendering pipeline; the field changes validation, not publication.
- **Quality-defining configuration is governed content: never weakened by its own author's session.** Type-checker configuration (mypy/pyright sections, tsconfig strictness flags), linter rule selections and ignore lists, suppression baselines, and the sources of the quality guardrails lane define the floor every other change is measured against. An agent never relaxes them — removing a rule, adding an ignore or suppression key, disabling an error category, widening an exemption, excluding a first-party module — except through independent deep review: a separate reviewer session with no stake in the work the relaxation would unblock, which explicitly approves that specific relaxation on its merits. The session whose work is blocked by a quality wall never approves moving that wall. Tightening is always permitted without review. Exemption: third-party accommodation stanzas whose module pattern targets code outside the project's own package(s); an override stanza targeting first-party modules is a relaxation and is governed.

## Rationale

- Treating artifacts uniformly avoids cherry-picking and missing capabilities.
- Agent artifacts govern agents and have no code coupling, so authoring them on `main` in the session that motivated them keeps their language and intent intact — dispatching them through a todo hands them to a worker that never heard the exchange, which loses the meaning in translation, and with no code delivery there is nothing for a todo to carry.
- Deciding what an artifact should say and writing it are distinct acts. The human holds the first; the agent performs the second, as it does for every other file in the system. Rules that assign the human the mechanical act describe a division of labor that does not exist here, and an agent reading them either stalls waiting for work the human will never do or hands that work back.
- Inflating master files keeps agent runtimes in sync while keeping source files stable.
- Thin, locked wrappers keep knowledge in its rightful home (snippets) and the master file from accreting a parallel, drifting manual.
- Limiting `hooks` to Claude matches current agent capabilities and avoids invalid configs.
- Quality configuration is the wall agent work is measured against; under goal pressure, any checker its own subject can edit gets edited toward green, one defensible commit message at a time. Governing the wall's definition places it outside the constrained author's unilateral reach.

## Scope

- Applies to every project that adopts TeleClaude artifact generation and distribution.

## Enforcement

- Distribution runs validate normalized authored commands and agents before output.
  Every skill entrypoint is identity-validated; only a skill declaring
  `teleclaude_taxonomy: true` is additionally graded against TeleClaude's body
  taxonomy. Supporting Markdown under either skill scope retains its authored
  structure.
- Generated files under `dist/` and deployed runtime directories are overwritten on each distribution run.
- A master file containing anything beyond `## Purpose` and `## Required reads` is a defect; relocate the content to a snippet or the README.
- A nested generated `AGENTS.md` containing the project baseline index or project activatable-procedure catalog is a defect; only the repository-root generated entrypoint may carry those project-wide sections.
- A commit that loosens quality configuration without a recorded independent approval is a violation. Reviewers treat maintenance framing of such diffs — "cleanup", "chore", "relax for now" — as the signature of erosion, not as mitigation.

## Exceptions

- None.

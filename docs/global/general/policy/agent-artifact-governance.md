---
description: 'Governance for agent-artifact sources, transforms, and ownership: master files are locked thin wrappers, generated entrypoints and runtime homes are never edited, knowledge lives in snippets.'
visibility: 'public'
---

# Agent Artifact Governance — Policy

## Rules

- Agent artifacts carry the same tier shape documentation has. In a repository they live under `agents/{global,local}/{commands,skills}`; in a company or person home they live flat under `agents/{commands,skills}` beside `docs/`. Commands and skills are the artifact kinds and are treated equally; subagent definitions are not an artifact class. Global commands are partitioned by the domains the repository publishes, `general` included, under the same one-owner declaration that governs documentation domains; global skills are the mother's alone, and global content outside a repository's declared reach fails validation.
- Authored sources and generated output never share a location. `.agents/` is a delivery location — the open project-local convention agent runtimes read — and is never an authored source root. A directory that is written by the platform is not also read as input.
- A machine-generated artifact reaches no further than the tier that produced it; promotion to a wider tier is a human act.

- **Agent artifacts are authored in-context on `main`, never routed through a todo.** Agent artifacts — commands and skills — are standalone agent-infrastructure plumbing; code never depends on their content, and couples to a command only where the platform dispatches it by name. What they should say is the human's decision; writing them is the agent's work, executed directly on `main` in the live session where that decision converged — never routed through a todo or the build lifecycle, never authored by a dispatched builder in a slug worktree. Human presence supplies context, not permission to edit: an original explicit authoring request, or agreement by every active participant followed by the human's release, opens the tracked write. Having no content for code to gate against, artifacts carry no pending markers and no `delivered_by`; after the complete artifact is stable, artifact distribution deploys it and the commits policy governs its commit.
- **A dispatched command retires with the delivery that removes its last dispatcher.** The command must exist while any dispatcher on `main` still names it, and must not outlive the delivery that removes the last one. Its retirement is therefore the one pending carrier an artifact takes: during that delivery's preparation, an empty companion `<name>.<slug>.md` is authored beside the command on `main`, naming the delivering slug, and the delivery fold deletes the command and the companion together. The command stays deployed until then. A new dispatched command needs no carrier: authored on `main` ahead of its dispatcher, it is inert until dispatched.
- Every `AGENTS.master.md` is inflated into an adjacent `AGENTS.md`, and that `AGENTS.md` is the only file generated beside a master. Artifact distribution inflates a project's masters. The home masters are a fixed set — the platform home's root master, the platform help desk's, each declared person's and company's root master, and each declared company help desk's — and are inflated when the home publishes, and again whenever the mother republishes the global documentation they inline; a master anywhere else in a home is not compiled. A home master produces its home's entrypoint from its own authored content and required reads; it receives no generated baseline index or activatable-procedure catalog.
- Every generated entrypoint — each `AGENTS.md` beside a master and each agent runtime's user-scope entrypoint — is fully inlined: every required read is expanded into it and no import survives in the runtime's import syntax outside code spans and fenced blocks. An unsupported import fails the build; it is never left for the runtime to resolve, because an agent runtime reading `AGENTS.md` directly resolves an import outside its working directory only under an approval it may never have been given.

<!-- planned-change:help-desks-as-deployment-output -->

- Master files are thin wrappers. Their only authored contents are `## Purpose` and `## Required reads`. Only the repository-root `AGENTS.master.md` produces the project entrypoint and receives the generated project baseline index and project activatable-procedure catalog. A nested master produces a directory-local entrypoint from its own authored content and required reads; it never inherits project-wide baseline material. They are never a knowledge home — all knowledge lives in doc snippets under `docs/`, and developer-experience prose lives in the README. A contract, procedure, architecture note, or operational note authored into a master file is a defect to be relocated to its rightful snippet.
- A master installed from a TeleClaude template — the platform home's, each person and company home's, and each help desk's — is that template's rendering. Installation or the home's initialization brings it back to the template whenever it differs, so an edit made in place does not last: the wording changes in the template, and what one home needs to know goes into that home's documentation, which its master requires through the home's local baseline. Installation leaves an edit nobody has recorded yet in place and reports it, and restores the template on the first installation after that edit is recorded or discarded. The local baseline manifests a template creates are the home's own after creation and are never overwritten.
- A help desk's master requires only documentation every reader of that desk may read. Inflation expands a required read without regard to `visibility`, so the master of a desk that serves people outside its home never requires the home's local documentation; such readers reach a home's documentation through `telec docs`, at the depth their relationship grants.

<!-- change:help-desks-as-deployment-output -->

- Master files are thin wrappers. Their only authored contents are `## Purpose` and `## Required reads`. Only the repository-root `AGENTS.master.md` produces the project entrypoint and receives the generated project baseline index and project activatable-procedure catalog. A nested master produces a directory-local entrypoint from its own authored content and required reads; it never inherits project-wide baseline material. They are never a knowledge home — all knowledge lives in doc snippets under `docs/`, and developer-experience prose lives in the README. A contract, procedure, architecture note, or operational note authored into a master file is a defect to be relocated to its rightful snippet.
- A master installed from a TeleClaude template — the platform home's, each person and company home's, and each help desk's — is that template's rendering and deployment output: its repository ignores it and never records it. Convergence, at commit-boundary maintenance and in `telec sync`, brings it back to the template whenever it differs, so an edit made in place does not last: the wording changes in the template, and what one home needs to know goes into that home's documentation, which its master requires through the home's local baseline. The local baseline manifests a template creates are the home's own after creation and are never overwritten.
- A help desk's master requires only documentation every reader of that desk may read. Inflation expands a required read without regard to `visibility`, so the master of a desk that serves people outside its home never requires the home's local documentation; such readers reach a home's documentation through `telec docs`, at the depth their relationship grants.

<!-- /planned-change:help-desks-as-deployment-output -->

- Master files are locked against unprompted edits: an agent never edits a master file on its own initiative or as a side effect of other work — only when the human raises the change in the session, and then the agent makes the edit. The lock guards the wrapper against accreting knowledge; it does not route typing to the human. It is declared by a `LOCKED_FILE` sentinel at the top and bottom of each master file.
- No `CLAUDE.md` is generated beside a master. Claude Code reads the generated `AGENTS.md` directly, alongside any `CLAUDE.md` in its directory or above, under the project-instructions setting that TeleClaude's deployed Claude user settings carry. A `CLAUDE.md` in a repository is that repository's own authored file and artifact distribution never writes it; the one exception is removal: an untracked `CLAUDE.md` — tracked neither at the published commit nor in the repository's current `HEAD`, and absent from its index — beside a master, whose entire content is the pointer import of `AGENTS.md`, is a leftover generated file, and distribution deletes it.
- Generated outputs under `dist/` are build artifacts. Do not edit them directly.

- Generated entrypoints are build outputs — never edit them directly. They are the `AGENTS.md` beside each master and each agent runtime's user-scope entrypoint in its deployed runtime directory; Claude Code's is `~/.claude/CLAUDE.md`, because that is the only name under which it reads user-scope instructions. Author the source artifacts; new instruction text belongs in a source addendum, never in a generated file.
- Deployed runtime directories (`~/.claude/`, `~/.codex/`, `~/.gemini/`) are also build outputs — never create or edit files there directly. Always author in source. This applies to any future agent runtime: `~/.{agent}/` directories are always deployment targets, never sources.
- Documentation indexes (for example `docs/index.yaml` and baseline index blocks in generated `AGENTS.md`) are generated by the index build; do not hand-edit them.

- Inline references are expanded for Claude, Codex, and Gemini outputs.
- Frontmatter is preserved by default; `hooks` are only emitted for Claude outputs.
- Every skill entrypoint keeps a small universal identity contract: `SKILL.md`
  must declare non-empty `name` and `description` frontmatter, and `name` must
  equal the containing folder. Supporting Markdown remains package content and
  is not graded against TeleClaude's artifact taxonomy.
- **Quality-defining configuration is governed content: never weakened by its own author's session.** Type-checker configuration (mypy/pyright sections, tsconfig strictness flags), linter rule selections and ignore lists, suppression baselines, and the sources of the quality guardrails lane define the floor every other change is measured against. An agent never relaxes them — removing a rule, adding an ignore or suppression key, disabling an error category, widening an exemption, excluding a first-party module — except through independent deep review: a separate reviewer session with no stake in the work the relaxation would unblock, which explicitly approves that specific relaxation on its merits. The session whose work is blocked by a quality wall never approves moving that wall. Tightening is always permitted without review. Exemption: third-party accommodation stanzas whose module pattern targets code outside the project's own package(s); an override stanza targeting first-party modules is a relaxation and is governed.

## Rationale

<!-- planned-change:help-desks-as-deployment-output -->

- Treating artifacts uniformly avoids cherry-picking and missing capabilities.
- Agent artifacts govern agents and no code depends on their content, so authoring them on `main` in the session that motivated them keeps their language and intent intact — dispatching them through a todo hands them to a worker that never heard the exchange, which loses the meaning in translation, and with no code delivery there is nothing for a todo to carry.
- Deciding what an artifact should say, releasing that decision for authoring, and writing it are distinct acts. The human holds the first two; the agent performs the mechanical write. Human presence preserves the live design context but never collapses those acts into one.
- Inflating master files keeps agent runtimes in sync while keeping source files stable.
- One generated entrypoint per directory serves every agent runtime. A per-runtime companion is a second generated file that can drift from the first, and for Claude Code any `CLAUDE.md` in a directory or above it would otherwise stop `AGENTS.md` from loading at all; the both-files setting, honoured only in user settings, removes that shadowing without asking any repository to give up its own `CLAUDE.md`. Only a leftover generated pointer is removed, because any other `CLAUDE.md` may carry its owner's words.
- A home entrypoint inlines documentation the mother publishes. Recompiling it when the mother republishes keeps every home session on the current bundle instead of the one in force at the home's last commit.
- Thin, locked wrappers keep knowledge in its rightful home (snippets) and the master file from accreting a parallel, drifting manual.
- One template serves every home of its kind, so a converged master keeps every such home on the same current wrapper, while the knowledge that differs per home lives in documentation that installation never touches. A baseline is where a home curates that knowledge, so after its creation it belongs to the home.
- An unrecorded edit exists nowhere but the working tree. Overwriting it destroys work the history never saw; leaving it for its author keeps the edit recoverable, and convergence still wins once the edit is recorded.
- An inlined required read reaches every reader of the entrypoint whole. Documentation depth for outside readers is enforced where it is read, not where a master was compiled.
- Limiting `hooks` to Claude matches current agent capabilities and avoids invalid configs.
- Quality configuration is the wall agent work is measured against; under goal pressure, any checker its own subject can edit gets edited toward green, one defensible commit message at a time. Governing the wall's definition places it outside the constrained author's unilateral reach.

<!-- change:help-desks-as-deployment-output -->

- Treating artifacts uniformly avoids cherry-picking and missing capabilities.
- Agent artifacts govern agents and no code depends on their content, so authoring them on `main` in the session that motivated them keeps their language and intent intact — dispatching them through a todo hands them to a worker that never heard the exchange, which loses the meaning in translation, and with no code delivery there is nothing for a todo to carry.
- Deciding what an artifact should say, releasing that decision for authoring, and writing it are distinct acts. The human holds the first two; the agent performs the mechanical write. Human presence preserves the live design context but never collapses those acts into one.
- Inflating master files keeps agent runtimes in sync while keeping source files stable.
- One generated entrypoint per directory serves every agent runtime. A per-runtime companion is a second generated file that can drift from the first, and for Claude Code any `CLAUDE.md` in a directory or above it would otherwise stop `AGENTS.md` from loading at all; the both-files setting, honoured only in user settings, removes that shadowing without asking any repository to give up its own `CLAUDE.md`. Only a leftover generated pointer is removed, because any other `CLAUDE.md` may carry its owner's words.
- A home entrypoint inlines documentation the mother publishes. Recompiling it when the mother republishes keeps every home session on the current bundle instead of the one in force at the home's last commit.
- Thin, locked wrappers keep knowledge in its rightful home (snippets) and the master file from accreting a parallel, drifting manual.
- One template serves every home of its kind, so a converged master keeps every such home on the same current wrapper, while the knowledge that differs per home lives in documentation that convergence never touches. A baseline is where a home curates that knowledge, so after its creation it belongs to the home.
- A template rendering holds nothing its template does not already hold, so no history records it and no edit made in place is worth keeping: what one home needs to know lives in that home's documentation. Keeping renderings out of every repository leaves convergence nothing to weigh against an author's work, and keeps a rendering from passing for authored content.
- An inlined required read reaches every reader of the entrypoint whole. Documentation depth for outside readers is enforced where it is read, not where a master was compiled.
- Limiting `hooks` to Claude matches current agent capabilities and avoids invalid configs.
- Quality configuration is the wall agent work is measured against; under goal pressure, any checker its own subject can edit gets edited toward green, one defensible commit message at a time. Governing the wall's definition places it outside the constrained author's unilateral reach.

<!-- /planned-change:help-desks-as-deployment-output -->

- A dispatched command is coupled to code in one direction only: its removal. Deleted on `main` before its last dispatcher is delivered, it breaks the dispatch still live there; deleted by hand afterwards, it has no owner once the preparing session ends. The fold that delivers the dispatcher's removal is the only act that reaches exactly that moment, so the removal rides it.

- Reading authored input from a directory the platform also writes makes a file's provenance unreadable from its location: an author cannot tell their own work from generated output, and a regenerating deploy is free to overwrite something a human wrote. Keeping the source root out of every delivery location is what makes that class of loss unrepresentable rather than merely avoided by convention.

## Scope

- Applies to every project that adopts TeleClaude artifact generation and distribution.

## Enforcement

- Distribution runs validate normalized authored commands before output.
  Every skill entrypoint is identity-validated; skill bodies are never graded
  against TeleClaude's artifact taxonomy. Supporting Markdown under either skill
  scope retains its authored structure.
- Generated files under `dist/` and deployed runtime directories are overwritten on each distribution run.
- A master file containing anything beyond `## Purpose` and `## Required reads` is a defect; relocate the content to a snippet or the README.
- A nested generated `AGENTS.md` containing the project baseline index or project activatable-procedure catalog is a defect; only the repository-root generated entrypoint may carry those project-wide sections.
- A commit that loosens quality configuration without a recorded independent approval is a violation. Reviewers treat maintenance framing of such diffs — "cleanup", "chore", "relax for now" — as the signature of erosion, not as mitigation.

## Exceptions

- None.

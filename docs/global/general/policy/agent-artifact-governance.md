---
description: 'Governance for agent-artifact sources, transforms, and ownership: master files are locked thin wrappers, generated entrypoints and runtime homes are never edited, knowledge lives in snippets.'
visibility: 'public'
---

# Agent Artifact Governance — Policy

## Rules

- Agent artifacts carry the same tier shape documentation has. In a repository they live under `agents/{global,local}/skills`; in a company or person home they live flat under `agents/skills` beside `docs/`. Skills are the one artifact kind; subagent definitions are not an artifact class, and what an agent is assigned at session start is a procedure, never an artifact. Global skills are the mother's alone, and global content outside a repository's declared reach fails validation.

- Authored sources and generated output never share a location. `.agents/` is a delivery location — the open project-local convention agent runtimes read — and is never an authored source root. A directory that is written by the platform is not also read as input.
- A machine-generated artifact reaches no further than the tier that produced it; promotion to a wider tier is a human act.

- **Agent artifacts are authored in-context on `main`, never routed through a todo.** Skills are standalone agent-infrastructure plumbing; code never depends on their content. What they should say is the human's decision; writing them is the agent's work, executed directly on `main` in the live session where that decision converged — never routed through a todo or the build lifecycle, never authored by a dispatched builder in a slug worktree. Human presence supplies context, not permission to edit: an original explicit authoring request, or agreement by every active participant followed by the human's release, opens the tracked write. Having no content for code to gate against, artifacts carry no pending markers and no `delivered_by`; after the complete artifact is stable, artifact distribution deploys it and the commits policy governs its commit.

- Every `AGENTS.master.md` is inflated into an adjacent `AGENTS.md`, and that `AGENTS.md` is the only file generated beside a master. Artifact distribution inflates a project's masters. The home masters are a fixed set — the platform home's root master, each declared person's and company's root master, and each declared company help desk's — and are inflated when the home publishes, and again whenever the mother republishes the global documentation they inline; a master anywhere else in a home is not compiled. A home master produces its home's entrypoint from its own authored content and required reads; it receives no generated baseline index or activatable-procedure catalog.

- Every generated entrypoint — each `AGENTS.md` beside a master and each agent runtime's user-scope entrypoint — is fully inlined: every required read is expanded into it and no import survives in the runtime's import syntax outside code spans and fenced blocks. An unsupported import fails the build; it is never left for the runtime to resolve, because an agent runtime reading `AGENTS.md` directly resolves an import outside its working directory only under an approval it may never have been given.

- Master files are thin wrappers. Their only authored contents are `## Purpose` and `## Required reads`. Only the repository-root `AGENTS.master.md` produces the project entrypoint and receives the generated project baseline index and project activatable-procedure catalog. A nested master produces a directory-local entrypoint from its own authored content and required reads; it never inherits project-wide baseline material. They are never a knowledge home — all knowledge lives in doc snippets under `docs/`, and developer-experience prose lives in the README. A contract, procedure, architecture note, or operational note authored into a master file is a defect to be relocated to its rightful snippet.

- Every master is its home's own source, recorded by its repository's history. A TeleClaude template seeds a person or company home's master and a company or project help desk's master only while it is absent, and nothing rewrites an existing one. The TeleClaude home's root master has no template and is authored in the home. What one home needs to know goes into that home's documentation, which its master requires through the home's local baseline. The local baseline manifests a template creates are the home's own after creation and are never overwritten.

- A help desk's master requires only the help-desk concept and procedures. Inflation expands a required read whole and without regard to `visibility`, so every other documentation reaches a desk's visitor through `telec docs`, at the depth their relationship grants.

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

- Treating artifacts uniformly avoids cherry-picking and missing capabilities.
- Agent artifacts govern agents and no code depends on their content, so authoring them on `main` in the session that motivated them keeps their language and intent intact — dispatching them through a todo hands them to a worker that never heard the exchange, which loses the meaning in translation, and with no code delivery there is nothing for a todo to carry.
- Deciding what an artifact should say, releasing that decision for authoring, and writing it are distinct acts. The human holds the first two; the agent performs the mechanical write. Human presence preserves the live design context but never collapses those acts into one.
- Inflating master files keeps agent runtimes in sync while keeping source files stable.
- One generated entrypoint per directory serves every agent runtime. A per-runtime companion is a second generated file that can drift from the first, and for Claude Code any `CLAUDE.md` in a directory or above it would otherwise stop `AGENTS.md` from loading at all; the both-files setting, honoured only in user settings, removes that shadowing without asking any repository to give up its own `CLAUDE.md`. Only a leftover generated pointer is removed, because any other `CLAUDE.md` may carry its owner's words.
- A home entrypoint inlines documentation the mother publishes. Recompiling it when the mother republishes keeps every home session on the current bundle instead of the one in force at the home's last commit.
- Thin, locked wrappers keep knowledge in its rightful home (snippets) and the master file from accreting a parallel, drifting manual.
- A master's required reads depend on what its home publishes, so a seeded master is that home's source. Rewriting it from a template would erase the home's choices, and a master no history records would reach publication as a file nobody reviewed. A baseline is where a home curates its knowledge, so after its creation it belongs to the home.
- An inlined required read reaches every reader of the entrypoint whole. Documentation depth for outside readers is enforced where it is read, not where a master was compiled, so a desk inlines nothing beyond how to work as a desk.
- Limiting `hooks` to Claude matches current agent capabilities and avoids invalid configs.
- Quality configuration is the wall agent work is measured against; under goal pressure, any checker its own subject can edit gets edited toward green, one defensible commit message at a time. Governing the wall's definition places it outside the constrained author's unilateral reach.

- What a session is assigned is a procedure, which is documentation: it carries pending markers, a delivering slug and independent review like any contract, which is why no artifact kind exists for it.

- Reading authored input from a directory the platform also writes makes a file's provenance unreadable from its location: an author cannot tell their own work from generated output, and a regenerating deploy is free to overwrite something a human wrote. Keeping the source root out of every delivery location is what makes that class of loss unrepresentable rather than merely avoided by convention.

## Scope

- Applies to every project that adopts TeleClaude artifact generation and distribution.

## Enforcement

- Every skill entrypoint is identity-validated; skill bodies are never graded
  against TeleClaude's artifact taxonomy. Supporting Markdown under either skill
  scope retains its authored structure.

- Generated files under `dist/` and deployed runtime directories are overwritten on each distribution run.
- A master file containing anything beyond `## Purpose` and `## Required reads` is a defect; relocate the content to a snippet or the README.
- A nested generated `AGENTS.md` containing the project baseline index or project activatable-procedure catalog is a defect; only the repository-root generated entrypoint may carry those project-wide sections.
- A commit that loosens quality configuration without a recorded independent approval is a violation. Reviewers treat maintenance framing of such diffs — "cleanup", "chore", "relax for now" — as the signature of erosion, not as mitigation.

## Exceptions

- None.

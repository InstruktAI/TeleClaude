---
id: project/spec/domain/agent_artifacts
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-agent-artifacts, v2-agent-artifacts-cutover]
description: Agent Artifacts bounded context — source manifest, inflation rules, and distribution of agent-facing deliverables (commands, skills, addenda, manifests) to deployed agent runtime directories.
---

# Agent Artifacts Domain Spec — Spec

## Required reads

- @docs/global/software-development/principle/domain-driven-design.md
- @docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `agent_artifacts` bounded context owns the build-and-distribute pipeline for agent-facing deliverables. It reads the artifact source manifest (under `agents/` for global and `.agents/` for project-local), applies inflation rules (e.g., `AGENTS.master.md` → `AGENTS.md` with inlined references), and distributes the deployed output to each supported agent's runtime directory (`~/.claude/`, `~/.codex/`, `~/.gemini/`).

This context is filesystem-driven — there is no Postgres schema. Source lives in git under `agents/` and `.agents/`; build outputs land in `dist/`; deployed runtime files live under `~/.<agent>/`. Coordination with `integration` happens via filesystem-mediated hook configs: agent_artifacts deploys the configs that tell agent CLIs WHEN to invoke `telec-hook`; integration owns what happens when the invocation arrives.

This context does NOT own: the authored artifact CONTENT itself (it's checked into git under `agents/`), knowledge retrieval policy (`knowledge`), workflow state (`workflow`), session runtime (`agent_runtime`).

## Canonical fields

### Ubiquitous language

**Agent artifact** (per glossary)
:  A deployable file or directory under `agents/` that defines an agent's behavior. Four canonical kinds: `command`, `skill`, `addendum`, `manifest`.

**Slash command**
:  An agent artifact of kind `command`. A markdown file under `commands/` defining a slash invocation for an agent CLI (e.g., `/next-prepare`). Distributed to `~/.claude/commands/`, `~/.codex/commands/`, etc.

**Skill**
:  An agent artifact of kind `skill`. Invocable capability with structured input/output. Distributed to the agent's skills directory.

**Addendum**
:  An agent artifact of kind `addendum`. A per-agent behavioral shim (`agents/{AGENT}.addendum.md`) targeted at correcting agent-specific failure modes. Inflated into the agent's `AGENTS.md` deployment.

**Manifest**
:  An agent artifact of kind `manifest`. The `AGENTS.master.md` source that gets inflated into the deployed `AGENTS.md`. Contains structure + references; inflation expands references and applies addenda.

**Inflation**
:  The process of transforming a manifest source (`AGENTS.master.md`) into a deployed `AGENTS.md`. Expands inline `@`-references, applies frontmatter, conditionally emits `hooks` (Claude only). Per-agent inflation may produce different outputs.

**Distribution**
:  The act of writing the inflated artifacts to deployed runtime directories. Idempotent: running `telec sync` again produces byte-identical output if sources unchanged.

**Source root**
:  The directory containing artifact sources. Two scopes: `agents/` (global, TeleClaude mother project only) and `.agents/` (project-local).

**Deployed runtime directory**
:  The home-directory location each agent CLI reads at startup: `~/.claude/`, `~/.codex/`, `~/.gemini/`. ALWAYS a deployment target, NEVER a source. Direct edits there are defects.

**Mother project**
:  The TeleClaude repo itself, the only repo allowed to publish global artifacts from `agents/`. Other projects use `.agents/` for project-local artifacts.

**Hook config**
:  A configuration entry in an agent CLI's settings (e.g., `~/.claude/settings.json:hooks`) that wires the agent CLI to invoke `telec-hook` on specific events. Authored under `agents/` or `.agents/`; deployed by agent_artifacts; consumed by `integration` when the agent CLI fires the hook.

### Aggregates

#### Artifact Source (aggregate)

- **Root:** `ArtifactSource`
- **Contains:** the source file path (under `agents/` or `.agents/`); kind (`command` | `skill` | `addendum` | `manifest`); scope (`global` | `project`); target agents (which agent CLIs this artifact applies to — `all` or a subset).
- **Invariants:**
  - Source files live in git under `agents/` or `.agents/` only. Files under `~/.<agent>/` or `dist/` are NEVER sources.
  - Global artifacts may be published only from the TeleClaude mother project (`agents/` in this repo). Other projects with `agents/` content fail validation.
  - Project-local artifacts live under `.agents/` and apply to the project they're authored in.
  - Each source artifact has a clear kind; mixed-kind files are defects.
  - Hooks frontmatter is preserved in source but only emitted for Claude in deployed output.
- **Identifier:** absolute source path relative to repo root.
- **Lifecycle:** Created by hand-authoring (or by future scaffolding tools). Deleted by removing the file from git. Mutation = git commit on the source.

#### Deployed Artifact (aggregate)

- **Root:** `DeployedArtifact`
- **Contains:** target agent (which agent CLI); deployment path (under `~/.<agent>/`); inflated content; the source it was inflated from.
- **Invariants:**
  - Every deployed artifact has exactly one source.
  - Re-running `telec sync` produces byte-identical content for the same source.
  - The deployed artifact's existence implies a successful sync; a missing deployed artifact for a known source means sync hasn't run since the source was added.
  - Deployed artifacts under `~/.<agent>/` are owned exclusively by agent_artifacts. External edits will be overwritten.
- **Identifier:** `(target_agent, deployment_path)`.
- **Lifecycle:** Created/updated on each `telec sync`. Removed when the source is removed AND the next sync runs.

#### Project Manifest (aggregate)

- **Root:** `ProjectManifest` (one per machine: `~/.teleclaude/projects.yaml`)
- **Contains:** the registered list of projects, each with: project path, project name, optional company association.
- **Invariants:**
  - One project entry per absolute path; no duplicates.
  - Project entries are added by `telec projects init`; removed by explicit operator action.
  - The manifest is mutated by sync as a side effect of project registration.
- **Identifier:** the file path `~/.teleclaude/projects.yaml`.
- **Lifecycle:** Created on first `telec projects init`. Mutated by subsequent init / sync runs.

### Domain events emitted

#### `agent_artifacts.synced`

- **Producer:** `agent_artifacts`
- **Emitted when:** `telec sync` completes successfully for a given scope (project + machine).
- **Payload:** `project_path`, `target_agents` (list), `sources_count`, `deployed_count`, `synced_at`, `triggered_by_principal`.
- **Visibility:** CLUSTER
- **Known consumers:** `integration` (refreshes its view of which hook configs are deployed, for diagnostics); `workflow` (potentially: if sync was triggered by a delivery, the delivery's todo is informed).
- **Idempotency key:** `(project_path, synced_at)`.
- **Posture:** `commit-then-emit`.

### Domain events consumed

#### `workflow.todo.delivered`

- **Producer:** `workflow`
- **Reaction:** if the delivered todo touched files under `agents/` or `.agents/`, agent_artifacts MAY auto-trigger a `telec sync` to propagate the change. Whether auto-sync fires is config-driven (default: no auto-sync; humans run sync explicitly).
- **Failure handling:** sync failures are logged; the delivery is not rolled back; operator may run sync manually.

### Use cases

#### UC-ART-1: Author a new global slash command

```
Given the operator is in the TeleClaude mother project
And creates a new file at agents/commands/foo.md following the slash-command schema
When the operator runs `telec sync`
Then agent_artifacts validates the source against the agent-artifact schema
And inflates the source for each target agent (Claude, Codex, Gemini)
And writes the deployed artifacts under ~/.claude/commands/foo.md, ~/.codex/commands/foo.md, ~/.gemini/commands/foo.md
And emits agent_artifacts.synced
And the slash command becomes available in every agent CLI on next session start
```

#### UC-ART-2: Inflate a manifest with addenda

```
Given agents/AGENTS.master.md exists as the canonical source
And agents/CLAUDE.addendum.md and agents/CODEX.addendum.md exist
When `telec sync` runs
Then for the Claude target, agent_artifacts inflates AGENTS.master.md applying the CLAUDE addendum + hooks frontmatter
And writes ~/.claude/AGENTS.md
And for the Codex target, applies the CODEX addendum (no hooks)
And writes ~/.codex/AGENTS.md
And produces a CLAUDE.md companion with single-line `@./AGENTS.md` content
```

#### UC-ART-3: Project-local artifact override

```
Given a project has .agents/commands/project-special.md (project-local)
And the same project also receives global artifacts from `agents/`
When `telec sync` runs in that project's context
Then agent_artifacts applies global artifacts first
And applies project-local artifacts second (overriding global on name collision)
And the deployed output reflects the merged set
```

#### UC-ART-4: Reject unauthorized global artifact publication

```
Given a non-mother project has files under its `agents/` directory
When `telec sync` runs
Then agent_artifacts rejects the operation with an error
And the message explains that only the TeleClaude mother project may publish global artifacts
And the operator is directed to move the files to `.agents/` if they're project-local
```

#### UC-ART-5: Deploy hook configs that wire integration

```
Given agents/CLAUDE.addendum.md includes a hooks frontmatter block specifying pre-tool-use hook on telec-hook
When sync runs for the Claude target
Then the deployed ~/.claude/settings.json gets the hook config wired
And the next time Claude fires a pre-tool-use event, it invokes telec-hook
And telec-hook reads stdin and emits an integration.inbox.agent_hook_received event
```

#### UC-ART-6: Idempotent re-sync

```
Given the agent artifact sources are unchanged since the last successful sync
When `telec sync` runs again
Then the deployed output is byte-identical
And agent_artifacts.synced still fires (operators want to know sync ran)
And no spurious git diff appears anywhere
```

#### UC-ART-7: Project registration as a sync side effect

```
Given `telec projects init` runs in a new project directory
When the init pipeline reaches the sync step
Then agent_artifacts adds the project to ~/.teleclaude/projects.yaml
And performs first sync for that project
And emits agent_artifacts.synced
```

### Context map position

- **Reads from `config`** — target agents to deploy to, per-machine project list.
- **Reads from `identity`** (via principal context for the triggering caller, mostly informational).
- **Conformist via filesystem to `integration`** — deploys hook configs that integration's `telec-hook` binary later consumes. The handshake is the agent CLI's invocation of `telec-hook`; agent_artifacts only writes the config, doesn't talk to integration directly.
- **No upstream domain context** for sync logic itself.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/sync.py` (~172 lines) + `teleclaude/install/configure_agent_cli.py` plus install scripts handle this work today. The v2 ACL is small (the v1 code becomes a thin shim calling v2 inflation logic). Disappears at `v2-agent-artifacts-cutover`.

## Allowed values

- `artifact kind`: `command`, `skill`, `addendum`, `manifest`.
- `artifact scope`: `global` (TeleClaude mother project only), `project` (any project, under `.agents/`).
- `target agent`: `claude`, `codex`, `gemini` (extensible).
- `deployed runtime directory`: `~/.claude/`, `~/.codex/`, `~/.gemini/` (any future `~/.<agent>/`).

## Known caveats

- **Filesystem-driven, no Postgres schema.** All state survives in git (sources) + filesystem (deployed). If inflation caching becomes expensive enough, that cache goes in Redis or `.cache/` on disk — NOT Postgres.
- **`dist/` is generated.** Build outputs land there during sync. Never hand-edited. The `.gitignore` keeps `dist/` out of git in most cases.
- **Generated indexes (`docs/index.yaml`, AGENTS.md baseline blocks) are toolchain outputs.** Per `Commits` policy: `telec sync` is the only thing that writes them; they ARE committed because consumers depend on them.
- **No agent may write directly to `~/.<agent>/`.** All output goes through `telec sync`. Direct writes will be overwritten silently and create confusion.
- **Hooks frontmatter is Claude-only in deployed output.** Codex and Gemini don't have the same hooks surface. Source files may include hooks; inflation strips them for non-Claude targets.
- **No new artifact kinds without schema update.** The four kinds are deliberate; adding a new kind requires schema + inflation logic + distribution logic in coordination.
- **Cross-runtime deployment formats are deferred.** If a future runtime needs a different deployment shape (e.g., a JSON manifest instead of `AGENTS.md`), that's a new artifact kind, not a hidden conditional in the existing pipeline.
- **The mother-project gate is enforced.** Global artifact publishing is a per-repo decision (this repo is the publisher; others consume). Any project trying to publish globals from `agents/` is rejected.

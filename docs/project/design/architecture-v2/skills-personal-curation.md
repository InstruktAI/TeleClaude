---
id: project/design/architecture-v2/skills-personal-curation
type: design
domain: software-development
scope: project
visibility: public
delivered_by: [skills-personal-curation]
description: Forward-looking architectural design for per-human skill curation — pulling vetted external skill libraries via the git-ingestion primitive, detecting per-human skill need from accumulated memory, associating skills per-human, and injecting per-human skill manifests at session-start. Built on top of the v2 platform; not part of the v2 cutover scope.
---

# Skills — Personal Curation — Design

## Required reads

- @docs/project/spec/domain/memory.md
- @~/.teleclaude/docs/general/procedure/git-repo-ingestion.md

## Purpose

Give multi-tenant platform users (members, customers, contributors) per-human skill loadouts without inheriting the failure modes of agent-CLI native skill systems (account-bound, project-or-global-only, no per-human axis). Skills are sourced from trusted external libraries (vetted, security-reviewed, community-tested), not authored internally. Per-human associations live in memory; the session-start hook reads them and injects a per-human manifest pointing the agent at the relevant skill files on disk.

This design builds on top of the v2 platform — Postgres-backed memory, mirror-based provenance, session-start injection — and is therefore deliberately _not_ part of the v2 cutover scope. It is the next layer.

## Inputs/Outputs

**Inputs:**

- Accumulated `(human, ...)` triples in the memory pillar. The substrate from which "this human would benefit from skill X" is inferred.
- A curated registry of trusted external skill libraries (GitHub repositories the operator has approved as vetted sources).
- A session-start event for a known human (email or identity-context string resolves the subject).

**Outputs:**

- Per-human skill associations stored as memory triples (or equivalent structured records) declaring "this human prefers skill X from library Y."
- A session-start context injection that hands the agent a manifest of paths into `~/.teleclaude/git/<host>/<owner>/<repo>/...` along with activation hints, so the agent can `Read` the skill file on-demand when its trigger fires.

## Invariants

- **External-only by default.** Skills are pulled from approved external libraries via the existing `git-repo-ingestion` procedure. Internal skill authoring is not a primary path.
- **No native-CLI skill mechanism dependency.** The agent CLIs' built-in skill systems are account/project/global-scoped; this design routes around them entirely by injecting context manifests at session-start.
- **Per-human associations are revocable.** Removing a `(human, ...)` skill association immediately stops the next session-start injection from including it.
- **Curation is human-approved.** No automatic promotion. A Tier-2 process surfaces candidate skill associations; a human or operator approves before the association becomes live.

## Primary flows

### Flow 1 — Library acquisition

1. Operator identifies a trusted external skill library (e.g., a GitHub repo).
2. `git-repo-ingestion` procedure pulls the library to `~/.teleclaude/git/<host>/<owner>/<repo>/`.
3. The library is now available locally at a predictable path. Skill files within it (typically `skill.md` or similar) can be referenced by their full path.

### Flow 2 — Skill-need detection (Tier 2, deferred internal design)

The Tier-2 process that detects skill need is not designed here. Open architectural questions (below) determine its data model and procedure. At a high level: it reads accumulated human-category memory for a given human, looks for indicators that a particular skill would be relevant, and surfaces candidate associations for approval.

### Flow 3 — Per-human association

When a skill-need-detection candidate is approved:

1. The association is recorded — either as a memory triple of some shape, or in a dedicated `human_skill_associations` table, or another mechanism the v2.x design lands on.
2. The association persists across sessions for that human.

### Flow 4 — Session-start injection

When a session starts for a human with known skill associations:

1. The session-start hook resolves the human's identifier.
2. It queries the association store for that human's approved skills.
3. It builds a manifest: list of `(skill-path, activation-trigger, brief-description)` entries.
4. The manifest is injected into the agent's context at session-start.
5. When an activation trigger fires during the session, the agent reads the skill file from disk via the `Read` tool.

## Failure modes

**Operational failure modes:**

- **External library quality drift.** A trusted library degrades over time (maintenance lapses, security advisories). Mitigation: periodic library re-vetting; the curation registry must support deprecation.
- **Skill-need detection false positives.** The Tier-2 process recommends skills the human doesn't actually want. Mitigation: human-approval gate on every new association; easy revocation surface.
- **Session-start manifest bloat.** Too many skills associated to one human inflates session-start context. Mitigation: cap on active associations per human; explicit pruning workflow.
- **Library path drift.** A library is removed or relocated, breaking association paths. Mitigation: integrity check at session-start that verifies the skill files exist before injecting; broken references degrade gracefully (skip with warning) rather than crash.

**Unresolved-at-design-time failure modes** — these are open architectural questions whose answers will shape the eventual implementation; design will fail if they are not resolved before build:

- **Skill-need detection data shape.** What data does the Tier-2 detector consume to recommend skills? Pure memory triples? Tool-call traces? Something else entirely? The memory pillar's triple shape may not fit pattern-detection workloads cleanly.
- **Association storage.** Memory triples with a `prefers-skill` predicate, OR a dedicated `human_skill_associations` table, OR something else? Trade-off between paradigm uniformity and storage clarity.
- **Approval workflow.** Where does the human-approval gate sit operationally? Telegram DM? TUI surface? Web?
- **Activation trigger format.** How does the agent know when to fire a skill? The injected manifest needs a trigger description format that the agent can match against the current task.
- **Multi-tenant operational concerns.** Per-human disk paths, per-human session-start latency, registry-of-vetted-libraries authority and update model.

## See Also

- docs/project/spec/domain/memory.md
- ~/.teleclaude/docs/general/procedure/git-repo-ingestion.md
- docs/project/design/architecture-v2/services.md

# Discovery Brief: Event Platform + Mesh Architecture

**Date:** 2026-03-01
**Method:** Peer research — two Claude Sonnet 4.6 sessions + 4 subagents covering 11 todos in parallel
**Scope:** event-platform (parent + 6 sub-todos), mesh-architecture, mesh-trust-model, event-domain-pillars, event-alpha-container, event-mesh-distribution, integration-events-model, integrator-wiring

---

## Build Readiness Verdict

| Todo                        | DOR | Ready?        | Worst Gap                                              |
| --------------------------- | --- | ------------- | ------------------------------------------------------ |
| event-system-cartridges     | 8   | PARTIAL       | Trust truth table missing; re-entry loop risk          |
| event-domain-infrastructure | 8   | CONDITIONAL   | Member slug undefined; DAG cache absent                |
| event-signal-pipeline       | 8   | CONDITIONAL   | PipelineContext.ai_client uncontracted                 |
| event-envelope-schema       | 8   | CONDITIONAL   | extra="allow" breaks backward compat                   |
| event-domain-pillars        | 8   | PARTIAL       | Cartridge files not seeded by telec init               |
| mesh-trust-model            | 8   | CONDITIONAL   | peer_id format undefined until mesh-architecture ships |
| integrator-wiring           | 8   | CONDITIONAL   | branch_pushed contradiction (hard)                     |
| mesh-architecture           | 0   | **NO**        | Requirements + plan = blank templates; 3 todos blocked |
| event-alpha-container       | 0   | **NO**        | CLI collision + health-check ping bug + stale socket   |
| event-mesh-distribution     | 0   | **NO**        | PeerInfo.cluster missing in live code; cascade loop    |
| integration-events-model    | —   | **DELIVERED** | Empty directory — clean up                             |

---

## Combined Blockers (must resolve before build)

1. **Phase 1 reality mismatch** — `teleclaude_events/` already exists with pipeline, 2 cartridges, schemas, delivery. Plan describes from-scratch work. Revise scope before writing a line.

2. **Consolidation/cutover void** — 7 old notification paths must collapse; zero migration tasks exist. Risk: duplicate delivery or silent loss.

3. **External producers unwired** — `integrator-wiring`, `todo-dump-command`, `prepare-quality-runner` must emit events. No task in any todo actually wires them.

4. **PipelineContext underspecified** — signal cartridges assume `context.ai_client` and `context.emit`; domain-infrastructure is a separate todo with no ordering dep declared. The dataclass is the ground truth and it's lean.

5. **extra="allow" backward compat break** — envelope schema adds `_extra` JSON key. Old deserializers won't handle it. No migration path.

6. **mesh-architecture entirely empty** — requirements.md and implementation-plan.md are blank templates. Node identity, keypair lifecycle, receptor endpoint, DNS wire format, subscription protocol all undefined. Three todos blocked on it.

7. **PeerInfo.cluster missing in live code** — confirmed `teleclaude/core/models.py:115`. Cluster-scope forwarding in event-mesh-distribution is unbuildable without a non-trivial redis_transport change.

8. **`telec cartridges list` CLI collision** — event-alpha-container and event-mesh-distribution both define it with incompatible semantics.

9. **`cartridge.invoked` emission cascade** — CartridgePromotionTracker is itself a cartridge; processes its own invocation event → infinite loop.

10. **`branch_pushed` contradiction in integrator-wiring** — FR2 folds it into `deployment.started` payload; readiness predicate requires it as a separate event; FR1 forbids modifying integration internals. All three constraints can't coexist.

---

## Two Systemic Patterns (found independently by both agents)

1. **`PipelineContext` is the unacknowledged cross-todo contract surface.** Every todo that adds cartridges assumes fields (`ai_client`, `emit`, `cluster`) not in the dataclass. No todo owns the contract. Needs a formal spec before any cartridge todo builds.

2. **"Cluster" is under-designed platform-wide.** Appears in cartridge state (signal pipeline), PeerInfo (mesh distribution), config schema (mesh architecture), trust scoping (mesh-trust-model) — with zero consistent definition. One authoritative definition needed before any of these build.

---

## High-Severity Gaps (sample)

- Trust evaluator: no truth table; `known_sources` origin undefined
- Correlation re-entry: guard only covers `source="correlation"` — domain synthetic events loop freely
- `meaningful_fields` absent from `NotificationLifecycle` schema — transition reset logic is inert dead code
- `idempotency_fields` absent from `EventSchema` — deduplication never fires consistently
- Burst detection duplicated across system + signal cartridges with no coordination
- Cluster cartridge: stateless protocol but clustering requires accumulated state — DB-backed implied, unspecified
- Cartridge file seeding missing — `seed_event_domains()` never copies files to cartridge dirs
- Code-as-data + L3 auto-install: no signature verification, not listed as a risk
- Peer observation weighting in mesh-trust-model: no algorithm defined

---

## Immediate Actions Before Any Build

1. Write `mesh-architecture/requirements.md` — unblocks 3 todos and defines peer_id + cluster concept everything keys on
2. Revise `event-platform` Phase 1 scope against existing `teleclaude_events/` code
3. Define `PipelineContext` contract — formal spec of all fields, which todo adds them, in what order
4. Resolve 3 hard contradictions: `branch_pushed`, CLI collision, `cartridge.invoked` cascade
5. Add cutover plan for 7 old notification paths
6. Mark `integration-events-model` delivered — delete empty directory, update roadmap

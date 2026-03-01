# DOR Report: event-domain-pillars

## Gate Verdict: needs_work — Score 6/10

**Assessed at:** 2026-03-01T16:00:00Z
**Assessed by:** Architect (gate mode)

---

## Gate Results

### Gate 1: Intent & success — PASS

Problem statement is clear: four business domain pillars with event schemas, cartridges,
and domain config. Success criteria are 14 concrete, testable items. What/why captured
in `input.md` and `requirements.md`.

### Gate 2: Scope & size — PASS (marginal)

6 phases, ~19 tasks. Phases 2–5 are independent pattern repetitions of the same structure
(schema + cartridges + config). The plan notes parallelizability. Fits a single session
due to repetitive pattern, but is at the upper bound.

### Gate 3: Verification — PASS

Demo has 5 concrete Python assertion blocks against the catalog. Tests defined in Phase 6.
`make lint` + `make test` in success criteria.

### Gate 4: Approach known — PASS

Schema registration pattern is proven by 9 existing events in
`teleclaude_events/schemas/software_development.py`. Cartridge convention depends on
upstream types not yet built — the stub strategy in Task 1.1 is adequate.

### Gate 5: Research complete — PASS (auto-satisfied)

No third-party dependencies.

### Gate 6: Dependencies & preconditions — NEEDS_WORK

Two roadmap dependencies are unbuilt:
- `event-domain-infrastructure`: DOR needs_work (score 0), itself blocked by
  `event-system-cartridges` (DOR pass, build pending)
- `event-signal-pipeline`: DOR needs_work (score 0), blocked by infrastructure

The plan accounts for this with stubs (Task 1.1), which is good. However:
- The config key namespace is wrong. Infrastructure requirements specify `event_domains`
  to avoid collision with existing `BusinessConfig.domains: Dict[str, str]` at
  `teleclaude/config/schema.py:96`. The pillars plan uses `domains:` in all YAML examples
  (Task 1.3, 2.3, etc.), which would collide. Must use `event_domains`.
- `telec init` domain seeding mechanism is unspecified. The current `init_flow.py` has no
  domain config hook. Task 1.3 says "Wire into telec init" but doesn't describe how. This
  is a meaningful tooling change that needs a concrete approach.

### Gate 7: Integration safety — PASS

Pure content addition. Schema modules extend `register_all()`. No runtime changes to
existing code beyond `telec init` extension.

### Gate 8: Tooling impact — NEEDS_WORK

`telec init` changes are proposed but the implementation mechanism is not detailed. No
scaffolding procedure update mentioned.

---

## Plan-to-Requirement Contradictions (Blockers)

### 1. Wildcard event subscription in plan contradicts requirements constraint

**Requirements constraint:** "No wildcard event subscriptions — cartridge manifests declare
explicit `event_types`"

**Plan Task 2.2:** `todo-lifecycle/manifest.yaml` specifies
`event_types=[domain.software-development.planning.*]` — this is a wildcard.

**Fix:** Replace with explicit enumeration of the 6 planning event types:
`[domain.software-development.planning.todo_created, .todo_dumped, .todo_activated,
.artifact_changed, .dependency_resolved, .dor_assessed]`.

The same check should be applied to all other cartridge manifests to ensure no wildcards
appear anywhere in the plan.

### 2. Config namespace collision

**Infrastructure requirements** (upstream): `event_domains.{name}` namespace, explicitly
to avoid collision with `BusinessConfig.domains`.

**Pillars plan** Task 1.3 and all domain config examples: uses `domains:` as the top-level
key.

**Fix:** All config YAML blocks and references must use `event_domains:` as the namespace.
Update Task 1.3 seed data and Tasks 2.3, 3.3, 4.3, 5.3 config entries.

---

## Missing Coverage

### 3. Documentation task absent

Requirements scope includes "Documentation for each pillar's event taxonomy and cartridge
composition." The implementation plan has no documentation task. Either:
- Add a Phase 6 task for documentation, or
- Clarify that schema modules + manifest files serve as documentation (and update
  requirements to say so).

### 4. `telec init` seeding mechanism needs specification

Task 1.3 says "Wire into telec init so domain configs are seeded on project bootstrap" but
`teleclaude/project_setup/init_flow.py` has no domain config seeding step. The plan must
specify:
- Which function seeds domain config (new function in `init_flow.py`?).
- How config is merged (via `telec config patch` internally, or direct file write?).
- What happens if domains already exist in config (merge vs. overwrite).

---

## Open Questions (from draft, still unresolved)

1. **`event_types` field on CartridgeManifest:** This type doesn't exist yet. The
   infrastructure requirements describe cartridge manifests but the exact schema fields
   are defined in the implementation plan for `event-domain-infrastructure`, not this todo.
   The pillars plan should document the assumed manifest fields and validate once
   infrastructure ships.

2. **Cross-domain pattern for signal→marketing bridge:** Marketing's `feed-monitor`
   cartridge subscribes to `signal.synthesis.ready` (signal pipeline) and maps to
   `domain.marketing.feed.synthesis_ready`. This cross-domain bridging pattern is not
   formalized in any upstream design. Document it as an assumed pattern.

---

## Actions Required Before Pass

| # | Fix | Severity |
|---|-----|----------|
| 1 | Replace wildcard `planning.*` with explicit event type list in Task 2.2 manifest | Blocker |
| 2 | Change config namespace from `domains:` to `event_domains:` across all YAML blocks | Blocker |
| 3 | Add documentation task or clarify documentation scope in requirements | Minor |
| 4 | Specify `telec init` seeding mechanism in Task 1.3 | Blocker |
| 5 | Document assumed CartridgeManifest fields used in manifest YAMLs | Minor |
| 6 | Document cross-domain signal→marketing bridging pattern | Minor |

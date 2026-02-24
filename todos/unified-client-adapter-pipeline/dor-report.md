# DOR Report — unified-client-adapter-pipeline (Gate)

## Final Verdict

- status: `needs_work`
- score: `7/10`
- assessed_at: `2026-02-24T15:55:57Z`

## Gate-by-Gate Assessment

1. **Intent & success**: pass
   - Problem, goal, and measurable acceptance criteria are explicit in `requirements.md`.
2. **Scope & size**: **needs work**
   - The todo currently bundles multiple substantial phases (contract definition, Web migration, TUI migration, ingress harmonization, migration/cutover, full validation).
   - Per Definition of Ready, this should be split into smaller dependent todos before build dispatch.
3. **Verification**: pass
   - Verification path includes concrete automated commands in `demo.md`.
   - Plan includes unit/integration coverage and observability checks.
4. **Approach known**: pass
   - Technical direction is grounded in existing project references:
     - `docs/project/design/architecture/agent-activity-streaming-target.md`
     - `docs/project/spec/session-output-routing.md`
     - `docs/project/policy/adapter-boundaries.md`
5. **Research complete (when applicable)**: pass
   - No new third-party integration is introduced by this todo.
6. **Dependencies & preconditions**: pass
   - Dependency is explicitly modeled in `todos/roadmap.yaml` (`after: transcript-first-output-and-hook-backpressure`).
7. **Integration safety**: pass
   - Plan includes migration/cutover controls and rollback documentation expectations.
8. **Tooling impact (if applicable)**: pass
   - No scaffolding/tooling contract changes are required in this todo.

## Plan-to-Requirement Fidelity

- `implementation-plan.md` includes explicit phase-to-requirement traceability.
- No plan task currently contradicts requirements.
- Gate blocker is size/splitting, not fidelity.

## Blockers (Must Resolve for Ready)

1. Split this todo into smaller dependent todos so each item is atomic and feasible for a single implementation session.

## Required Remediation

1. Create follow-up slugs in `todos/roadmap.yaml` (for example: outbound contract, Web alignment, TUI alignment, ingress harmonization/cutover).
2. Move phase-specific scope and acceptance checks into those slugs and keep this parent slug as umbrella-only (or close it in favor of the split set).
3. Re-run gate after split artifacts exist and dependency edges are explicit.

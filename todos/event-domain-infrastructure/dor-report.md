# DOR Report: event-domain-infrastructure

## Assessment Date

2026-03-01 (draft)

## Gate Status

**NEEDS WORK** — artifacts are substantial but have one structural blocker and several
factual corrections needed.

## Gate Analysis

### 1. Intent & Success — PASS

- Problem statement is clear: multi-domain event processing after system pipeline.
- Success criteria are concrete and testable (11 checkboxes in requirements).
- "What" and "why" are captured in `input.md` and `requirements.md`.

### 2. Scope & Size — PASS (with note)

- Work is substantial (8 phases, ~20 tasks) but follows an incremental pattern where
  each phase is independently testable.
- Cross-cutting concerns are called out (config schema, daemon wiring).
- The scope is large for a single AI session but phases are sequentially buildable.

### 3. Verification — PASS

- Each phase has testable outputs. Success criteria map to observable behavior.
- Edge cases identified: cycle detection, exception isolation, permission errors.
- `make test` and `make lint` as final gates.

### 4. Approach Known — PASS

- Implementation plan follows established codebase patterns (Pipeline, Cartridge Protocol,
  config loading, asyncio.gather).
- Dynamic module loading via `importlib.util.spec_from_file_location` is standard Python.
- Pydantic models for config schema match existing patterns in `teleclaude/config/schema.py`.

### 5. Research Complete — PASS (auto-satisfied)

- No new third-party dependencies. All patterns use stdlib + existing deps (Pydantic,
  asyncio, importlib).

### 6. Dependencies & Preconditions — BLOCKER

- **`event-system-cartridges` is a roadmap dependency** (`after: [event-system-cartridges]`)
  and is currently unbuilt (DOR score 0, build pending).
- The domain infrastructure plan assumes the system pipeline is fully operational with
  trust/enrichment/correlation/classification cartridges. Specifically:
  - `PipelineContext` may gain fields from `event-system-cartridges` (trust_config,
    correlation_config, producer) that domain pipeline context extends.
  - The "after system pipeline completes" fan-out assumes the full 6-cartridge system
    chain exists.
- **Question:** Can domain infrastructure be built against the current 2-cartridge system
  pipeline (dedup + notification), with the fan-out point being after whatever system
  cartridges exist? If yes, the dependency is soft and domain infra can proceed. If the
  plan requires trust/enrichment/classification outputs in domain cartridges, the dependency
  is hard.

### 7. Integration Safety — PASS

- Domain pipeline is fire-and-forget from system pipeline (doesn't mutate system output).
- Startup errors disable domain pipeline without crashing daemon.
- Cartridge exception isolation prevents cascading failures.

### 8. Tooling Impact — NEEDS REVIEW

- New `telec config cartridges` subcommands are introduced. The CLI surface expansion
  should be verified against the existing config command structure.
- Config wizard gains a "Domain Autonomy" section — wizard testing needed.

## Corrections Applied (Draft Phase)

1. **Fixed:** Implementation plan referenced `teleclaude_events/cartridge.py` — actual
   Cartridge Protocol is in `teleclaude_events/pipeline.py`.
2. **Fixed:** Implementation plan referenced `teleclaude/core/config.py` — actual config
   module is `teleclaude/config/schema.py` + `teleclaude/config/loader.py`.
3. **Fixed:** Implementation plan referenced `teleclaude/config_schema.py` — corrected to
   `teleclaude/config/schema.py`.
4. **Fixed:** Requirements constraint said `async def process(event, context)` — corrected
   to class-based Protocol with `self` parameter.
5. **Added:** Fleshed out `demo.md` with concrete validation commands and guided presentation.

## Open Questions

1. Is the `event-system-cartridges` dependency hard or soft? Can domain infrastructure
   work against the current 2-cartridge pipeline?
2. The plan adds `DomainsConfig` to the top-level config schema — should this be a new
   top-level key in `GlobalConfig`, or nested under an existing section?
3. Member identity: personal pipelines reference `member_id` but the current config uses
   `PersonConfig` with `invite_token`. How does member identity map to personal cartridge
   paths?

## Blockers

1. **Upstream dependency `event-system-cartridges`** — roadmap declares hard dependency;
   needs decision on whether to proceed or wait.

## Recommendations

- If the dependency is soft (domain infra can work against any system pipeline length),
  remove or relax the roadmap dependency and proceed.
- If hard, prepare `event-system-cartridges` first.
- Regardless, the artifacts are gate-ready once the dependency question is resolved.

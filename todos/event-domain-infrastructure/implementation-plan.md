# Implementation Plan: event-domain-infrastructure

## Overview

Build the domain event processing layer on top of `teleclaude_events/` (from
`event-platform-core`). The system pipeline already runs; this phase fans out to domain
pipelines in parallel after it completes.

Ordered for incremental testability: config schema first, then cartridge discovery and DAG,
then runtime execution, then personal subscriptions, then lifecycle ops, then autonomy matrix,
then `telec config` surface, then wiring into the daemon.

Codebase patterns to follow:

| Pattern                 | Evidence                                                               |
| ----------------------- | ---------------------------------------------------------------------- |
| Package layout          | `teleclaude_events/pipeline.py` (from event-platform-core)             |
| Cartridge interface     | `teleclaude_events/cartridge.py` — `async def process(event, context)` |
| Config loading          | `teleclaude/core/config.py` — YAML config, `get_config()`              |
| Dynamic module import   | `importlib.util.spec_from_file_location` pattern                       |
| Async parallel tasks    | `asyncio.gather(*tasks, return_exceptions=True)`                       |
| Background task hosting | `teleclaude/daemon.py` — `asyncio.create_task` + done callback         |
| FastAPI routes          | `teleclaude/api_server.py` — route registration on `self.app`          |

---

## Phase 1: Config Schema and Domain Registry

### Task 1.1: Define domain config schema

**File(s):** `teleclaude_events/domain_config.py`

- [ ] Define `AutonomyLevel` string enum: `manual`, `notify`, `auto_notify`, `autonomous`
- [ ] Define `AutonomyMatrix` Pydantic model:
  - `global_default: AutonomyLevel = AutonomyLevel.notify`
  - `by_domain: dict[str, AutonomyLevel] = {}`
  - `by_cartridge: dict[str, AutonomyLevel] = {}` # key: `"{domain}/{cartridge_id}"`
  - `by_event_type: dict[str, AutonomyLevel] = {}` # key: `"{domain}/{event_type}"`
  - `resolve(domain, cartridge_id, event_type) -> AutonomyLevel` — priority: event_type > cartridge > domain > global
- [ ] Define `DomainGuardianConfig` Pydantic model:
  - `agent: str = "claude"`
  - `mode: str = "med"`
  - `enabled: bool = True`
  - `evaluation_prompt: str | None = None`
- [ ] Define `DomainConfig` Pydantic model:
  - `name: str`
  - `enabled: bool = True`
  - `cartridge_path: str | None = None` # defaults to `~/.teleclaude/company/domains/{name}/cartridges/`
  - `guardian: DomainGuardianConfig = Field(default_factory=DomainGuardianConfig)`
  - `autonomy: AutonomyMatrix = Field(default_factory=AutonomyMatrix)`
- [ ] Define `DomainsConfig` Pydantic model (top-level config key `domains`):
  - `enabled: bool = True`
  - `base_path: str = "~/.teleclaude/company"`
  - `personal_base_path: str = "~/.teleclaude/personal"`
  - `helpdesk_path: str = "~/.teleclaude/helpdesk"`
  - `domains: dict[str, DomainConfig] = {}`
- [ ] Unit test: `AutonomyMatrix.resolve` priority ordering

### Task 1.2: Domain registry

**File(s):** `teleclaude_events/domain_registry.py`

- [ ] Define `DomainRegistry` class:
  - `_domains: dict[str, DomainConfig]`
  - `load_from_config(config: DomainsConfig) -> None` — populate from config dict
  - `get(name: str) -> DomainConfig | None`
  - `list_enabled() -> list[DomainConfig]`
  - `cartridge_path_for(domain_name: str) -> Path` — expand `~`, apply override or default
  - `personal_path_for(member_id: str) -> Path`
- [ ] Unit test: `cartridge_path_for` with override and default

---

## Phase 2: Cartridge Discovery and DAG

### Task 2.1: Cartridge manifest schema

**File(s):** `teleclaude_events/cartridge_manifest.py`

- [ ] Define `CartridgeManifest` Pydantic model (loaded from `manifest.yaml` in cartridge dir):
  - `id: str` # unique within domain, e.g. `enrich-git-context`
  - `description: str`
  - `version: str = "0.1.0"`
  - `domain_affinity: list[str] = []` # empty = any domain
  - `depends_on: list[str] = []` # list of cartridge IDs within same domain
  - `output_slots: list[str] = []` # e.g. `["enrichment.git"]` — conflict detection key
  - `personal: bool = False` # true = personal/member scope only
  - `module: str = "cartridge"` # Python module filename (without .py)
- [ ] Define `CartridgeError` base exception; subclasses: `CartridgeCycleError`,
      `CartridgeDependencyError`, `CartridgeScopeError`, `CartridgeConflictError`
- [ ] Unit test: manifest loads from YAML dict

### Task 2.2: Cartridge loader and DAG resolver

**File(s):** `teleclaude_events/cartridge_loader.py`

- [ ] Define `LoadedCartridge` dataclass:
  - `manifest: CartridgeManifest`
  - `module_path: Path`
  - `process: Callable` # the `async def process(event, context)` callable
- [ ] `load_cartridge(path: Path) -> LoadedCartridge`:
  - Read `manifest.yaml` from `path/`
  - Import module via `importlib.util.spec_from_file_location`
  - Resolve `process` callable; raise `CartridgeError` if missing
- [ ] `discover_cartridges(domain_path: Path) -> list[LoadedCartridge]`:
  - Scan immediate subdirs of `domain_path` for `manifest.yaml`
  - Call `load_cartridge` on each; collect errors without aborting
  - Return successfully loaded list
- [ ] `resolve_dag(cartridges: list[LoadedCartridge]) -> list[list[LoadedCartridge]]`:
  - Build adjacency map from `depends_on` fields
  - Kahn's algorithm topological sort
  - Raise `CartridgeCycleError` with cycle path if cycle detected
  - Return levels: `[[level0_a, level0_b], [level1_a], ...]`
- [ ] `validate_pipeline(levels: list[list[LoadedCartridge]], domain: str) -> None`:
  - Scope check: cartridge with non-empty `domain_affinity` must include `domain`
  - Output slot uniqueness: two cartridges in same domain cannot share an output slot for
    the same event type (static check; log warning, not error)
  - Raise appropriate `CartridgeError` subclass on hard failures
- [ ] Unit tests: cycle detection, topological levels, scope mismatch, missing dependency

---

## Phase 3: Domain Pipeline Runtime

### Task 3.1: Domain pipeline executor

**File(s):** `teleclaude_events/domain_pipeline.py`

- [ ] Define `DomainPipelineContext` (extends `PipelineContext`):
  - `domain_name: str`
  - `autonomy_matrix: AutonomyMatrix`
  - `guardian_config: DomainGuardianConfig`
- [ ] Define `DomainPipeline` class:
  - `__init__(domain: DomainConfig, levels: list[list[LoadedCartridge]])`
  - `async run(event: EventEnvelope, base_context: PipelineContext) -> EventEnvelope | None`:
    - Iterate levels; within each level run cartridges concurrently via `asyncio.gather`
    - Per-cartridge exception isolation: catch and log; do not abort level
    - Pass `DomainPipelineContext` to each cartridge
    - Return final envelope (last non-None result) or None if all cartridges return None
- [ ] Define `DomainPipelineRunner` class:
  - `_pipelines: dict[str, DomainPipeline]` — keyed by domain name
  - `async run_all(event: EventEnvelope, context: PipelineContext) -> dict[str, EventEnvelope | None]`:
    - Run all enabled domain pipelines in parallel via `asyncio.gather`
    - Return domain name → result map
  - `async run_for_domain(domain: str, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`
- [ ] Unit test: parallel execution, per-cartridge exception isolation

### Task 3.2: Integrate domain runner into main pipeline

**File(s):** `teleclaude_events/pipeline.py`

- [ ] After system pipeline completes, call `DomainPipelineRunner.run_all(event, context)`
- [ ] Results are fire-and-forget from system pipeline perspective (domain results do not
      mutate the system pipeline output)
- [ ] Log domain pipeline results at DEBUG level
- [ ] Unit test: system pipeline result unaffected by domain pipeline error

---

## Phase 4: Personal Subscription Pipeline

### Task 4.1: Personal cartridge loader

**File(s):** `teleclaude_events/personal_pipeline.py`

- [ ] Define `PersonalPipeline` class:
  - `member_id: str`
  - `cartridges: list[LoadedCartridge]` # leaf nodes only (personal=True enforced)
  - `async run(event: EventEnvelope, context: PipelineContext) -> None`:
    - Run all personal cartridges sequentially (no DAG; leaf nodes have no deps)
    - Per-cartridge exception isolation
- [ ] `load_personal_pipeline(member_id: str, path: Path) -> PersonalPipeline`:
  - Discover cartridges from `path`
  - Reject any cartridge where `manifest.personal is False` or `depends_on` is non-empty
  - Return `PersonalPipeline`
- [ ] Integrate into `DomainPipelineRunner`: after domain pipelines complete, run personal
      pipelines for all members in parallel
- [ ] Unit test: personal cartridge isolation, non-leaf rejection

---

## Phase 5: Cartridge Lifecycle Commands

### Task 5.1: Lifecycle manager

**File(s):** `teleclaude_events/lifecycle.py`

- [ ] Define `CartridgeScope` enum: `personal`, `domain`, `platform`
- [ ] Define `LifecycleManager` class:
  - `install(source_path: Path, scope: CartridgeScope, target: str, caller_is_admin: bool) -> None`:
    - `scope=personal`: copy to `personal_base_path/members/{target}/cartridges/`
    - `scope=domain/platform`: require `caller_is_admin`; copy to appropriate domain path
    - Validate manifest before install; raise `CartridgeError` on invalid
    - Reload pipeline after install
  - `remove(cartridge_id: str, scope: CartridgeScope, target: str, caller_is_admin: bool) -> None`:
    - Locate cartridge dir by scanning target path
    - `scope=domain/platform`: require `caller_is_admin`
    - Delete cartridge dir; reload pipeline
  - `promote(cartridge_id: str, from_scope: CartridgeScope, to_scope: CartridgeScope,
         target_domain: str, caller_is_admin: bool) -> None`:
    - `personal → domain`: require `caller_is_admin`
    - `domain → platform`: require `caller_is_admin`
    - Copy manifest+module to target path; remove from source path; reload pipeline
  - `reload() -> None`: trigger `DomainPipelineRunner` rebuild from disk
- [ ] Unit test: install/remove/promote with permission checks

### Task 5.2: `telec config` CLI surface for lifecycle

**File(s):** `teleclaude/cli/commands/config_commands.py` (or equivalent CLI entrypoint)

- [ ] `telec config cartridges install --path <src> --scope <scope> --target <name>`
- [ ] `telec config cartridges remove --id <id> --scope <scope> --target <name>`
- [ ] `telec config cartridges promote --id <id> --from <scope> --to <scope> --domain <name>`
- [ ] `telec config cartridges list [--domain <name>] [--member <id>]`
- [ ] Each command calls `LifecycleManager`; prints structured result
- [ ] Permission error produces clear message: "This operation requires admin role."

---

## Phase 6: Autonomy Matrix and Config Integration

### Task 6.1: Autonomy matrix config keys and wizard

**File(s):** `teleclaude/cli/commands/config_commands.py`, `teleclaude/config_schema.py`

- [ ] Add `domains` key to top-level config schema (`DomainsConfig`)
- [ ] `telec config get domains.{name}.autonomy` returns resolved matrix
- [ ] `telec config patch --yaml 'domains.software-development.autonomy.global_default: autonomous'`
      updates config file
- [ ] Config wizard: new section "Domain Autonomy" — prompts for global default, then
      optionally per-domain overrides
- [ ] Unit test: `resolve()` reads from config correctly after patch

### Task 6.2: Runtime autonomy enforcement

**File(s):** `teleclaude_events/domain_pipeline.py`

- [ ] `DomainPipeline.run` consults `AutonomyMatrix.resolve(domain, cartridge_id, event_type)`
      before invoking each cartridge
- [ ] `manual` → skip cartridge, emit `cartridge.skipped` event with reason `autonomy=manual`
- [ ] `notify` → run cartridge, emit notification regardless of cartridge's own notification logic
- [ ] `auto_notify` → run cartridge, suppress notification if cartridge returns None
- [ ] `autonomous` → run cartridge, no notification
- [ ] Unit test: each autonomy level produces correct behavior

---

## Phase 7: Domain Guardian Config and Startup Wiring

### Task 7.1: Domain guardian config passthrough

**File(s):** `teleclaude_events/domain_pipeline.py`, `teleclaude_events/domain_config.py`

- [ ] `DomainPipelineContext` carries `guardian_config` from `DomainConfig`
- [ ] Cartridges may read `context.guardian_config` to determine AI agent settings
      (no guardian execution in this phase — that is `event-domain-pillars`)
- [ ] Absent guardian config block → `DomainGuardianConfig()` defaults, no error
- [ ] Unit test: context carries config, absent block uses defaults

### Task 7.2: Daemon startup wiring

**File(s):** `teleclaude/daemon.py`, `teleclaude_events/startup.py`

- [ ] Define `build_domain_pipeline_runner(config: DomainsConfig) -> DomainPipelineRunner`:
  - Load registry from config
  - For each enabled domain: discover cartridges, resolve DAG, validate, build `DomainPipeline`
  - Build personal pipelines for all configured members
  - Return `DomainPipelineRunner`
- [ ] Call `build_domain_pipeline_runner` on daemon startup (after `event-platform-core`
      system pipeline is started)
- [ ] On startup error (e.g., `CartridgeCycleError`): log error, disable domain pipeline,
      continue daemon startup — domain failures must not crash the daemon
- [ ] Register `LifecycleManager` with daemon for use by CLI commands
- [ ] Unit test: startup with empty domains config completes without error

### Task 7.3: Tests and quality

**File(s):** `tests/teleclaude_events/test_domain_pipeline.py`,
`tests/teleclaude_events/test_cartridge_loader.py`,
`tests/teleclaude_events/test_lifecycle.py`,
`tests/teleclaude_events/test_autonomy_matrix.py`

- [ ] Integration test: full event flow through system pipeline → domain pipelines in parallel
- [ ] Integration test: personal pipeline runs after domain pipelines
- [ ] Integration test: autonomy `manual` skips cartridge, `autonomous` runs silently
- [ ] Integration test: lifecycle `promote` moves cartridge and reloads pipeline
- [ ] Run `make test` — all pass
- [ ] Run `make lint` — clean

---

## Phase 8: Review Readiness

- [ ] Confirm all success criteria in `requirements.md` are met and marked `[x]`
- [ ] Confirm all implementation tasks above are marked `[x]`
- [ ] `telec config cartridges list` returns correct output for a seeded test domain
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

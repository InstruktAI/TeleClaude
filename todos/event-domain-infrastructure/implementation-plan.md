# Implementation Plan: event-domain-infrastructure

## Overview

Build the domain event processing layer on top of `teleclaude_events/` (from
`event-platform-core`). The system pipeline already runs; this phase fans out to domain
pipelines in parallel after it completes.

Ordered for incremental testability: config schema first, then cartridge discovery and DAG,
then runtime execution, then personal subscriptions, then lifecycle ops, then autonomy matrix,
then `telec config` surface, then wiring into the daemon.

Codebase patterns to follow:

| Pattern                 | Evidence                                                                                              |
| ----------------------- | ----------------------------------------------------------------------------------------------------- |
| Package layout          | `teleclaude_events/pipeline.py` (from event-platform-core)                                            |
| Cartridge interface     | `teleclaude_events/pipeline.py` — `Cartridge` Protocol with `async def process(self, event, context)` |
| Config loading          | `teleclaude/config/schema.py` + `teleclaude/config/loader.py` — YAML config, `load_config()`          |
| Dynamic module import   | `importlib.util.spec_from_file_location` pattern                                                      |
| Async parallel tasks    | `asyncio.gather(*tasks, return_exceptions=True)`                                                      |
| Background task hosting | `teleclaude/daemon.py` — `asyncio.create_task` + done callback                                        |
| FastAPI routes          | `teleclaude/api_server.py` — route registration on `self.app`                                         |

---

## Phase 1: Config Schema and Domain Registry

### Task 1.1: Define domain config schema

**File(s):** `teleclaude_events/domain_config.py`

- [x] Define `AutonomyLevel` string enum: `manual`, `notify`, `auto_notify`, `autonomous`
- [x] Define `AutonomyMatrix` Pydantic model:
  - `global_default: AutonomyLevel = AutonomyLevel.notify`
  - `by_domain: dict[str, AutonomyLevel] = {}`
  - `by_cartridge: dict[str, AutonomyLevel] = {}` # key: `"{domain}/{cartridge_id}"`
  - `by_event_type: dict[str, AutonomyLevel] = {}` # key: `"{domain}/{event_type}"`
  - `resolve(domain, cartridge_id, event_type) -> AutonomyLevel` — priority: event_type > cartridge > domain > global
- [x] Define `DomainGuardianConfig` Pydantic model:
  - `agent: str = "claude"`
  - `mode: str = "med"`
  - `enabled: bool = True`
  - `evaluation_prompt: str | None = None`
- [x] Define `DomainConfig` Pydantic model:
  - `name: str`
  - `enabled: bool = True`
  - `cartridge_path: str | None = None` # defaults to `~/.teleclaude/company/domains/{name}/cartridges/`
  - `guardian: DomainGuardianConfig = Field(default_factory=DomainGuardianConfig)`
  - `autonomy: AutonomyMatrix = Field(default_factory=AutonomyMatrix)`
- [x] Define `DomainsConfig` Pydantic model (top-level config key `event_domains` — avoids
      collision with existing `BusinessConfig.domains`):
  - `enabled: bool = True`
  - `base_path: str = "~/.teleclaude/company"`
  - `personal_base_path: str = "~/.teleclaude/personal"`
  - `helpdesk_path: str = "~/.teleclaude/helpdesk"`
  - `domains: dict[str, DomainConfig] = {}`
- [x] Unit test: `AutonomyMatrix.resolve` priority ordering

### Task 1.2: Domain registry

**File(s):** `teleclaude_events/domain_registry.py`

- [x] Define `DomainRegistry` class:
  - `_domains: dict[str, DomainConfig]`
  - `load_from_config(config: DomainsConfig) -> None` — populate from config dict
  - `get(name: str) -> DomainConfig | None`
  - `list_enabled() -> list[DomainConfig]`
  - `cartridge_path_for(domain_name: str) -> Path` — expand `~`, apply override or default
  - `personal_path_for(member_id: str) -> Path` — `member_id` is derived from
    `PersonEntry.email` (slugified). The registry resolves member email → filesystem path.
- [x] Unit test: `cartridge_path_for` with override and default

---

## Phase 2: Cartridge Discovery and DAG

### Task 2.1: Cartridge manifest schema

**File(s):** `teleclaude_events/cartridge_manifest.py`

- [x] Define `CartridgeManifest` Pydantic model (loaded from `manifest.yaml` in cartridge dir):
  - `id: str` # unique within domain, e.g. `enrich-git-context`
  - `description: str`
  - `version: str = "0.1.0"`
  - `domain_affinity: list[str] = []` # empty = any domain
  - `depends_on: list[str] = []` # list of cartridge IDs within same domain
  - `output_slots: list[str] = []` # e.g. `["enrichment.git"]` — conflict detection key
  - `personal: bool = False` # true = personal/member scope only
  - `module: str = "cartridge"` # Python module filename (without .py)
- [x] Define `CartridgeError` base exception; subclasses: `CartridgeCycleError`,
      `CartridgeDependencyError`, `CartridgeScopeError`, `CartridgeConflictError`
- [x] Unit test: manifest loads from YAML dict

### Task 2.2: Cartridge loader and DAG resolver

**File(s):** `teleclaude_events/cartridge_loader.py`

- [x] Define `LoadedCartridge` dataclass:
  - `manifest: CartridgeManifest`
  - `module_path: Path`
  - `process: Callable` # the `async def process(event, context)` callable
- [x] `load_cartridge(path: Path) -> LoadedCartridge`:
  - Read `manifest.yaml` from `path/`
  - Import module via `importlib.util.spec_from_file_location`
  - Resolve `process` callable; raise `CartridgeError` if missing
- [x] `discover_cartridges(domain_path: Path) -> list[LoadedCartridge]`:
  - Scan immediate subdirs of `domain_path` for `manifest.yaml`
  - Call `load_cartridge` on each; collect errors without aborting
  - Return successfully loaded list
- [x] `resolve_dag(cartridges: list[LoadedCartridge]) -> list[list[LoadedCartridge]]`:
  - Build adjacency map from `depends_on` fields
  - Kahn's algorithm topological sort
  - Raise `CartridgeCycleError` with cycle path if cycle detected
  - Return levels: `[[level0_a, level0_b], [level1_a], ...]`
- [x] `validate_pipeline(levels: list[list[LoadedCartridge]], domain: str) -> None`:
  - Scope check: cartridge with non-empty `domain_affinity` must include `domain`
  - Output slot uniqueness: two cartridges in same domain cannot share an output slot for
    the same event type (static check; log warning, not error)
  - Raise appropriate `CartridgeError` subclass on hard failures
- [x] Unit tests: cycle detection, topological levels, scope mismatch, missing dependency

---

## Phase 3: Domain Pipeline Runtime

### Task 3.1: Domain pipeline executor

**File(s):** `teleclaude_events/domain_pipeline.py`

- [x] Define `DomainPipelineContext` (extends `PipelineContext`):
  - `domain_name: str`
  - `autonomy_matrix: AutonomyMatrix`
  - `guardian_config: DomainGuardianConfig`
- [x] Define `DomainPipeline` class:
  - `__init__(domain: DomainConfig, levels: list[list[LoadedCartridge]])`
  - `async run(event: EventEnvelope, base_context: PipelineContext) -> EventEnvelope | None`:
    - Iterate levels; within each level run cartridges concurrently via `asyncio.gather`
    - Per-cartridge exception isolation: catch and log; do not abort level
    - Pass `DomainPipelineContext` to each cartridge
    - Return final envelope (last non-None result) or None if all cartridges return None
- [x] Define `DomainPipelineRunner` class:
  - `_pipelines: dict[str, DomainPipeline]` — keyed by domain name
  - `async run_all(event: EventEnvelope, context: PipelineContext) -> dict[str, EventEnvelope | None]`:
    - Run all enabled domain pipelines in parallel via `asyncio.gather`
    - Return domain name → result map
  - `async run_for_domain(domain: str, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`
- [x] Unit test: parallel execution, per-cartridge exception isolation

### Task 3.2: Integrate domain runner into main pipeline

**File(s):** `teleclaude_events/pipeline.py`

- [x] After system pipeline completes, call `DomainPipelineRunner.run_all(event, context)`
- [x] Results are fire-and-forget from system pipeline perspective (domain results do not
      mutate the system pipeline output)
- [x] Log domain pipeline results at DEBUG level
- [x] Unit test: system pipeline result unaffected by domain pipeline error

---

## Phase 4: Personal Subscription Pipeline

### Task 4.1: Personal cartridge loader

**File(s):** `teleclaude_events/personal_pipeline.py`

- [x] Define `PersonalPipeline` class:
  - `member_id: str`
  - `cartridges: list[LoadedCartridge]` # leaf nodes only (personal=True enforced)
  - `async run(event: EventEnvelope, context: PipelineContext) -> None`:
    - Run all personal cartridges sequentially (no DAG; leaf nodes have no deps)
    - Per-cartridge exception isolation
- [x] `load_personal_pipeline(member_id: str, path: Path) -> PersonalPipeline`:
  - Discover cartridges from `path`
  - Reject any cartridge where `manifest.personal is False` or `depends_on` is non-empty
  - Return `PersonalPipeline`
- [x] Integrate into `DomainPipelineRunner`: after domain pipelines complete, run personal
      pipelines for all members in parallel
- [x] Unit test: personal cartridge isolation, non-leaf rejection

---

## Phase 5: Cartridge Lifecycle Commands

### Task 5.1: Lifecycle manager

**File(s):** `teleclaude_events/lifecycle.py`

- [x] Define `CartridgeScope` enum: `personal`, `domain`, `platform`
- [x] Define `LifecycleManager` class:
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
- [x] Unit test: install/remove/promote with permission checks

### Task 5.2: `telec config` CLI surface for lifecycle

**File(s):** `teleclaude/cli/cartridge_cli.py` (new), `teleclaude/cli/telec.py` (wire dispatcher)

The CLI dispatcher is `_handle_config()` in `teleclaude/cli/telec.py`. Add `"cartridges"` to the
subcommand switch and route to a new `teleclaude/cli/cartridge_cli.py` module (following the
pattern of `config_cmd.py` / `config_cli.py`).

- [x] `telec config cartridges install --path <src> --scope <scope> --target <name>`
- [x] `telec config cartridges remove --id <id> --scope <scope> --target <name>`
- [x] `telec config cartridges promote --id <id> --from <scope> --to <scope> --domain <name>`
- [x] `telec config cartridges list [--domain <name>] [--member <id>]`
- [x] Each command calls `LifecycleManager` via the daemon API; prints structured result
- [x] Permission error produces clear message: "This operation requires admin role."

---

## Phase 6: Autonomy Matrix and Config Integration

### Task 6.1: Autonomy matrix config keys and wizard

**File(s):** `teleclaude/config/schema.py`, `teleclaude/cli/cartridge_cli.py`, `teleclaude/cli/telec.py`

Note: `BusinessConfig.domains: Dict[str, str]` already exists in `schema.py` for business domain
labels. The event domain processing config must use a distinct key — `event_domains` — to avoid
collision. `DomainsConfig` maps to `GlobalConfig.event_domains`.

- [x] Add `event_domains` key to `GlobalConfig` (type: `DomainsConfig`)
- [x] `telec config get event_domains.{name}.autonomy` returns resolved matrix
- [x] `telec config patch --yaml 'event_domains.software-development.autonomy.global_default: autonomous'`
      updates config file
- [x] Config wizard: new section "Domain Autonomy" — prompts for global default, then
      optionally per-domain overrides
- [x] Unit test: `resolve()` reads from config correctly after patch

### Task 6.2: Runtime autonomy enforcement

**File(s):** `teleclaude_events/domain_pipeline.py`

- [x] `DomainPipeline.run` consults `AutonomyMatrix.resolve(domain, cartridge_id, event_type)`
      before invoking each cartridge
- [x] `manual` → skip cartridge, emit `cartridge.skipped` event with reason `autonomy=manual`
- [x] `notify` → run cartridge, emit notification regardless of cartridge's own notification logic
- [x] `auto_notify` → run cartridge, suppress notification if cartridge returns None
- [x] `autonomous` → run cartridge, no notification
- [x] Unit test: each autonomy level produces correct behavior

---

## Phase 7: Domain Guardian Config and Startup Wiring

### Task 7.1: Domain guardian config passthrough

**File(s):** `teleclaude_events/domain_pipeline.py`, `teleclaude_events/domain_config.py`

- [x] `DomainPipelineContext` carries `guardian_config` from `DomainConfig`
- [x] Cartridges may read `context.guardian_config` to determine AI agent settings
      (no guardian execution in this phase — that is `event-domain-pillars`)
- [x] Absent guardian config block → `DomainGuardianConfig()` defaults, no error
- [x] Unit test: context carries config, absent block uses defaults

### Task 7.2: Daemon startup wiring

**File(s):** `teleclaude/daemon.py`, `teleclaude_events/startup.py`

- [x] Define `build_domain_pipeline_runner(config: DomainsConfig) -> DomainPipelineRunner`:
  - Load registry from config
  - For each enabled domain: discover cartridges, resolve DAG, validate, build `DomainPipeline`
  - Build personal pipelines for all configured members
  - Return `DomainPipelineRunner`
- [x] Call `build_domain_pipeline_runner` on daemon startup (after `event-platform-core`
      system pipeline is started)
- [x] On startup error (e.g., `CartridgeCycleError`): log error, disable domain pipeline,
      continue daemon startup — domain failures must not crash the daemon
- [x] Register `LifecycleManager` with daemon for use by CLI commands
- [x] Unit test: startup with empty domains config completes without error

### Task 7.3: Tests and quality

**File(s):** `tests/teleclaude_events/test_domain_pipeline.py`,
`tests/teleclaude_events/test_cartridge_loader.py`,
`tests/teleclaude_events/test_lifecycle.py`,
`tests/teleclaude_events/test_autonomy_matrix.py`

- [x] Integration test: full event flow through system pipeline → domain pipelines in parallel
- [x] Integration test: personal pipeline runs after domain pipelines
- [x] Integration test: autonomy `manual` skips cartridge, `autonomous` runs silently
- [x] Integration test: lifecycle `promote` moves cartridge and reloads pipeline
- [x] Run `make test` — all pass
- [x] Run `make lint` — clean

---

## Phase 8: Review Readiness

- [x] Confirm all success criteria in `requirements.md` are met and marked `[x]`
- [x] Confirm all implementation tasks above are marked `[x]`
- [x] `telec config cartridges list` returns correct output for a seeded test domain
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)

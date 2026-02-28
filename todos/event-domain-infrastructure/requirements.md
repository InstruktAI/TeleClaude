# Requirements: event-domain-infrastructure

## Goal

Implement multi-domain event processing infrastructure: domain-scoped cartridge pipelines that
execute in parallel after the system pipeline completes, with a full cartridge lifecycle (install,
remove, promote), dependency-aware loading (DAG + topological sort), configurable autonomy matrix,
and role-scoped access control.

## Scope

### In scope

- **Domain pipeline runtime:** parallel per-domain execution after system pipeline; each domain
  runs its cartridge stack sequentially via the existing `PipelineContext` interface.
- **Folder hierarchy:** `~/.teleclaude/company/domains/{name}/cartridges/`,
  `~/.teleclaude/personal/members/{id}/cartridges/`, `~/.teleclaude/helpdesk/cartridges/`.
  Cartridges are Python modules discovered by convention from these paths.
- **Domain cartridge loading:** scan domain folders on startup, resolve dependency DAG,
  topological sort, validate no cycles, load in order.
- **Parallel DAG execution:** cartridges at the same topological level within a domain run
  concurrently via `asyncio.gather`.
- **Personal subscription pipeline:** per-member micro-cartridges (leaf nodes). Members can
  install cartridges scoped to their personal domain only. Leaf = no dependents, no domain-level
  side effects.
- **Cartridge lifecycle:** `install`, `remove`, `promote` (personal → domain → platform) commands
  via `telec config`. Promote requires admin role.
- **Autonomy matrix:** four-level hierarchy `event_type > cartridge > domain > global`. Stored
  in config, manageable via `telec config get/patch`. Levels: `manual`, `notify`, `auto_notify`,
  `autonomous`.
- **Domain guardian AI config:** per-domain config block specifying agent settings for evaluating
  cartridge submissions, detecting behavioral patterns, validating compositions.
- **Pipeline validation on load:** scope matching (cartridge declares domain affinity), dependency
  satisfaction (all declared deps present and loadable), conflict detection (two cartridges claim
  same output slot for same event type).
- **Roles/permissions:** admin scope — install/remove/promote domain or platform cartridges,
  modify domain guardian config, set autonomy overrides. Member scope — install/remove personal
  cartridges only.
- **`telec config` integration:** new config keys under `domains.{name}.autonomy`,
  `domains.{name}.guardian`, `domains.{name}.cartridges`. Config wizard sections for autonomy
  management.

### Out of scope

- Domain-specific cartridge implementations (those live in `event-domain-pillars`).
- Mesh distribution of cartridges across nodes (`event-mesh-distribution`).
- Alpha container sandboxing (`event-alpha-container`).
- Signal processing cartridges (`event-signal-pipeline`).
- UI rendering for domain events (handled by existing notification/API layer).
- Cross-domain cartridge composition (deferred; not needed until pillars exist).

## Success Criteria

- [ ] Domain pipeline executes per-domain in parallel after system pipeline; events with no
      domain routing skip domain stage without error.
- [ ] Cartridges loaded from `company/domains/{name}/cartridges/` are topologically sorted;
      cycle in DAG raises `CartridgeCycleError` at startup.
- [ ] Cartridges at the same DAG level within a domain run concurrently.
- [ ] Personal cartridges for a member are loaded as leaf nodes and execute after domain
      cartridges; member can only affect their own subscription scope.
- [ ] `telec config patch` can set autonomy level for a specific `event_type/cartridge/domain`;
      pipeline honors it at runtime.
- [ ] `install` / `remove` / `promote` lifecycle commands work end-to-end; promote fails with
      permission error for non-admin callers.
- [ ] Pipeline validation on startup rejects: missing dependency, scope mismatch, output
      slot conflict — with specific error messages identifying the offending cartridge.
- [ ] Domain guardian config block is read per domain and passed to domain pipeline context;
      no runtime errors when block is absent.
- [ ] `make test` passes with coverage for: DAG resolution, parallel execution, lifecycle ops,
      autonomy matrix lookup, validation errors.
- [ ] `make lint` passes.

## Constraints

- Cartridge interface unchanged: `async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`.
- No new database tables unless strictly required; autonomy matrix and domain config live in
  the existing config file.
- Domain pipeline must not block or delay the system pipeline result; runs as a fan-out.
- Personal cartridges are always leaf nodes — they cannot declare dependents.
- Folder paths use `~/.teleclaude/` as the root; paths are configurable but default to this.
- Python module loading from config folders must be sandboxed to the discovered path (no
  `sys.path` pollution beyond the cartridge directory scope).

## Risks

- **DAG complexity at scale:** many cartridges with interdependencies could produce slow
  startup topological sorts. Mitigate: cache resolved order; invalidate on cartridge add/remove.
- **Personal cartridge isolation:** a member's personal cartridge that raises an unhandled
  exception must not abort the domain pipeline. Mitigate: per-cartridge exception isolation with
  structured error logging.
- **Module loading from filesystem paths:** dynamic import of user-provided Python modules is
  a security surface. Mitigate: document that this is an admin-controlled path; no network
  access from cartridge execution context in this phase.
- **Autonomy matrix lookup performance:** matrix is queried per event per cartridge; if config
  is re-read from disk on every lookup, this adds latency. Mitigate: load matrix into memory at
  startup, watch config file for changes.
- **Cartridge promotion rollback:** if a promoted cartridge breaks domain pipeline, rollback
  path must be clear. Mitigate: `remove` command works at any scope; document recovery procedure.

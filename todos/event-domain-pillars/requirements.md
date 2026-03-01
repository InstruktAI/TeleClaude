# Requirements: event-domain-pillars

## Goal

Ship production-ready domain configurations for four business pillars (software development,
marketing, creative production, customer relations). Each pillar provides catalog-registered
event schemas, starter cartridges (following the `CartridgeManifest` + module convention from
`event-domain-infrastructure`), and domain config entries (including `DomainGuardianConfig`)
so that `telec init` can seed these domains with zero manual authoring.

## Scope

### In scope

- **Event schema registrations** for all four pillars added to
  `teleclaude_events/schemas/` modules, following the existing catalog registration pattern
  (`EventSchema` + `EventCatalog.register()`)
- **Software development pillar**: extend the existing 9 schemas in
  `teleclaude_events/schemas/software_development.py` with additional lifecycle events
  (deploy, ops, maintenance) — do not duplicate existing registrations
- **Starter cartridges** per pillar under `~/.teleclaude/company/domains/{name}/cartridges/`,
  each as a subdirectory with `manifest.yaml` (conforming to `CartridgeManifest` schema) and
  a Python module implementing `async def process(event, context)`
- **Domain config entries** per pillar: `DomainConfig` blocks with `DomainGuardianConfig`
  nested, seeded into the main config via `telec init` or `telec config patch`
- **Marketing pillar** composition: feed-monitor cartridge declares
  `depends_on: [signal-ingest, signal-cluster, signal-synthesize]` in its manifest
- **Customer relations jailing**: domain config sets `trust_threshold: strict` via
  `DomainGuardianConfig`; cartridge manifests tag external-input handlers
- **`telec init` domain seeding**: a `seed_event_domains()` step in `init_flow.py` that
  checks if the `event_domains` config section is missing/empty and, if so, merges default
  pillar config blocks via the config loader (merge, not overwrite — preserves user edits)
- Documentation: schema modules and cartridge manifests serve as the primary documentation;
  each schema module has a module-level docstring describing the pillar's event taxonomy

### Out of scope

- Building the signal pipeline cartridges themselves (done in `event-signal-pipeline`)
- Building the domain infrastructure runtime (done in `event-domain-infrastructure`)
- Mesh distribution of domain events (done in `event-mesh-distribution`)
- Alpha container execution
- Per-member personal subscription micro-cartridges
- UI/TUI changes beyond `telec init` config seeding

## Success Criteria

- [ ] `teleclaude_events/schemas/software_development.py` is extended with deploy, ops, and
      maintenance event types (existing 9 schemas untouched)
- [ ] `teleclaude_events/schemas/marketing.py` registers content lifecycle, campaign, and
      feed monitoring event types using `catalog.register(EventSchema(...))`
- [ ] `teleclaude_events/schemas/creative_production.py` registers asset lifecycle event
      types (brief, draft, review, approval, delivery)
- [ ] `teleclaude_events/schemas/customer_relations.py` registers help desk, escalation,
      and satisfaction tracking event types
- [ ] `teleclaude_events/schemas/__init__.py` `register_all()` calls all four domain
      registration functions
- [ ] Each pillar has at least one starter cartridge as a subdirectory with valid
      `manifest.yaml` conforming to `CartridgeManifest` and a Python module
- [ ] Each pillar has a `DomainConfig` YAML block (with `DomainGuardianConfig`) ready for
      config seeding
- [ ] Marketing domain feed-monitor cartridge manifest declares
      `depends_on: [signal-ingest, signal-cluster, signal-synthesize]`
- [ ] Customer relations domain config has `guardian.trust_threshold: strict`
- [ ] `telec init` calls `seed_event_domains()` which merges default pillar configs into
      the `event_domains` section of the config file (no-op if already populated)
- [ ] All new event type strings emitted by starter cartridges are registered in the catalog
- [ ] Existing `domain.software-development.planning.*` emitters resolve against the catalog
      without change
- [ ] Tests cover schema registration, cartridge manifest loading, and config seeding
- [ ] `make lint` and `make test` pass

## Constraints

- Domain event schemas use the `EventSchema` + `EventCatalog` registration pattern — no
  Pydantic event subclasses (`EventEnvelope` is the single event data model)
- All `EventSchema` entries must specify `domain`, `default_level`, `lifecycle`, and
  `idempotency_fields`
- Cartridge manifests follow the `CartridgeManifest` schema from `event-domain-infrastructure`:
  `id`, `description`, `domain_affinity`, `depends_on`, `event_types`, `output_slots`, `module`
- Cartridge handler functions conform to the `Cartridge` protocol:
  `async def process(event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`
- No wildcard event subscriptions — cartridge manifests declare explicit `event_types`
- Guardian config is a `DomainGuardianConfig` within `DomainConfig`, not a separate file
- Config key namespace is `event_domains` (not `domains`) to avoid collision with
  `BusinessConfig.domains: Dict[str, str]` at `teleclaude/config/schema.py:96`
- Config seeding uses the same YAML structure as `telec config patch` operates on
- Cartridge I/O is via declared emitters only — no direct filesystem or network access

## Risks

- Software development schema extension may conflict with existing event type strings if
  naming convention diverges — requires audit of existing 9 event types before adding new ones
- Customer relations trust threshold depends on `event-domain-infrastructure` implementing
  the `DomainGuardianConfig` with trust threshold support; if not available, document as a
  stub and create a follow-up todo
- Marketing cartridge DAG depends on `event-signal-pipeline` shipping the signal utility
  cartridges; if signal pipeline slips, marketing starter cartridges ship as stubs with
  clear dependency documentation
- Cartridge subdirectory convention must match what `event-domain-infrastructure`'s
  `discover_cartridges()` expects — verify during implementation

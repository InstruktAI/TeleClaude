# Requirements: event-domain-pillars

## Goal

Ship production-ready domain configurations for four business pillars (software development, marketing, creative production, customer relations). Each pillar provides event schemas, starter cartridges, and a guardian AI config that together make the domain operational from `telec init` without manual schema authoring.

## Scope

### In scope

- Event schema definitions for all four pillars under `teleclaude_events/schemas/domain/`
- Starter cartridges for each pillar under `company/domains/{name}/cartridges/`
- Guardian AI config per domain at `company/domains/{name}/guardian.yaml`
- `telec init` discovery manifest entries so domains are listed and installable
- Marketing pillar composition of `signal-ingest`, `signal-cluster`, and `signal-synthesize` utility cartridges for feed monitoring
- Customer relations jailing: event producers in the help desk domain are treated as untrusted external input and run through the trust evaluator with stricter thresholds
- Software development formalization: existing todo lifecycle events (`todo.dor_assessed`, `todo.work.*`, etc.) elevated to first-class domain schemas
- Documentation for each pillar's event taxonomy and cartridge composition

### Out of scope

- Building the signal pipeline cartridges themselves (done in `event-signal-pipeline`)
- Building the domain infrastructure runtime (done in `event-domain-infrastructure`)
- Mesh distribution of domain events (done in `event-mesh-distribution`)
- Alpha container execution
- Per-member personal subscription micro-cartridges
- UI/TUI changes beyond `telec init` discovery

## Success Criteria

- [ ] `teleclaude_events/schemas/domain/software_development.py` declares all lifecycle event types (todo, build, review, deployment, operations, maintenance)
- [ ] `teleclaude_events/schemas/domain/marketing.py` declares content lifecycle, campaign, and feed monitoring event types
- [ ] `teleclaude_events/schemas/domain/creative_production.py` declares asset lifecycle event types (brief → draft → review → approval → delivery)
- [ ] `teleclaude_events/schemas/domain/customer_relations.py` declares help desk, escalation, and satisfaction tracking event types
- [ ] Each pillar has at least one starter cartridge that handles its primary lifecycle event
- [ ] Each pillar has a `guardian.yaml` with domain-appropriate AI config (model, prompt framing, autonomy defaults)
- [ ] Marketing domain cartridge composes signal pipeline utility cartridges via declared dependencies
- [ ] Customer relations guardian config enforces stricter trust thresholds for external input
- [ ] `telec init` lists all four domains and can install any of them
- [ ] Schema catalog registers all domain event types (no unregistered events emitted by starter cartridges)
- [ ] Existing internal event emitters (`todo.dor_assessed`) resolve against the new software-development schema without change
- [ ] Tests cover schema instantiation, cartridge handler dispatch, and guardian config loading for each pillar
- [ ] `make lint` and `make test` pass

## Constraints

- Domain cartridges must declare their `event_types` subscription list explicitly — no wildcard subscriptions
- Guardian AI configs must specify `autonomy_default` (one of: `notify`, `ask`, `act`) per cartridge
- Customer relations cartridges that handle external input must be tagged `trust_required: strict`
- Marketing cartridges composing the signal pipeline must declare `depends_on: [signal-ingest, signal-cluster, signal-synthesize]`
- Cartridge handler functions must be pure with respect to side effects — I/O via declared emitters only
- All schema models extend `DomainEvent` base from `teleclaude_events/schemas/base.py`
- `telec init` manifest is YAML; discovery entries follow the format established by `event-domain-infrastructure`

## Risks

- Software development schema may conflict with existing ad-hoc event strings in the codebase — requires an audit pass
- Customer relations jailing scope is not fully defined upstream; if `event-domain-infrastructure` doesn't implement the trust threshold override per domain, we must add a compatibility shim
- Marketing cartridge DAG depends on `event-signal-pipeline` being complete; if signal pipeline tasks slip, marketing starter cartridges ship as stubs with clear TODO markers
- Four pillars in parallel creates broad surface area; risk of inconsistent guardian config conventions across pillars — mitigate with a shared `guardian_config_schema.py` they all validate against

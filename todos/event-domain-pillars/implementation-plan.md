# Implementation Plan: event-domain-pillars

## Overview

Deliver four domain pillar configurations as pure data/content artifacts: catalog-registered
event schemas, starter cartridges (manifest + module), and domain config YAML blocks. No
runtime changes required — all runtime machinery (domain pipeline, cartridge loader, DAG
resolver, autonomy matrix) is built in `event-domain-infrastructure`.

Work is organized into six phases: shared setup first, then one phase per pillar (independent
and parallelizable), then validation.

### Codebase patterns to follow

| Pattern                | Evidence                                                                           |
| ---------------------- | ---------------------------------------------------------------------------------- |
| Schema registration    | `teleclaude_events/schemas/software_development.py` — `catalog.register(EventSchema(...))` |
| Event type naming      | `domain.software-development.planning.todo_created` — `domain.{domain}.{category}.{action}` |
| Envelope model         | `teleclaude_events/envelope.py` — `EventEnvelope` is the single event data model   |
| Catalog metadata       | `teleclaude_events/catalog.py` — `EventSchema`, `NotificationLifecycle`            |
| Cartridge interface    | `teleclaude_events/pipeline.py` — `Cartridge` Protocol: `async def process(event, context)` |
| Cartridge manifest     | `teleclaude_events/cartridge_manifest.py` (from `event-domain-infrastructure`)     |
| Domain config          | `teleclaude_events/domain_config.py` — `DomainConfig`, `DomainGuardianConfig`      |
| Config namespace       | `event_domains` top-level key (avoids `BusinessConfig.domains: Dict[str, str]` at `schema.py:96`) |
| Schema module pattern  | `teleclaude_events/schemas/__init__.py` — `register_all()` calls domain functions  |

### Assumed CartridgeManifest fields (from `event-domain-infrastructure` plan)

Until `CartridgeManifest` ships, manifests are authored as YAML matching these fields:

| Field              | Type         | Description                                       |
| ------------------ | ------------ | ------------------------------------------------- |
| `id`               | `str`        | Unique within domain, e.g. `todo-lifecycle`        |
| `description`      | `str`        | Short description                                  |
| `version`          | `str`        | Semver, default `0.1.0`                            |
| `domain_affinity`  | `list[str]`  | Domains this cartridge runs in; empty = any        |
| `depends_on`       | `list[str]`  | Cartridge IDs within same domain                   |
| `output_slots`     | `list[str]`  | Conflict detection keys                            |
| `module`           | `str`        | Python module filename (without `.py`), default `cartridge` |

### Cross-domain bridging pattern

Marketing's `feed-monitor` subscribes to signal pipeline events (`signal.synthesis.ready`)
and re-emits them as domain events (`domain.marketing.feed.synthesis_ready`). This is the
assumed cross-domain pattern: a domain cartridge consumes events from another domain's
namespace and translates them into its own. The signal pipeline emits under `signal.*`;
the marketing domain translates into `domain.marketing.feed.*`.

---

## Phase 1: Shared Setup

### Task 1.1: Verify upstream dependencies are available

- [ ] Confirm `teleclaude_events/cartridge_manifest.py` defines `CartridgeManifest` (from
      `event-domain-infrastructure`); if not yet built, document the expected schema and
      create placeholder YAML manifests that will validate once infrastructure ships
- [ ] Confirm `teleclaude_events/domain_config.py` defines `DomainConfig` and
      `DomainGuardianConfig`; if not yet built, document the expected config structure
- [ ] Confirm `teleclaude_events/domain_pipeline.py` defines `DomainPipelineContext`

### Task 1.2: Establish event type naming convention

- [ ] Audit existing 9 software-development event types in
      `teleclaude_events/schemas/software_development.py`
- [ ] Document the pattern: `domain.{domain-slug}.{category}.{action}`
- [ ] Define category taxonomy per pillar (used consistently in all schema phases below):
  - software-development: `planning`, `build`, `review`, `deploy`, `ops`, `maintenance`
  - marketing: `content`, `campaign`, `feed`
  - creative-production: `asset`, `format`
  - customer-relations: `helpdesk`, `satisfaction`, `escalation`

### Task 1.3: Create `telec init` domain seeding mechanism

**File(s):** `teleclaude_events/domain_seeds.py`, `teleclaude/project_setup/init_flow.py`

- [ ] Define `DEFAULT_EVENT_DOMAINS: dict` in `teleclaude_events/domain_seeds.py` containing
      default pillar configs as Python dicts (matching `DomainConfig` structure):
  ```yaml
  event_domains:
    software-development:
      enabled: true
      guardian:
        agent: claude
        mode: med
        enabled: true
    marketing:
      enabled: true
      guardian:
        agent: claude
        mode: med
        enabled: true
    creative-production:
      enabled: true
      guardian:
        agent: claude
        mode: med
        enabled: true
    customer-relations:
      enabled: true
      guardian:
        agent: claude
        mode: med
        enabled: true
        trust_threshold: strict
  ```
- [ ] Define `seed_event_domains(project_root: Path) -> None` in
      `teleclaude/project_setup/domain_seeds.py`:
  - Load current config via `load_config()`
  - If `event_domains` section is missing or empty, merge `DEFAULT_EVENT_DOMAINS`
  - If `event_domains` already has entries, skip (no-op — preserves user edits)
  - Write updated config via the config loader's save mechanism
- [ ] Add `seed_event_domains(project_root)` call to `init_project()` in `init_flow.py`
      (after `sync_project_artifacts`, before `install_docs_watch`)
- [ ] Test: `seed_event_domains` is idempotent — calling twice produces same result

---

## Phase 2: Software Development Pillar

### Task 2.1: Extend existing event schemas

**File(s):** `teleclaude_events/schemas/software_development.py`

Existing 9 events (DO NOT modify):
- `domain.software-development.planning.todo_created`
- `domain.software-development.planning.todo_dumped`
- `domain.software-development.planning.todo_activated`
- `domain.software-development.planning.artifact_changed`
- `domain.software-development.planning.dependency_resolved`
- `domain.software-development.planning.dor_assessed`
- `domain.software-development.build.completed`
- `domain.software-development.review.verdict_ready`
- `domain.software-development.review.needs_decision`

New event schemas to add:
- [ ] `domain.software-development.deploy.triggered` — WORKFLOW, idempotency: [slug, environment]
- [ ] `domain.software-development.deploy.succeeded` — WORKFLOW, idempotency: [slug, environment],
      lifecycle: resolves, group_key: slug
- [ ] `domain.software-development.deploy.failed` — BUSINESS, idempotency: [slug, environment],
      actionable: true
- [ ] `domain.software-development.ops.alert_fired` — BUSINESS, idempotency: [alert_id],
      actionable: true
- [ ] `domain.software-development.ops.alert_resolved` — WORKFLOW, idempotency: [alert_id],
      lifecycle: resolves, group_key: alert_id
- [ ] `domain.software-development.maintenance.dependency_update` — OPERATIONAL,
      idempotency: [package, version]
- [ ] `domain.software-development.maintenance.security_patch` — BUSINESS,
      idempotency: [advisory_id], actionable: true

### Task 2.2: Starter cartridges

**Directory structure:**
```
~/.teleclaude/company/domains/software-development/cartridges/
  todo-lifecycle/
    manifest.yaml
    cartridge.py
  build-notifier/
    manifest.yaml
    cartridge.py
  deploy-tracker/
    manifest.yaml
    cartridge.py
```

- [ ] `todo-lifecycle/manifest.yaml`: id=todo-lifecycle, domain_affinity=[software-development],
      depends_on=[], event_types=[domain.software-development.planning.todo_created,
      domain.software-development.planning.todo_dumped,
      domain.software-development.planning.todo_activated,
      domain.software-development.planning.artifact_changed,
      domain.software-development.planning.dependency_resolved,
      domain.software-development.planning.dor_assessed]
- [ ] `todo-lifecycle/cartridge.py`: subscribes to planning events, emits downstream state
      transitions, notifies on `dor_assessed` and `todo_activated`
- [ ] `build-notifier/manifest.yaml`: id=build-notifier, domain_affinity=[software-development],
      depends_on=[], event_types=[domain.software-development.build.completed]
- [ ] `build-notifier/cartridge.py`: subscribes to `build.completed` (checks payload for
      failure), notifies assigned developer
- [ ] `deploy-tracker/manifest.yaml`: id=deploy-tracker, domain_affinity=[software-development],
      depends_on=[], event_types=[domain.software-development.deploy.triggered,
      domain.software-development.deploy.succeeded,
      domain.software-development.deploy.failed]
- [ ] `deploy-tracker/cartridge.py`: subscribes to deploy events, maintains rolling log,
      notifies on failure

### Task 2.3: Domain config entry

**Data:** YAML block for `event_domains` config seeding

- [ ] `DomainConfig` block (under `event_domains.software-development`):
  ```yaml
  event_domains:
    software-development:
      enabled: true
      guardian:
        agent: claude
        mode: med
        enabled: true
        evaluation_prompt: "Software development domain guardian: monitor todo lifecycle,
          build health, and deployment patterns. Detect stalled todos, repeated build
          failures, and deployment anomalies."
  ```
- [ ] Autonomy defaults (seeded via `telec config patch` under
      `event_domains.software-development.autonomy`):
  - todo-lifecycle: `auto_notify`
  - build-notifier: `notify`
  - deploy-tracker: `notify`

---

## Phase 3: Marketing Pillar

### Task 3.1: Event schemas

**File(s):** `teleclaude_events/schemas/marketing.py`

- [ ] Create `register_marketing(catalog)` function
- [ ] Register event schemas:
  - `domain.marketing.content.brief_created` — WORKFLOW, creates=True
  - `domain.marketing.content.draft_ready` — WORKFLOW, updates=True, group_key=content_id
  - `domain.marketing.content.published` — WORKFLOW, resolves=True, group_key=content_id
  - `domain.marketing.content.performance_reported` — OPERATIONAL
  - `domain.marketing.campaign.launched` — WORKFLOW, creates=True
  - `domain.marketing.campaign.budget_threshold_hit` — BUSINESS, actionable=True
  - `domain.marketing.campaign.ended` — WORKFLOW, resolves=True, group_key=campaign_id
  - `domain.marketing.campaign.report_ready` — WORKFLOW
  - `domain.marketing.feed.signal_received` — OPERATIONAL (wraps signal pipeline output)
  - `domain.marketing.feed.cluster_formed` — OPERATIONAL
  - `domain.marketing.feed.synthesis_ready` — WORKFLOW, actionable=True
- [ ] Wire `register_marketing` into `teleclaude_events/schemas/__init__.py` `register_all()`

### Task 3.2: Starter cartridges

**Directory structure:**
```
~/.teleclaude/company/domains/marketing/cartridges/
  content-pipeline/
    manifest.yaml
    cartridge.py
  campaign-budget-monitor/
    manifest.yaml
    cartridge.py
  feed-monitor/
    manifest.yaml
    cartridge.py
```

- [ ] `content-pipeline/manifest.yaml`: id=content-pipeline,
      domain_affinity=[marketing], depends_on=[],
      event_types=[domain.marketing.content.brief_created,
      domain.marketing.content.draft_ready,
      domain.marketing.content.published,
      domain.marketing.content.performance_reported]
- [ ] `content-pipeline/cartridge.py`: subscribes to content events, orchestrates
      brief -> draft -> publish lifecycle transitions
- [ ] `campaign-budget-monitor/manifest.yaml`: id=campaign-budget-monitor,
      domain_affinity=[marketing], depends_on=[],
      event_types=[domain.marketing.campaign.budget_threshold_hit]
- [ ] `campaign-budget-monitor/cartridge.py`: subscribes to
      `campaign.budget_threshold_hit`, evaluates spend rate
- [ ] `feed-monitor/manifest.yaml`: id=feed-monitor, domain_affinity=[marketing],
      depends_on=[signal-ingest, signal-cluster, signal-synthesize],
      event_types=[signal.synthesis.ready]
- [ ] `feed-monitor/cartridge.py`: subscribes to `signal.synthesis.ready` (cross-domain
      bridge — see overview), maps to `domain.marketing.feed.synthesis_ready` domain events

### Task 3.3: Domain config entry

- [ ] `DomainConfig` block with guardian evaluation prompt focused on content quality,
      budget escalation thresholds, signal synthesis quality
- [ ] Autonomy defaults: content-pipeline -> `ask`, campaign-budget-monitor -> `ask`,
      feed-monitor -> `auto_notify`

---

## Phase 4: Creative Production Pillar

### Task 4.1: Event schemas

**File(s):** `teleclaude_events/schemas/creative_production.py`

- [ ] Create `register_creative_production(catalog)` function
- [ ] Register event schemas:
  - `domain.creative-production.asset.brief_created` — WORKFLOW, creates=True
  - `domain.creative-production.asset.draft_submitted` — WORKFLOW, updates=True,
    group_key=asset_id
  - `domain.creative-production.asset.review_requested` — WORKFLOW, updates=True,
    group_key=asset_id, actionable=True
  - `domain.creative-production.asset.revision_requested` — WORKFLOW, updates=True,
    group_key=asset_id
  - `domain.creative-production.asset.approved` — WORKFLOW, updates=True, group_key=asset_id
  - `domain.creative-production.asset.delivered` — WORKFLOW, resolves=True,
    group_key=asset_id
  - `domain.creative-production.format.transcode_started` — OPERATIONAL
  - `domain.creative-production.format.transcode_completed` — OPERATIONAL
  - `domain.creative-production.format.transcode_failed` — BUSINESS, actionable=True
- [ ] Wire `register_creative_production` into `register_all()`

### Task 4.2: Starter cartridges

**Directory structure:**
```
~/.teleclaude/company/domains/creative-production/cartridges/
  asset-lifecycle/
    manifest.yaml
    cartridge.py
  review-gatekeeper/
    manifest.yaml
    cartridge.py
```

- [ ] `asset-lifecycle/manifest.yaml`: id=asset-lifecycle,
      domain_affinity=[creative-production], depends_on=[],
      event_types=[domain.creative-production.asset.brief_created,
      domain.creative-production.asset.draft_submitted,
      domain.creative-production.asset.review_requested,
      domain.creative-production.asset.revision_requested,
      domain.creative-production.asset.approved,
      domain.creative-production.asset.delivered]
- [ ] `asset-lifecycle/cartridge.py`: subscribes to asset lifecycle events, tracks
      brief-to-delivery chain, notifies stakeholders at each gate
- [ ] `review-gatekeeper/manifest.yaml`: id=review-gatekeeper,
      domain_affinity=[creative-production], depends_on=[asset-lifecycle],
      event_types=[domain.creative-production.asset.review_requested]
- [ ] `review-gatekeeper/cartridge.py`: subscribes to `asset.review_requested`, routes
      to reviewer, enforces SLA timer

### Task 4.3: Domain config entry

- [ ] `DomainConfig` block with guardian prompt focused on asset quality standards,
      review cycle norms, multi-format awareness
- [ ] Autonomy defaults: asset-lifecycle -> `notify`, review-gatekeeper -> `ask`

---

## Phase 5: Customer Relations Pillar

### Task 5.1: Event schemas

**File(s):** `teleclaude_events/schemas/customer_relations.py`

- [ ] Create `register_customer_relations(catalog)` function
- [ ] Register event schemas — all with `domain: "customer-relations"`:
  - `domain.customer-relations.helpdesk.ticket_created` — WORKFLOW, creates=True
  - `domain.customer-relations.helpdesk.ticket_updated` — WORKFLOW, updates=True,
    group_key=ticket_id
  - `domain.customer-relations.helpdesk.ticket_escalated` — BUSINESS, updates=True,
    group_key=ticket_id, actionable=True
  - `domain.customer-relations.helpdesk.ticket_resolved` — WORKFLOW, resolves=True,
    group_key=ticket_id
  - `domain.customer-relations.satisfaction.survey_sent` — OPERATIONAL
  - `domain.customer-relations.satisfaction.response_received` — WORKFLOW
  - `domain.customer-relations.satisfaction.score_recorded` — WORKFLOW
  - `domain.customer-relations.escalation.triggered` — BUSINESS, actionable=True
  - `domain.customer-relations.escalation.acknowledged` — WORKFLOW, updates=True,
    group_key=escalation_id
  - `domain.customer-relations.escalation.resolved` — WORKFLOW, resolves=True,
    group_key=escalation_id
- [ ] Wire `register_customer_relations` into `register_all()`

### Task 5.2: Starter cartridges

**Directory structure:**
```
~/.teleclaude/company/domains/customer-relations/cartridges/
  helpdesk-triage/
    manifest.yaml
    cartridge.py
  escalation-handler/
    manifest.yaml
    cartridge.py
  satisfaction-tracker/
    manifest.yaml
    cartridge.py
```

- [ ] `helpdesk-triage/manifest.yaml`: id=helpdesk-triage,
      domain_affinity=[customer-relations], depends_on=[],
      event_types=[domain.customer-relations.helpdesk.ticket_created]
      Note in manifest metadata: `trust_required: strict`
- [ ] `helpdesk-triage/cartridge.py`: subscribes to `helpdesk.ticket_created`, classifies
      urgency, notifies on-call
- [ ] `escalation-handler/manifest.yaml`: id=escalation-handler,
      domain_affinity=[customer-relations], depends_on=[helpdesk-triage],
      event_types=[domain.customer-relations.helpdesk.ticket_escalated,
      domain.customer-relations.escalation.triggered]
      Note: `trust_required: strict`
- [ ] `escalation-handler/cartridge.py`: subscribes to `helpdesk.ticket_escalated` and
      `escalation.triggered`, notifies admin
- [ ] `satisfaction-tracker/manifest.yaml`: id=satisfaction-tracker,
      domain_affinity=[customer-relations], depends_on=[],
      event_types=[domain.customer-relations.satisfaction.response_received]
      Note: `trust_required: strict`
- [ ] `satisfaction-tracker/cartridge.py`: subscribes to `satisfaction.response_received`,
      aggregates scores, emits `satisfaction.score_recorded`

### Task 5.3: Domain config entry

- [ ] `DomainConfig` block under `event_domains.customer-relations` with
      `guardian.trust_threshold: strict`
- [ ] Guardian evaluation prompt: external input threat model, escalation decision criteria,
      customer data sensitivity, explicit instruction to require human confirmation
- [ ] Autonomy defaults: helpdesk-triage -> `ask`, escalation-handler -> `ask`,
      satisfaction-tracker -> `notify`

---

## Phase 6: Validation

### Task 6.1: Schema catalog audit

- [ ] Confirm all event type strings emitted by starter cartridges are registered in the
      catalog via `build_default_catalog()`
- [ ] Confirm existing 9 `domain.software-development.planning.*` and
      `domain.software-development.build.*` and `domain.software-development.review.*`
      emitters resolve without change
- [ ] Run `python -c "from teleclaude_events.catalog import build_default_catalog; c = build_default_catalog(); print(len(c.list_all()))"` —
      count must include all new domain events

### Task 6.2: Tests

**File(s):** `tests/teleclaude_events/test_domain_schemas.py`,
`tests/teleclaude_events/test_domain_cartridges.py`

- [ ] Schema registration: verify each domain module registers expected event types
- [ ] Existing schemas preserved: verify the 9 original software-development events still exist
- [ ] Cartridge manifest: validate each pillar's `manifest.yaml` files parse correctly
      (once `CartridgeManifest` is available from infrastructure)
- [ ] Config seeding: verify domain config blocks are valid `DomainConfig` structures
- [ ] Run `make test`

### Task 6.3: Documentation

- [ ] Each schema module (`marketing.py`, `creative_production.py`, `customer_relations.py`)
      has a module-level docstring describing the pillar's event taxonomy
- [ ] Each cartridge manifest `description` field explains what the cartridge does
- [ ] Schema modules and manifests serve as the primary documentation (no separate docs)

### Task 6.4: Quality checks

- [ ] Run `make lint`
- [ ] Verify no starter cartridge uses wildcard event subscriptions
- [ ] Verify no duplicate event type strings across pillar schema modules
- [ ] Verify naming convention consistency: `domain.{slug}.{category}.{action}`

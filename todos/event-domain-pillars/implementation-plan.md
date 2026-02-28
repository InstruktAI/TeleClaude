# Implementation Plan: event-domain-pillars

## Overview

Deliver four domain pillar configurations as pure data artifacts — schemas, cartridges, guardian configs, and init manifests. No runtime changes required; all runtime machinery (domain pipeline, cartridge loader, trust evaluator, signal pipeline) is built in upstream phases. This phase is content, not plumbing.

Work is organized into six phases: shared infrastructure first, then one phase per pillar, then validation. Pillar phases (2–5) are independent of each other and can be parallelized.

---

## Phase 1: Shared Schema Infrastructure

### Task 1.1: Base domain event model

**File(s):** `teleclaude_events/schemas/domain/__init__.py`, `teleclaude_events/schemas/domain/base.py`

- [ ] Create `domain/` subpackage under `teleclaude_events/schemas/`
- [ ] Define `DomainEvent(EventEnvelope)` base model: adds `domain: str`, `entity_id: str`, `entity_type: str` fields
- [ ] Define `DomainEventPhase` enum: `created`, `updated`, `completed`, `failed`, `cancelled`
- [ ] Export from `teleclaude_events/schemas/__init__.py`

### Task 1.2: Guardian config schema

**File(s):** `teleclaude_events/schemas/domain/guardian_config.py`

- [ ] Define `GuardianConfig` Pydantic model: `domain`, `model`, `system_prompt_path`, `autonomy_defaults: dict[str, AutonomyLevel]`, `trust_threshold: TrustLevel`
- [ ] Define `AutonomyLevel` enum: `notify`, `ask`, `act`
- [ ] Define `TrustLevel` enum: `standard`, `strict`, `permissive`
- [ ] Add YAML loader: `GuardianConfig.from_yaml(path)` — used by domain pipeline on startup

### Task 1.3: `telec init` domain discovery manifest schema

**File(s):** `teleclaude_events/schemas/domain/init_manifest.py`

- [ ] Define `DomainInitEntry` model: `name`, `display_name`, `description`, `cartridges: list[str]`, `depends_on: list[str]`
- [ ] Define `DomainInitManifest` model: root list of `DomainInitEntry`
- [ ] Ensure manifest loader in `telec init` can consume this schema (wire hook or document integration point)

---

## Phase 2: Software Development Pillar

### Task 2.1: Event schemas

**File(s):** `teleclaude_events/schemas/domain/software_development.py`

- [ ] Define event types covering: `todo.*` (created, dor_assessed, work_started, work_completed, delivered), `build.*` (started, passed, failed), `review.*` (requested, approved, changes_requested), `deploy.*` (triggered, succeeded, failed), `ops.*` (alert_fired, alert_resolved), `maintenance.*` (dependency_update, security_patch)
- [ ] Each event type is a `DomainEvent` subclass with domain-specific payload fields
- [ ] Register all types in `teleclaude_events/catalog.py`
- [ ] Confirm existing `todo.dor_assessed` emitter resolves against new schema without change

### Task 2.2: Starter cartridges

**File(s):** `company/domains/software-development/cartridges/todo-lifecycle.py`, `company/domains/software-development/cartridges/build-notifier.py`, `company/domains/software-development/cartridges/deploy-tracker.py`

- [ ] `todo-lifecycle`: subscribes to `todo.*`, emits downstream state transitions, notifies on `dor_assessed` and `work_completed`
- [ ] `build-notifier`: subscribes to `build.failed`, notifies assigned developer via Telegram
- [ ] `deploy-tracker`: subscribes to `deploy.*`, maintains a rolling deploy log entry, notifies on failure

### Task 2.3: Guardian AI config

**File(s):** `company/domains/software-development/guardian.yaml`

- [ ] Set `model: claude-sonnet-4-6`, `trust_threshold: standard`
- [ ] Set `autonomy_defaults`: todo-lifecycle → `act`, build-notifier → `notify`, deploy-tracker → `notify`
- [ ] Set `system_prompt_path: prompts/software-development-guardian.md`

### Task 2.4: Guardian system prompt

**File(s):** `company/domains/software-development/prompts/software-development-guardian.md`

- [ ] Write prompt framing: domain context, cartridge submission review criteria, pattern detection focus (repeated build failures, stalled todos)
- [ ] Include autonomy decision heuristics for this domain

### Task 2.5: `telec init` manifest entry

**File(s):** `company/domains/software-development/init.yaml`

- [ ] Declare `name: software-development`, cartridge list, no `depends_on` (self-contained)
- [ ] Include one-line description for `telec init` listing output

---

## Phase 3: Marketing Pillar

### Task 3.1: Event schemas

**File(s):** `teleclaude_events/schemas/domain/marketing.py`

- [ ] Define event types: `content.*` (brief_created, draft_ready, published, performance_reported), `campaign.*` (launched, budget_threshold_hit, ended, report_ready), `feed.*` (signal_received, cluster_formed, synthesis_ready — wraps signal pipeline events into domain context)
- [ ] Register all types in `teleclaude_events/catalog.py`

### Task 3.2: Starter cartridges

**File(s):** `company/domains/marketing/cartridges/content-publication-pipeline.py`, `company/domains/marketing/cartridges/campaign-budget-monitor.py`, `company/domains/marketing/cartridges/feed-monitor.py`

- [ ] `content-publication-pipeline`: subscribes to `content.brief_created`, orchestrates draft → review → publish lifecycle transitions, notifies on `published`
- [ ] `campaign-budget-monitor`: subscribes to `campaign.budget_threshold_hit`, evaluates spend rate, notifies or asks depending on autonomy level
- [ ] `feed-monitor`: subscribes to `signal.synthesis.ready` (from signal pipeline), maps synthesis artifacts to `feed.synthesis_ready` domain events; declare `depends_on: [signal-ingest, signal-cluster, signal-synthesize]`

### Task 3.3: Guardian AI config

**File(s):** `company/domains/marketing/guardian.yaml`

- [ ] Set `model: claude-sonnet-4-6`, `trust_threshold: standard`
- [ ] Set `autonomy_defaults`: content-publication-pipeline → `ask`, campaign-budget-monitor → `ask`, feed-monitor → `act`
- [ ] Set `system_prompt_path: prompts/marketing-guardian.md`

### Task 3.4: Guardian system prompt

**File(s):** `company/domains/marketing/prompts/marketing-guardian.md`

- [ ] Write prompt framing: content quality standards, budget escalation thresholds, signal synthesis quality criteria
- [ ] Include heuristics for distinguishing signal noise from actionable feed clusters

### Task 3.5: `telec init` manifest entry

**File(s):** `company/domains/marketing/init.yaml`

- [ ] Declare `name: marketing`, cartridge list, `depends_on: [signal-ingest, signal-cluster, signal-synthesize]`
- [ ] Include one-line description

---

## Phase 4: Creative Production Pillar

### Task 4.1: Event schemas

**File(s):** `teleclaude_events/schemas/domain/creative_production.py`

- [ ] Define event types covering asset lifecycle: `asset.*` (brief_created, draft_submitted, review_requested, revision_requested, approved, delivered), `format.*` (transcode_started, transcode_completed, transcode_failed)
- [ ] Include `asset_format: str` field on all `asset.*` events (image, video, audio, copy, design)
- [ ] Register all types in `teleclaude_events/catalog.py`

### Task 4.2: Starter cartridges

**File(s):** `company/domains/creative-production/cartridges/asset-lifecycle.py`, `company/domains/creative-production/cartridges/review-gatekeeper.py`

- [ ] `asset-lifecycle`: subscribes to `asset.*`, tracks brief-to-delivery chain, notifies stakeholders at each gate
- [ ] `review-gatekeeper`: subscribes to `asset.review_requested`, routes to reviewer, enforces SLA timer, escalates on overdue

### Task 4.3: Guardian AI config

**File(s):** `company/domains/creative-production/guardian.yaml`

- [ ] Set `model: claude-sonnet-4-6`, `trust_threshold: standard`
- [ ] Set `autonomy_defaults`: asset-lifecycle → `notify`, review-gatekeeper → `ask`
- [ ] Set `system_prompt_path: prompts/creative-production-guardian.md`

### Task 4.4: Guardian system prompt

**File(s):** `company/domains/creative-production/prompts/creative-production-guardian.md`

- [ ] Write prompt framing: asset quality standards, review cycle norms, escalation criteria for blocked assets
- [ ] Include multi-format awareness (different SLA expectations per format)

### Task 4.5: `telec init` manifest entry

**File(s):** `company/domains/creative-production/init.yaml`

- [ ] Declare `name: creative-production`, cartridge list, no signal pipeline dependency
- [ ] Include one-line description

---

## Phase 5: Customer Relations Pillar

### Task 5.1: Event schemas

**File(s):** `teleclaude_events/schemas/domain/customer_relations.py`

- [ ] Define event types: `helpdesk.*` (ticket_created, ticket_updated, ticket_escalated, ticket_resolved), `satisfaction.*` (survey_sent, response_received, score_recorded), `escalation.*` (triggered, acknowledged, resolved)
- [ ] Tag all external-origin events with `origin: external` field (enforces trust evaluator path)
- [ ] Register all types in `teleclaude_events/catalog.py`

### Task 5.2: Starter cartridges

**File(s):** `company/domains/customer-relations/cartridges/helpdesk-triage.py`, `company/domains/customer-relations/cartridges/escalation-handler.py`, `company/domains/customer-relations/cartridges/satisfaction-tracker.py`

- [ ] `helpdesk-triage`: subscribes to `helpdesk.ticket_created`, classifies urgency, notifies on-call; tagged `trust_required: strict`
- [ ] `escalation-handler`: subscribes to `helpdesk.ticket_escalated` and `escalation.triggered`, notifies admin, creates Telegram escalation message; tagged `trust_required: strict`
- [ ] `satisfaction-tracker`: subscribes to `satisfaction.response_received`, aggregates scores, emits `satisfaction.score_recorded`; tagged `trust_required: strict`

### Task 5.3: Guardian AI config

**File(s):** `company/domains/customer-relations/guardian.yaml`

- [ ] Set `model: claude-sonnet-4-6`, `trust_threshold: strict`
- [ ] Set `autonomy_defaults`: helpdesk-triage → `ask`, escalation-handler → `ask`, satisfaction-tracker → `notify`
- [ ] Set `system_prompt_path: prompts/customer-relations-guardian.md`

### Task 5.4: Guardian system prompt

**File(s):** `company/domains/customer-relations/prompts/customer-relations-guardian.md`

- [ ] Write prompt framing: external input threat model, escalation decision criteria, customer data sensitivity
- [ ] Explicitly instruct guardian to treat all external input as untrusted and to require human confirmation before acting

### Task 5.5: `telec init` manifest entry

**File(s):** `company/domains/customer-relations/init.yaml`

- [ ] Declare `name: customer-relations`, cartridge list, no signal pipeline dependency
- [ ] Flag `external_input: true` in manifest so `telec init` surfaces the trust caveat to the installer

---

## Phase 6: Validation

### Task 6.1: Schema catalog audit

**File(s):** `teleclaude_events/catalog.py`, `teleclaude_events/schemas/domain/software_development.py`, `marketing.py`, `creative_production.py`, `customer_relations.py`

- [ ] Confirm all emitted event type strings in starter cartridges are registered in the catalog
- [ ] Confirm existing `todo.dor_assessed` emitter in `teleclaude/core/` resolves without change
- [ ] Run `python -c "from teleclaude_events.catalog import EVENT_CATALOG; print(len(EVENT_CATALOG))"` — count must include all new domain events

### Task 6.2: Tests

**File(s):** `tests/events/domain/test_software_development.py`, `test_marketing.py`, `test_creative_production.py`, `test_customer_relations.py`, `tests/events/domain/test_guardian_config.py`

- [ ] Schema instantiation: one valid and one invalid instance per domain schema module
- [ ] Cartridge handler dispatch: mock event bus, assert correct handler called for each subscribed event type
- [ ] Guardian config loading: assert `GuardianConfig.from_yaml()` parses each pillar's `guardian.yaml` correctly
- [ ] Trust threshold enforcement: assert customer relations cartridges reject events without `trust_required: strict` metadata
- [ ] Run `make test`

### Task 6.3: Quality checks

- [ ] Run `make lint`
- [ ] Verify no starter cartridge uses wildcard event subscriptions
- [ ] Verify all four `init.yaml` files parse against `DomainInitEntry` schema
- [ ] Verify no unchecked implementation tasks remain

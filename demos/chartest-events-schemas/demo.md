# Demo: chartest-events-schemas

## Validation

Run the characterization tests and confirm they all pass:

```bash
.venv/bin/pytest tests/unit/events/schemas/ tests/unit/events/delivery/ tests/unit/events/signal/ -q
```

Show the full test count breakdown:

```bash
.venv/bin/pytest tests/unit/events/schemas/ tests/unit/events/delivery/ tests/unit/events/signal/ -v --tb=no -q 2>&1 | tail -5
```

## Guided Presentation

The characterization tests pin current behavior of 19 source files across three subsystems:

**Event Schemas** (`tests/unit/events/schemas/`): 11 test files covering registration functions
for content, creative production, customer relations, deployment, marketing, node, notification,
schema evolution, signal, software development, and system event schemas. Each test verifies
which event types get registered, their domain, level, visibility, lifecycle contracts, and
actionable flags.

**Delivery Adapters** (`tests/unit/events/delivery/`): 3 test files covering Discord, Telegram,
and WhatsApp adapters. Tests verify the routing logic — `was_created` gating, `min_level`
filtering, exception swallowing, and correct channel routing.

**Signal Pipeline** (`tests/unit/events/signal/`): 5 test files covering the signal protocol
(`SynthesisArtifact`, `SignalAIClient`), clustering algorithms (`group_by_tags`,
`refine_by_embeddings`, `detect_burst`, `detect_novelty`, `build_cluster_key`), RSS/Atom feed
parsing, ingest scheduling, and source configuration loading.

All 164 tests pass immediately — this is expected and correct for characterization testing.
The mutation check property is preserved: each test would catch a specific class of real bugs
in the production code it covers.

# Implementation Plan: chartest-events-core

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/events/cartridge_loader.py` → `tests/unit/events/test_cartridge_loader.py`
- [ ] Characterize `teleclaude/events/cartridge_manifest.py` → `tests/unit/events/test_cartridge_manifest.py`
- [ ] Characterize `teleclaude/events/catalog.py` → `tests/unit/events/test_catalog.py`
- [ ] Characterize `teleclaude/events/domain_config.py` → `tests/unit/events/test_domain_config.py`
- [ ] Characterize `teleclaude/events/domain_pipeline.py` → `tests/unit/events/test_domain_pipeline.py`
- [ ] Characterize `teleclaude/events/domain_registry.py` → `tests/unit/events/test_domain_registry.py`
- [ ] Characterize `teleclaude/events/domain_seeds.py` → `tests/unit/events/test_domain_seeds.py`
- [ ] Characterize `teleclaude/events/envelope.py` → `tests/unit/events/test_envelope.py`
- [ ] Characterize `teleclaude/events/personal_pipeline.py` → `tests/unit/events/test_personal_pipeline.py`
- [ ] Characterize `teleclaude/events/pipeline.py` → `tests/unit/events/test_pipeline.py`
- [ ] Characterize `teleclaude/events/processor.py` → `tests/unit/events/test_processor.py`
- [ ] Characterize `teleclaude/events/producer.py` → `tests/unit/events/test_producer.py`
- [ ] Characterize `teleclaude/events/schema_export.py` → `tests/unit/events/test_schema_export.py`
- [ ] Characterize `teleclaude/events/startup.py` → `tests/unit/events/test_startup.py`

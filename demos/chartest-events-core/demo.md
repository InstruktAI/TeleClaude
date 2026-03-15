# Demo: chartest-events-core

## Validation

Run the new characterization tests to prove they pass on the current codebase:

```bash
.venv/bin/pytest tests/unit/events/test_cartridge_manifest.py tests/unit/events/test_envelope.py tests/unit/events/test_catalog.py tests/unit/events/test_domain_config.py tests/unit/events/test_domain_registry.py tests/unit/events/test_domain_seeds.py tests/unit/events/test_cartridge_loader.py tests/unit/events/test_pipeline.py tests/unit/events/test_domain_pipeline.py tests/unit/events/test_personal_pipeline.py tests/unit/events/test_processor.py tests/unit/events/test_producer.py tests/unit/events/test_schema_export.py tests/unit/events/test_startup.py -v --tb=short -q 2>&1 | tail -20
```

Show total count of new test files:

```bash
ls tests/unit/events/test_cartridge_manifest.py tests/unit/events/test_envelope.py tests/unit/events/test_catalog.py tests/unit/events/test_domain_config.py tests/unit/events/test_domain_registry.py tests/unit/events/test_domain_seeds.py tests/unit/events/test_cartridge_loader.py tests/unit/events/test_pipeline.py tests/unit/events/test_domain_pipeline.py tests/unit/events/test_personal_pipeline.py tests/unit/events/test_processor.py tests/unit/events/test_producer.py tests/unit/events/test_schema_export.py tests/unit/events/test_startup.py | wc -l
```

## Guided Presentation

This delivery adds 14 characterization test files for the events pipeline core modules.
Each test file pins the observable behavior of one source module at its public API boundary,
creating a safety net for future refactoring.

The tests follow the OBSERVE-ASSERT-VERIFY pattern:

- Each test asserts a concrete behavior that was observed by reading the source
- Each test would catch a real bug in the production code if that behavior changed

Key coverage highlights:

- `test_envelope.py`: Full roundtrip through `to_stream_dict` / `from_stream_dict` including extra fields
- `test_catalog.py`: Idempotency key construction and duplicate registration guard
- `test_cartridge_loader.py`: DAG resolution, cycle detection, scope validation
- `test_domain_config.py`: Autonomy resolution priority (event_type > cartridge > domain > global)
- `test_pipeline.py`: Fire-and-forget domain fanout behavior
- `test_processor.py`: BUSYGROUP error tolerance on startup
- `test_startup.py`: Graceful domain skip on CartridgeError

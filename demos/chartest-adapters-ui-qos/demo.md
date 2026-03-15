# Demo: chartest-adapters-ui-qos

## Validation

```bash
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/chartest-adapters-ui-qos
.venv/bin/pytest tests/unit/adapters/ -q --tb=short
```

## Guided Presentation

The characterization test suite covers six adapter modules:

- `ui_adapter.py` — base adapter class with delivery locks, lifecycle formatting, and session ID helpers
- `ui/output_delivery.py` — edit-in-place output delivery, footer management, dedup logic
- `ui/threaded_output.py` — append-only threaded message delivery with overflow pagination
- `qos/output_scheduler.py` — coalescing output scheduler with fair round-robin dispatch
- `qos/policy.py` — per-adapter QoS policy dataclasses and factory functions
- `whatsapp_adapter.py` — WhatsApp Cloud API adapter with chunking, markdown conversion, and rate-limit retry

Run the tests to confirm all 153 characterization tests pass against the current codebase.

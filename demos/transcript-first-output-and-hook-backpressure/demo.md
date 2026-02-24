# Demo: transcript-first-output-and-hook-backpressure

## Validation

<!-- Bash code blocks that prove the feature works. -->
<!-- Each block is run by `telec todo demo transcript-first-output-and-hook-backpressure` as a build gate - all must exit 0. -->

```bash
# 1) Baseline health + demo artifact validation
make status
telec todo demo validate transcript-first-output-and-hook-backpressure
```

Expected:

- Daemon reports healthy status.
- Demo artifact is structurally valid.

```bash
# 2) Validate single-producer + control-plane behavior
pytest tests/unit/test_agent_coordinator.py tests/unit/test_threaded_output_updates.py tests/unit/test_polling_coordinator.py tests/unit/test_agent_activity_events.py -q
```

Expected:

- No duplicate-output regressions from dual producer paths.
- Hook activity events remain available for control-plane/UI concerns.
- Cadence/final-flush behavior remains covered by regression tests.

```bash
# 3) Validate bounded queue/coalescing path in daemon/hook pipeline
pytest tests/unit/test_daemon.py tests/unit/test_hook_receiver.py -q
```

## Guided Presentation

<!-- Walk through the delivery step by step. For each step: what to do, what to observe, why it matters. -->
<!-- The AI presenter reads this top-to-bottom and executes. Write it as a continuous sequence. -->

1. Start with `make status` and demo validation to establish a clean baseline.
2. Run focused output/control-plane tests to prove no dual-producer regressions.
3. Run daemon/hook tests to verify bounded processing and coalescing behavior under bursty conditions.
4. Optional runtime spot-check: `instrukt-ai-logs teleclaude --since 15m --grep "coalesc|queue|lag|output"` after a busy session.

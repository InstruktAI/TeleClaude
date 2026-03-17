# Demo: fix-integration-queue-ghost

## Validation

Confirm the TTL guard is gone from the scanner:

```bash
# The constant definition (line 44) and lease acquisition (line 396) are the only
# two valid references. Any other occurrence means the TTL guard leaked back in.
count=$(grep -c "INTEGRATION_LEASE_TTL_SECONDS" teleclaude/core/integration/step_functions.py)
if [ "$count" -ne 2 ]; then
  echo "FAIL: expected exactly 2 references to INTEGRATION_LEASE_TTL_SECONDS, found $count"
  grep -n "INTEGRATION_LEASE_TTL_SECONDS" teleclaude/core/integration/step_functions.py
  exit 1
fi
echo "PASS: TTL constant referenced only at definition and lease acquisition — scanner is clean"
```

Confirm `IntegrationQueue.enqueue` is no longer called from the daemon:

```bash
if grep -n "integration_queue.enqueue" teleclaude/daemon_event_platform.py; then
  echo "FAIL: enqueue call still present"
  exit 1
fi
echo "PASS: queue.json enqueue removed from daemon wiring"
```

Run the targeted integration scanner tests:

```bash
python -m pytest tests/unit/core/integration/test_auto_enqueue.py -v 2>&1 | tail -30
```

## Guided Presentation

1. **The ghost problem**: Every slug finalized by the event chain was immediately written to
   `handed_off` status. The scanner skipped any `handed_off` candidate younger than the lease
   TTL (120 s), so freshly finalized slugs were invisible to the integrator forever.

2. **The fix**: Two surgical changes — the daemon no longer enqueues into `queue.json`
   (the state-driven scanner is the source of truth), and the scanner now accepts `handed_off`
   candidates unconditionally. The lease already prevents concurrent processing.

3. **Run the tests** to see `test_scan_accepts_fresh_handed_off` pass — the same scenario
   that previously proved the ghost bug now proves the fix.

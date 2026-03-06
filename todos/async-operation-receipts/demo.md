# Demo: async-operation-receipts

## Validation

```bash
# Submit a long-running work item and confirm the API path returns a receipt quickly.
telec todo work my-slug
```

```bash
# Query the durable operation record directly.
telec operations get <operation_id>
```

```bash
# Re-submit the same logical request and confirm the system returns the same
# operation rather than running the state machine twice.
telec todo work my-slug
```

## Guided Presentation

Run `telec todo work` for a slug that would previously keep the HTTP request open for a long time.
Observe that the caller receives a durable operation handle quickly instead of depending on one
long API request. Then inspect the operation directly and show that progress is visible while the
work is still running. Finally, demonstrate that the terminal result preserves the same caller-facing
decision payload that `next_work()` returns today. If the CLI auto-waits by default in the final
design, interrupt it once and show that the recovery handle is sufficient to resume observation
without rerunning the workflow.

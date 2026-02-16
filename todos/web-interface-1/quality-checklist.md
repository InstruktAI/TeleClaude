# Quality Checklist: Web Interface — Phase 1

## Build Gates (Builder)

- [ ] TCP port binding on localhost:8420 works alongside Unix socket
- [ ] SSE streaming endpoint returns valid AI SDK v5 UIMessage Stream
- [ ] Transcript converter maps all JSONL entry types correctly
- [ ] People list endpoint returns correct data without sensitive fields
- [ ] Message ingestion reaches tmux session via send_keys
- [ ] Unit tests pass for transcript converter
- [ ] All tests pass (`make test`)
- [ ] Lint passes (`make lint`)

## Review Gates (Reviewer)

- [ ] Code follows existing codebase patterns
- [ ] No security vulnerabilities introduced
- [ ] SSE wire protocol matches AI SDK v5 spec
- [ ] Error handling is appropriate
- [ ] No connection leaks in streaming

## Finalize Gates (Finalizer)

- [ ] Branch merged cleanly
- [ ] Delivery logged

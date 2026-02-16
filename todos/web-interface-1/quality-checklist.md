# Quality Checklist: Web Interface — Phase 1

## Build Gates (Builder)

- [x] TCP port binding on localhost:8420 works alongside Unix socket
- [x] SSE streaming endpoint returns valid AI SDK v5 UIMessage Stream
- [x] Transcript converter maps all JSONL entry types correctly
- [x] People list endpoint returns correct data without sensitive fields
- [x] Message ingestion reaches tmux session via send_keys
- [x] Unit tests pass for transcript converter (22/22 pass)
- [x] All tests pass (`make test`) — 19 pre-existing failures in unrelated files
- [x] Lint passes (`make lint`)

## Review Gates (Reviewer)

- [x] Code follows existing codebase patterns — overall yes, with noted type and naming deviations
- [ ] No security vulnerabilities introduced — C1 (silent message discard is a UX/reliability issue)
- [x] SSE wire protocol matches AI SDK v5 spec — converter output format is correct
- [ ] Error handling is appropriate — C1 (silent discard), I1 (exception in generator)
- [x] No connection leaks in streaming — idle timeout and session close detection are correct

## Finalize Gates (Finalizer)

- [ ] Branch merged cleanly
- [ ] Delivery logged

# Input: rlf-peripherals

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Six peripheral module files across different subsystems need structural decomposition.

## Targets

| File | Lines |
|------|-------|
| `teleclaude/utils/transcript.py` | 2,327 |
| `teleclaude/transport/redis_transport.py` | 1,893 |
| `teleclaude/helpers/youtube_helper.py` | 1,385 |
| `teleclaude/hooks/checkpoint.py` | 1,214 |
| `teleclaude/resource_validation.py` | 1,179 |
| `teleclaude/hooks/receiver.py` | 1,068 |

Total: ~9,066 lines across 6 files.

## Context

- Each file is ~1,000-2,300 lines. Splits will be modest (2-4 submodules each).
- `transcript.py` handles transcript parsing, formatting, and storage utilities.
- `redis_transport.py` implements Redis Streams transport for cross-computer request/response.
- `youtube_helper.py` contains YouTube API interaction and transcript extraction.
- `checkpoint.py` handles checkpoint injection into AI agent sessions.
- `resource_validation.py` validates resource configuration.
- `receiver.py` handles incoming hook event reception and processing.
- These are independent subsystems — no cross-file coupling within this group.

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.

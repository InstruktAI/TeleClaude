# origin-metadata-rename — Requirements

## Problem Statement

The naming convergence from `channel_metadata` to `origin_metadata` in the
command pipeline remains incomplete. The per-request payload carrying
platform-specific identity signals is `channel_metadata` in adapters, Redis
transport, fanout, and `CommandMapper`, but `origin_metadata` in the session
model and API layer.

## Requirements

### R4: Rename `channel_metadata` to `origin_metadata` in the command pipeline

Complete the naming convergence documented in the layer-ownership architecture.

**Success criteria:**

- `MessageMetadata` uses a single field for per-request platform identity
  signals, named consistently with the architecture's terminology.
- The deprecated `channel_metadata` field on `MessageMetadata` is removed.
- All callers that wrote to `channel_metadata` (Telegram adapters, Discord
  gateway, WhatsApp handler, and their tests) are updated to use the
  converged name.
- The `CommandMapper` mapping from `MessageMetadata` to
  `CreateSessionCommand` remains correct after the rename.
- `RedisTransportMetadata` is updated, with backward compatibility for
  existing serialized data.

### R5: Behavioral preservation (rename-specific)

All existing behavior that flows through `channel_metadata` must be
preserved after the rename.

**Success criteria:**

- Actor extraction via `CommandMapper._extract_actor` produces identical
  results when reading from `origin_metadata` as it did from
  `channel_metadata`.
- Redis transport metadata round-trips correctly with both old and new
  key names.
- Fanout reflection metadata propagation continues to carry actor identity
  for cross-session reflection.
- Telegram message processing continues to extract correct actor identity
  (user_id, user_name) from per-message metadata.

## Deferred / Out of scope

- **Layer-ownership documentation updates** — architecture docs reference
  both names; documentation updates are tracked separately.

## Verification strategy

- Pre-commit hooks (lint, typecheck, tests) must pass.
- `grep -r "channel_metadata" teleclaude/` returns zero production code hits
  after completion.
- Actor extraction, Redis transport round-trip, and fanout reflection tests
  verify behavioral preservation beyond grep.

# DOR Report: help-desk-control-room

## Draft Assessment

**Status:** Draft — not yet formally gated.

## Gate Analysis

### 1. Intent & Success — Strong

The problem and outcome are explicit: Discord-based admin control room for unified session observation and intervention. Success criteria are concrete (thread creation, output mirroring, admin input routing, thread lifecycle). The "what" and "why" are captured in the roadmap entry and refined in requirements.

### 2. Scope & Size — Needs Attention

The work touches config, adapter metadata, Discord adapter (create/update/close/message handling), database queries, and tests. All changes are localized to the Discord adapter and its supporting infrastructure. Fits a single AI session.

**Risk:** The dual-thread output routing (help desk thread + control room thread) adds complexity to `send_output_update`. May need careful handling to avoid blocking or rate limit issues.

### 3. Verification — Strong

Each requirement has a clear test strategy:

- Thread creation: unit test with mock Discord client
- Output mirroring: unit test for dual-thread delivery
- Admin intervention: unit test for message routing from control room thread
- Graceful degradation: unit test with `control_room_channel_id = None`
- Lifecycle: unit tests for title sync, close, delete

### 4. Approach Known — Strong

Three proven codebase patterns cover the entire scope:

1. Telegram supergroup topic pattern (per-session topic, admin message routing)
2. Discord help desk forum pattern (thread creation in forum channel)
3. AdapterClient observer broadcast (fan-out output delivery)

No new architectural patterns needed. The implementation is a composition of existing patterns.

### 5. Research — Needs Verification

Discord forum channel capabilities (tags, thread creation in forums) are used in the existing help desk implementation. However:

- **Forum tag management via discord.py** — Need to verify how to create/list/apply forum tags programmatically. The existing codebase uses `discord.py` but may not yet use tag APIs.
- **Thread creation rate limits** — Discord imposes per-guild rate limits on thread creation. Need to verify limits are acceptable for session creation frequency.

### 6. Dependencies & Preconditions — Open Question

`dependencies.json` lists both `help-desk-discord` and `help-desk-whatsapp` as dependencies. The roadmap says `after: help-desk-discord` only.

**Question:** Is the `help-desk-whatsapp` dependency correct? The control room mirrors ALL sessions regardless of adapter, so it doesn't strictly depend on WhatsApp being implemented. The dependency may be overly strict. Consider removing the WhatsApp dependency if it blocks scheduling.

### 7. Integration Safety — Strong

- Changes are additive: new config field, new metadata field, new behavior behind a config gate
- `control_room_channel_id = None` (default) disables all new behavior
- Existing help desk and escalation flows are untouched
- Rollback: remove config value to disable

### 8. Tooling Impact — N/A

No tooling or scaffolding changes.

## Assumptions

1. The Discord adapter is fully functional for help desk sessions before this work starts (depends on `help-desk-discord`)
2. The `discord.py` library supports forum tag management (create, list, apply to threads)
3. Discord's per-guild rate limits on thread creation are sufficient for expected session volumes
4. One control room forum channel is enough (no need for per-project or per-computer separation)

## Open Questions

1. **WhatsApp dependency:** Should `help-desk-whatsapp` remain as a blocker, or can the control room proceed independently? The control room works regardless of which adapters are enabled.
2. **Forum tag API:** Does `discord.py` expose forum tag creation/management, or do tags need to be created manually by the admin?
3. **Output format in control room:** Should control room threads show raw tmux output or formatted output? The Telegram supergroup shows the same formatted output as the user sees.
4. **Thread archival policy:** When sessions end (72h sweep), should control room threads be archived (hidden but retrievable) or deleted? Archival preserves history; deletion keeps the forum clean.

## Blockers

None identified — all open questions have reasonable defaults that can be resolved during implementation.

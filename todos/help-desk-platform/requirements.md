# Requirements: help-desk-platform

## Goal

Turn TeleClaude into a two-plane help desk platform — customer ingress on any adapter (Discord, Telegram, WhatsApp, web), operator workspace on Discord — with identity-scoped memory, escalation tooling, admin relay channels, internal pub/sub channels, and a standalone operator workspace.

## Scope

### In scope

- Identity-scoped memory (identity_key on memory_observations, per-customer continuity)
- Identity resolution for Discord (person config lookup via discord_user_id)
- Telegram adapter metadata fix (persist user_id for identity derivation)
- Customer role in MCP (CUSTOMER_EXCLUDED_TOOLS tier, escalation tool gating)
- Audience-tagged doc snippets (frontmatter audience field, role-filtered get_context)
- Session schema extensions (bookkeeping timestamps, relay state fields)
- Identity-aware context injection (SessionStart hook threads identity_key)
- Help desk bootstrap routine (idempotent scaffold from templates, telec init)
- Organization doc domain (docs/global/organization/ symlinked to ~/.teleclaude/docs/organization/)
- /author-knowledge global command (conversational brain-dump to structured docs)
- Internal channels (Redis Streams pub/sub with consumer groups, MCP publish tool)
- Customer session lifecycle (idle compaction without termination, 72h sweep only)
- Memory extraction job (dual-lens: personal + business, incremental from last marker)
- Intelligence job (daily digest, pattern detection across sessions)
- Operator brain template (AGENTS.master.md with persona, escalation awareness, idle routines)
- Escalation tool (teleclaude\_\_escalate MCP handler, Discord thread creation, relay activation)
- Admin relay channel (message routing diversion, admin-to-customer forwarding, @agent handback with context injection)

### Out of scope

- WhatsApp adapter implementation (future work, platform-agnostic design supports it)
- Web adapter customer ingress (future work)
- Billing integration or payment processing
- Multi-tenant isolation (single-org deployment assumed)
- Customer self-service portal or dashboard
- Real-time analytics dashboard

## Success Criteria

- [ ] Customer messages on Discord/Telegram create identity-scoped sessions with personal memory continuity
- [ ] Identity resolution maps known Discord/Telegram users to configured roles; unknown users default to customer
- [ ] Customer sessions see only customer-appropriate MCP tools (escalation visible, admin tools hidden)
- [ ] Doc snippets respect audience tags — customers see only public/help-desk content
- [ ] Escalation tool creates Discord relay thread and activates relay mode on session
- [ ] Admin messages in relay thread are delivered to customer on their originating platform
- [ ] @agent handback collects relay messages, injects context into AI session, clears relay
- [ ] Idle compaction extracts memories then compacts without killing customer sessions
- [ ] Memory extraction job processes transcripts incrementally with idempotent bookkeeping
- [ ] Internal channels publish/consume via Redis Streams with exactly-once consumer groups
- [ ] Help desk bootstrap creates standalone workspace from templates via telec init
- [ ] Operator brain defines customer-facing persona with escalation awareness and idle routines

## Constraints

- Single memory_observations table — identity_key is an additional column, not a separate store
- Extract-before-compact invariant — memory extraction MUST complete before /compact injection
- Customer sessions have no idle timeout — only 72h inactivity sweep terminates them
- Relay diverts, not duplicates — customer messages go to relay thread ONLY during active relay
- Escalation tool is customer-scoped — excluded from all non-customer role tiers
- Help desk workspace is standalone git repo — not a TeleClaude subdirectory
- Claude is the only model for customer-facing sessions — not configurable

## Risks

- Redis unavailability degrades channels but memory (SQLite) continues to work
- Identity resolution failure falls back to customer role without personal memory injection
- Escalation with Discord unavailable returns error to AI; customer informed but not escalated
- @agent tag missed or malformed keeps relay active; manual API clear is the recovery path

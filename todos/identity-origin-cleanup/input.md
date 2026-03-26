# identity-origin-cleanup — Input

Identity propagation + channel_metadata cleanup + origin metadata normalization

Child sessions spawned by daemon-created orchestrators lose human identity. The IdentityResolver.resolve() defaults to customer when it can't identify the caller, which prevents parent identity inheritance. This causes worker sessions to be routed to the help desk in Discord.

Additionally, channel_metadata has grown from an edge-only platform signal payload into a grab bag carrying internal routing fields (initiator_session_id, working_slug, email). This violates layer ownership: channel_metadata should be consumed at the edge, merged into origin_metadata, and discarded.

Phase 1 (done): Identity resolver returns empty instead of customer default. Fail fast on unidentified sessions.

Phase 2: Remove working_slug — derive from subdir convention (trees/{slug}). Remove from CreateSessionCommand, command_mapper, session creation handler, API routes.

Phase 3: Remove internal fields from channel_metadata — initiator_session_id, subfolder, email injection. Use first-class command fields. Promote actor context and target_computer in Redis transport to named fields.

Phase 4: Add typed WebOriginMetadata and TerminalOriginMetadata dataclasses matching the adapter metadata pattern. Identity resolver reads from typed schemas.

Phase 5: Rename/document channel_metadata as edge-only platform signals. After phases 2-4 it carries only raw platform identity signals from edges.

Phase 6: Daemon headless session creation via command pipeline. Replace db.create_headless_session() with constructing a CreateSessionCommand and routing through core. Remove resolve_from_terminal() — identity propagates from parent session.

Key files: teleclaude/core/identity.py, teleclaude/core/command_handlers/_session.py, teleclaude/types/commands.py, teleclaude/api/sessions_actions_routes.py, teleclaude/api/sessions_routes.py, teleclaude/core/command_mapper.py, teleclaude/core/models/_adapter.py, teleclaude/core/agent_coordinator/_fanout.py, teleclaude/transport/redis_transport/_messaging.py, teleclaude/daemon_hook_outbox.py, teleclaude/core/db/_sessions.py

-- Output generation identity: one row per cut turn boundary for a session.
-- Assistant output snapshots name their generation so an adapter can edit
-- only its own in-flight message, never a stale or later turn's.
CREATE TABLE IF NOT EXISTS output_generations (
    generation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    binding_id TEXT,
    is_legacy INTEGER NOT NULL DEFAULT 0,
    native_runtime TEXT,
    native_session_id TEXT,
    native_entry_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_output_generations_session ON output_generations(session_id, created_at);

-- Per-consumer delivery progress. One session may have multiple independent
-- consumers (origin adapter, admin mirror, additional relay lanes); each
-- owns its own cursor so one consumer's advance cannot mute another's.
CREATE TABLE IF NOT EXISTS output_consumer_cursors (
    session_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    generation_id TEXT,
    char_offset INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, consumer)
);

-- Per-consumer, per-generation delivery receipt: the platform message a
-- consumer is currently editing for a specific generation, and how much of
-- that generation's output has been written into it.
CREATE TABLE IF NOT EXISTS output_consumer_receipts (
    session_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    platform_message_id TEXT,
    delivered_char_offset INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, consumer, generation_id)
);

CREATE INDEX IF NOT EXISTS idx_output_consumer_receipts_session_consumer
ON output_consumer_receipts(session_id, consumer, updated_at DESC);

-- Durable Discord webhook create intent, persisted before dispatch so restart
-- can reconcile an unresolved create instead of blind-resending it. Bounded
-- terminal dispositions: 'resolved' (a platform id was recovered and
-- adopted), 'omitted' (reconciliation was inconclusive within its bound —
-- closed as not-delivered, releasing the lane for the next generation), and
-- 'replayed' (an explicit recovery action re-drove an omitted intent; the
-- retry is a fresh intent row referencing this one via replays_intent_id).
CREATE TABLE IF NOT EXISTS discord_send_intents (
    intent_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    generation_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'resolved', 'omitted', 'replayed')),
    platform_message_id TEXT,
    replays_intent_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_discord_send_intents_session_gen
ON discord_send_intents(session_id, generation_id);

CREATE INDEX IF NOT EXISTS idx_discord_send_intents_status
ON discord_send_intents(status);

-- Current reminder aggregate generation. Public identity is session + slug;
-- occurrence_key is private acceptance-dedup infrastructure identity.
CREATE TABLE IF NOT EXISTS reminders (
    session_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    profile TEXT,
    intent TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('time', 'agent_event')),
    event_anchor TEXT,
    recurrence TEXT NOT NULL CHECK(recurrence IN ('one_shot', 'recurring')),
    interval_seconds REAL,
    armed_at TEXT NOT NULL,
    next_fire_at TEXT,
    generation INTEGER NOT NULL,
    occurrence_key TEXT NOT NULL,
    firing_count INTEGER NOT NULL DEFAULT 0 CHECK(firing_count >= 0),
    sliding INTEGER NOT NULL DEFAULT 0,
    claimed_occurrence_key TEXT,
    claimed_at TEXT,
    PRIMARY KEY (session_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_reminders_next_fire
ON reminders(next_fire_at)
WHERE next_fire_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_reminders_event_anchor
ON reminders(session_id, event_anchor)
WHERE event_anchor IS NOT NULL;

-- Append-only reminder source entries. A firing occurrence is unique so a
-- crash after inbound acceptance cannot append a second firing entry.
CREATE TABLE IF NOT EXISTS reminder_entries (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    slug TEXT NOT NULL,
    generation INTEGER NOT NULL,
    transition TEXT NOT NULL CHECK(transition IN ('armed', 'replaced', 'cancelled', 'firing')),
    profile TEXT,
    intent TEXT NOT NULL,
    trigger_type TEXT NOT NULL CHECK(trigger_type IN ('time', 'agent_event')),
    event_anchor TEXT,
    recurrence TEXT NOT NULL CHECK(recurrence IN ('one_shot', 'recurring')),
    interval_seconds REAL,
    armed_at TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    next_fire_at TEXT,
    occurrence_key TEXT NOT NULL,
    sliding INTEGER NOT NULL DEFAULT 0,
    firing_number INTEGER CHECK(firing_number IS NULL OR firing_number > 0)
);

CREATE INDEX IF NOT EXISTS idx_reminder_entries_session
ON reminder_entries(session_id, entry_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reminder_entries_firing_occurrence
ON reminder_entries(occurrence_key)
WHERE transition = 'firing';

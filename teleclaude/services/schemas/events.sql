-- Event channel infrastructure — outbox tables, subscriber cursors, NOTIFY triggers.
--
-- Each channel has its own outbox table for isolation. Subscribers track
-- their position via the cursors table. Postgres triggers fire NOTIFY
-- on every insert so consumers wake immediately.

CREATE SCHEMA IF NOT EXISTS events;

-- Per-channel outbox: one table per channel for independent throughput.

CREATE TABLE events.hooks_outbox (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE events.lifecycle_outbox (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE events.work_outbox (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Subscriber cursors: one row per subscriber per channel.

CREATE TABLE events.cursors (
    channel     TEXT NOT NULL,
    subscriber  TEXT NOT NULL,
    cursor_pos  BIGINT NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel, subscriber)
);

-- NOTIFY triggers — fire automatically on every outbox insert.
-- Subscribers LISTEN on 'events_{channel}' and wake immediately.

CREATE OR REPLACE FUNCTION events.notify_hooks() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('events_hooks', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hooks_outbox_notify
    AFTER INSERT ON events.hooks_outbox
    FOR EACH ROW EXECUTE FUNCTION events.notify_hooks();


CREATE OR REPLACE FUNCTION events.notify_lifecycle() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('events_lifecycle', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER lifecycle_outbox_notify
    AFTER INSERT ON events.lifecycle_outbox
    FOR EACH ROW EXECUTE FUNCTION events.notify_lifecycle();


CREATE OR REPLACE FUNCTION events.notify_work() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('events_work', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER work_outbox_notify
    AFTER INSERT ON events.work_outbox
    FOR EACH ROW EXECUTE FUNCTION events.notify_work();

-- Indexes for cursor-based reads (WHERE id > cursor ORDER BY id).
-- BIGSERIAL PK already provides this via the primary key index.
-- Additional indexes only if query patterns demand them.

CREATE INDEX idx_hooks_outbox_type ON events.hooks_outbox (event_type);
CREATE INDEX idx_lifecycle_outbox_type ON events.lifecycle_outbox (event_type);
CREATE INDEX idx_work_outbox_type ON events.work_outbox (event_type);

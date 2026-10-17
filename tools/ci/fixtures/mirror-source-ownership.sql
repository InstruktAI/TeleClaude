PRAGMA user_version = 10;

CREATE TABLE mirror_sessions (
    id INTEGER PRIMARY KEY,
    session_id TEXT UNIQUE NOT NULL,
    principal TEXT,
    subject TEXT,
    subject_owner TEXT,
    project TEXT,
    subdir TEXT,
    initiator_session_id TEXT,
    initiator_computer TEXT,
    initiated_by_ai INTEGER,
    job TEXT,
    started_at TEXT,
    closed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    native_session_id TEXT,
    source_identity TEXT UNIQUE,
    computer TEXT NOT NULL,
    agent TEXT NOT NULL,
    project_path TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    timestamp_start TEXT,
    timestamp_end TEXT,
    conversation_text TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT,
    human_email TEXT,
    visibility TEXT DEFAULT 'private',
    command TEXT,
    todo TEXT,
    is_worker INTEGER NOT NULL DEFAULT 0,
    derivation_version INTEGER NOT NULL DEFAULT 0,
    session INTEGER,
    position INTEGER,
    covered_at TEXT,
    coverage_ready INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE mirror_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mirror INTEGER NOT NULL,
    source_identity TEXT NOT NULL UNIQUE,
    native_session_id TEXT,
    agent TEXT NOT NULL,
    transcript_path TEXT,
    position INTEGER NOT NULL DEFAULT 0,
    file_size INTEGER,
    file_mtime_ns TEXT,
    missing_at TEXT,
    derivation_version INTEGER NOT NULL DEFAULT 0,
    archival_text TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0,
    timestamp_start TEXT,
    timestamp_end TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE mirror_messages (
    source INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    entry_index INTEGER NOT NULL,
    block_ordinal INTEGER NOT NULL,
    timestamp TEXT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    PRIMARY KEY (source, ordinal)
) WITHOUT ROWID;

CREATE TABLE mirror_unreprojectable_sources (
    source_identity TEXT PRIMARY KEY,
    marked_at TEXT NOT NULL
);

CREATE TABLE mirror_shrink_refusals (
    source_identity TEXT PRIMARY KEY,
    shrink_refused_at TEXT NOT NULL
);

CREATE TABLE mirror_tombstones (
    source_identity TEXT PRIMARY KEY,
    agent TEXT NOT NULL DEFAULT '',
    transcript_path TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    file_mtime TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE mirrors_fts USING fts5(title, conversation_text, content='mirrors', content_rowid='id');
CREATE TRIGGER mirrors_ai AFTER INSERT ON mirrors BEGIN
    INSERT INTO mirrors_fts(rowid, title, conversation_text) VALUES (new.id, new.title, new.conversation_text);
END;
CREATE TRIGGER mirrors_ad AFTER DELETE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
END;
CREATE TRIGGER mirrors_au AFTER UPDATE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
    INSERT INTO mirrors_fts(rowid, title, conversation_text) VALUES (new.id, new.title, new.conversation_text);
END;
CREATE INDEX idx_mirror_sources_mirror ON mirror_sources(mirror);
CREATE INDEX idx_mirror_sources_native ON mirror_sources(native_session_id);
CREATE UNIQUE INDEX idx_mirrors_session_unique ON mirrors(session) WHERE session IS NOT NULL;

INSERT INTO mirror_sessions (
    id, session_id, principal, subject, subject_owner, project, initiator_computer,
    started_at, closed_at, created_at, updated_at
) VALUES (
    14, '00000000-0000-4000-8000-000000000014', 'human:runtime-acceptance@example.invalid',
    'person:runtime-acceptance', 'runtime-acceptance@example.invalid', 'runtime-acceptance',
    'runtime-acceptance', '2026-01-01T10:00:00.000Z', '2026-01-01T10:02:00.000Z',
    '2026-01-01T10:00:00.000Z', '2026-01-01T10:02:00.000Z'
);

INSERT INTO mirrors (
    id, native_session_id, source_identity, computer, agent, project_path, title,
    timestamp_start, timestamp_end, conversation_text, message_count, metadata, created_at,
    updated_at, human_email, session, position, covered_at, coverage_ready
) VALUES (
    14, 'runtime-acceptance-native-14', 'claude:runtime-acceptance-native-14.jsonl',
    'runtime-acceptance', 'claude', '', 'retained fixture', '2026-01-01T10:00:00.000Z',
    '2026-01-01T10:00:05.000Z', 'Retained fixture conversation survives source ownership migration.',
    1, '{"source":"fixture","provenance":"retained"}', '2026-01-01T10:00:00.000Z',
    '2026-01-01T10:00:05.000Z', 'runtime-acceptance@example.invalid', 14, 0,
    '2026-01-01T10:00:05.000Z', 1
);

INSERT INTO mirror_sources (
    id, mirror, source_identity, native_session_id, agent, transcript_path, position,
    file_size, file_mtime_ns, derivation_version, archival_text, message_count,
    timestamp_start, timestamp_end, created_at, updated_at
) VALUES (
    14, 14, 'claude:runtime-acceptance-native-14.jsonl', 'runtime-acceptance-native-14',
    'claude', '/synthetic/runtime-acceptance-native-14.jsonl', 0, 82, '1767261605000000000',
    1, 'Retained fixture conversation survives source ownership migration.', 1,
    '2026-01-01T10:00:00.000Z', '2026-01-01T10:00:05.000Z',
    '2026-01-01T10:00:00.000Z', '2026-01-01T10:00:05.000Z'
);

INSERT INTO mirror_messages (
    source, ordinal, entry_index, block_ordinal, timestamp, role, text
) VALUES (
    14, 1, 1, 0, '2026-01-01T10:00:00.000Z', 'user',
    'Retained fixture conversation survives source ownership migration.'
);
INSERT INTO mirror_unreprojectable_sources (source_identity, marked_at)
VALUES ('claude:runtime-acceptance-native-14.jsonl', '2026-01-01T10:03:00.000Z');
INSERT INTO mirror_shrink_refusals (source_identity, shrink_refused_at)
VALUES ('claude:runtime-acceptance-native-14.jsonl', '2026-01-01T10:04:00.000Z');
INSERT INTO mirror_tombstones (source_identity, agent, transcript_path, file_size, file_mtime, created_at)
VALUES (
    'claude:runtime-acceptance-tombstone.jsonl', 'claude', '/synthetic/runtime-acceptance-tombstone.jsonl',
    0, '1767261606000000000', '2026-01-01T10:05:00.000Z'
);

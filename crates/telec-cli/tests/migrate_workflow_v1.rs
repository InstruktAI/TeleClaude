//! Integration tests for `migrate-workflow-v1`.
//!
//! Each test:
//!
//! 1. Acquires a fresh Postgres database via `sqlx::test`, with the v2
//!    `workflow` migrations applied. `DATABASE_URL` must be set in the
//!    test environment.
//! 2. Builds a v1 `todos.db` SQLite file in a tempdir using the same
//!    schema strings v1 ships in production (mirrored verbatim from
//!    `teleclaude/core/todos_db/schema.sql`).
//! 3. Invokes [`telec_cli::migrate::run`] against the fresh pool and
//!    asserts the resulting v2 row counts, idempotency, and SHA tracking.
//!
//! Tests are gated with `#[ignore]` so `cargo test -p telec-cli` is
//! green in environments without Postgres. Run them with
//! `cargo test -p telec-cli -- --ignored`.

use std::path::PathBuf;
use std::sync::Arc;

use async_trait::async_trait;
use event_bus::{EventBusError, EventEnvelope};
use rusqlite::Connection;
use sqlx::PgPool;
use telec_cli::migrate::{run, MigrateArgs};
use tempfile::TempDir;
use workflow::{EventSink, WorkflowService};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("../workflow/migrations");

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

/// EventSink that swallows every envelope. The migrator does not publish
/// events; we still need an `EventSink` to construct a `WorkflowService`.
struct NoopSink;

#[async_trait]
impl EventSink for NoopSink {
    async fn emit(&self, _envelope: &EventEnvelope) -> Result<(), EventBusError> {
        Ok(())
    }
}

fn build_service(pool: PgPool) -> WorkflowService {
    WorkflowService::new(pool, Arc::new(NoopSink))
}

/// Apply the v1 SQLite schema to a fresh DB. Mirrors
/// `teleclaude/core/todos_db/schema.sql` verbatim.
fn apply_v1_schema(conn: &Connection) {
    conn.execute_batch(
        "CREATE TABLE roadmap (
             id              TEXT PRIMARY KEY,
             slug            TEXT NOT NULL,
             position        INTEGER NOT NULL,
             group_slug      TEXT,
             description     TEXT,
             status          TEXT NOT NULL DEFAULT 'active',
             delivered_at    TEXT,
             delivered_commit TEXT,
             children        TEXT,
             created_at      TEXT NOT NULL,
             updated_at      TEXT NOT NULL
         );
         CREATE UNIQUE INDEX idx_roadmap_slug_active
             ON roadmap(slug) WHERE status IN ('active', 'icebox');
         CREATE TABLE todo_state (
             id              TEXT PRIMARY KEY,
             slug            TEXT NOT NULL,
             state           TEXT NOT NULL,
             created_at      TEXT NOT NULL,
             updated_at      TEXT NOT NULL
         );
         CREATE TABLE todo_artifacts (
             id              TEXT NOT NULL,
             slug            TEXT NOT NULL,
             name            TEXT NOT NULL,
             content         TEXT NOT NULL DEFAULT '',
             digest          TEXT NOT NULL DEFAULT '',
             updated_by      TEXT,
             updated_at      TEXT,
             PRIMARY KEY (id, name)
         );
         CREATE TABLE todo_artifact_versions (
             version_id      INTEGER PRIMARY KEY AUTOINCREMENT,
             id              TEXT NOT NULL,
             slug            TEXT NOT NULL,
             name            TEXT NOT NULL,
             content         TEXT NOT NULL,
             digest          TEXT NOT NULL,
             updated_by      TEXT,
             created_at      TEXT NOT NULL
         );
         CREATE INDEX idx_av_id_name ON todo_artifact_versions(id, name, created_at);
         CREATE TABLE roadmap_deps (
             slug            TEXT NOT NULL,
             depends_on      TEXT NOT NULL,
             PRIMARY KEY (slug, depends_on)
         );",
    )
    .expect("apply v1 schema");
}

struct Fixture {
    _tmp: TempDir,
    db_path: PathBuf,
}

impl Fixture {
    fn project_root(&self) -> PathBuf {
        self.db_path
            .parent()
            .and_then(|p| p.parent())
            .expect("project root")
            .to_path_buf()
    }
}

/// Build a v1 SQLite db with a representative payload:
///
/// * 2 active roadmap entries and 1 delivered.
/// * One dependency edge (`beta` after `alpha`).
/// * Matching `todo_state` rows; `beta` carries a non-default lifecycle
///   phase and an `integration_phase` so the JSON-promotion code is
///   exercised.
/// * One artifact (`prd`) with two versions on `alpha`.
fn build_v1_fixture() -> Fixture {
    let tmp = TempDir::new().expect("tempdir");
    let dot = tmp.path().join("proj").join(".teleclaude");
    std::fs::create_dir_all(&dot).expect("mkdir .teleclaude");
    let db_path = dot.join("todos.db");
    let conn = Connection::open(&db_path).expect("open sqlite");
    apply_v1_schema(&conn);
    seed_v1_rows(&conn);
    Fixture { _tmp: tmp, db_path }
}

fn seed_v1_rows(conn: &Connection) {
    let now = "2024-05-01T12:00:00+00:00";
    conn.execute_batch(&format!(
        r#"
        INSERT INTO roadmap (id, slug, position, group_slug, description, status, created_at, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000001', 'alpha', 1, 'core', 'First todo', 'active', '{now}', '{now}');
        INSERT INTO roadmap (id, slug, position, group_slug, description, status, created_at, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000002', 'beta', 2, 'core', 'Second todo', 'active', '{now}', '{now}');
        INSERT INTO roadmap (id, slug, position, group_slug, description, status, delivered_at, delivered_commit, created_at, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000003', 'gamma', 3, NULL, 'Done todo', 'delivered', '{now}', 'deadbeef', '{now}', '{now}');

        INSERT INTO roadmap_deps (slug, depends_on) VALUES ('beta', 'alpha');

        INSERT INTO todo_state (id, slug, state, created_at, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000001', 'alpha',
                    '{{"kind":"feature","lifecycle_phase":"draft","misc":"keep-me"}}',
                    '{now}', '{now}');
        INSERT INTO todo_state (id, slug, state, created_at, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000002', 'beta',
                    '{{"kind":"bug","lifecycle_phase":"build_started","integration_phase":"lease_held","finalize":{{"status":"ready"}}}}',
                    '{now}', '{now}');
        INSERT INTO todo_state (id, slug, state, created_at, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000003', 'gamma',
                    '{{"kind":"feature","lifecycle_phase":"handed_off"}}',
                    '{now}', '{now}');

        INSERT INTO todo_artifacts (id, slug, name, content, digest, updated_by, updated_at)
            VALUES ('00000000-0000-0000-0000-000000000001', 'alpha', 'prd', 'v2 content', 'd2', 'tester', '{now}');
        INSERT INTO todo_artifact_versions (id, slug, name, content, digest, updated_by, created_at)
            VALUES ('00000000-0000-0000-0000-000000000001', 'alpha', 'prd', 'v1 content', 'd1', 'tester', '{now}');
        INSERT INTO todo_artifact_versions (id, slug, name, content, digest, updated_by, created_at)
            VALUES ('00000000-0000-0000-0000-000000000001', 'alpha', 'prd', 'v2 content', 'd2', 'tester', '{now}');
        "#,
    ))
    .expect("seed v1 rows");
}

fn args_for(fixture: &Fixture, project: &str, force: bool, dry_run: bool) -> MigrateArgs {
    MigrateArgs {
        project: project.to_owned(),
        source: Some(fixture.db_path.to_string_lossy().into_owned()),
        dry_run,
        force,
    }
}

async fn count(pool: &PgPool, sql: &str) -> i64 {
    sqlx::query_scalar(sql)
        .fetch_one(pool)
        .await
        .expect("count query")
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[sqlx::test(migrator = "MIGRATOR")]
#[ignore]
async fn happy_path_imports_v1_rows_into_v2(pool: PgPool) {
    let fixture = build_v1_fixture();
    let service = build_service(pool.clone());

    let code = run(args_for(&fixture, "alpha-project", false, false), &service)
        .await
        .expect("migration succeeds");
    assert_eq!(code, 0);

    assert_eq!(
        count(&pool, "select count(*) from workflow.projects").await,
        1
    );
    assert_eq!(
        count(&pool, "select count(*) from workflow.roadmap_entries").await,
        3
    );
    assert_eq!(count(&pool, "select count(*) from workflow.todos").await, 3);
    assert_eq!(
        count(&pool, "select count(*) from workflow.artifacts").await,
        1
    );
    assert_eq!(
        count(&pool, "select count(*) from workflow.artifact_versions").await,
        2
    );
    assert_eq!(
        count(&pool, "select count(*) from workflow.roadmap_deps").await,
        1
    );
    assert_eq!(
        count(&pool, "select count(*) from workflow.migrations_v1").await,
        1
    );

    let slugs: Vec<String> =
        sqlx::query_scalar("select slug from workflow.todos order by slug asc")
            .fetch_all(&pool)
            .await
            .expect("fetch slugs");
    assert_eq!(slugs, vec!["alpha", "beta", "gamma"]);

    // The 'beta' state JSON promoted integration_phase + nested finalize.status.
    let (integration, finalize): (Option<String>, Option<String>) = sqlx::query_as(
        "select integration_phase, finalize_status from workflow.todos where slug = 'beta'",
    )
    .fetch_one(&pool)
    .await
    .expect("fetch beta promotion");
    assert_eq!(integration.as_deref(), Some("lease_held"));
    assert_eq!(finalize.as_deref(), Some("ready"));

    // 'alpha' state_extra preserves the unmodelled "misc" key.
    let extra: serde_json::Value =
        sqlx::query_scalar("select state_extra from workflow.todos where slug = 'alpha'")
            .fetch_one(&pool)
            .await
            .expect("fetch alpha extra");
    assert_eq!(extra.get("misc").and_then(|v| v.as_str()), Some("keep-me"));

    // 'beta' lists 'alpha' as a dependency in the relational table.
    let dep: String =
        sqlx::query_scalar("select depends_on from workflow.roadmap_deps where slug = 'beta'")
            .fetch_one(&pool)
            .await
            .expect("fetch dep");
    assert_eq!(dep, "alpha");

    // root_path on the project points at the fixture's project root.
    let stored_root: String =
        sqlx::query_scalar("select root_path from workflow.projects where name = 'alpha-project'")
            .fetch_one(&pool)
            .await
            .expect("fetch root_path");
    assert_eq!(
        PathBuf::from(stored_root),
        fixture.project_root(),
        "stored project root should match fixture project root"
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
#[ignore]
async fn rerun_with_unchanged_source_is_a_noop(pool: PgPool) {
    let fixture = build_v1_fixture();
    let service = build_service(pool.clone());

    run(args_for(&fixture, "alpha-project", false, false), &service)
        .await
        .expect("first migration succeeds");
    run(args_for(&fixture, "alpha-project", false, false), &service)
        .await
        .expect("second migration succeeds with no-op");

    // Counts unchanged after the second run.
    assert_eq!(count(&pool, "select count(*) from workflow.todos").await, 3);
    assert_eq!(
        count(&pool, "select count(*) from workflow.roadmap_entries").await,
        3
    );
    assert_eq!(
        count(&pool, "select count(*) from workflow.artifact_versions").await,
        2
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
#[ignore]
async fn rerun_against_mutated_source_without_force_errors(pool: PgPool) {
    let fixture = build_v1_fixture();
    let service = build_service(pool.clone());

    run(args_for(&fixture, "alpha-project", false, false), &service)
        .await
        .expect("first migration succeeds");

    // Mutate the source DB so its SHA changes.
    {
        let conn = Connection::open(&fixture.db_path).expect("reopen");
        conn.execute(
            "INSERT INTO roadmap (id, slug, position, status, created_at, updated_at)
             VALUES ('00000000-0000-0000-0000-000000000099', 'delta', 4, 'active',
                     '2024-05-02T12:00:00+00:00', '2024-05-02T12:00:00+00:00')",
            [],
        )
        .expect("insert delta");
    }

    let err = run(args_for(&fixture, "alpha-project", false, false), &service)
        .await
        .expect_err("expected error on changed source without --force");
    assert!(
        err.to_string().contains("--force"),
        "error should mention --force; got: {err}"
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
#[ignore]
async fn rerun_with_force_replaces_rows(pool: PgPool) {
    let fixture = build_v1_fixture();
    let service = build_service(pool.clone());

    run(args_for(&fixture, "alpha-project", false, false), &service)
        .await
        .expect("first migration succeeds");

    {
        let conn = Connection::open(&fixture.db_path).expect("reopen");
        conn.execute(
            "INSERT INTO roadmap (id, slug, position, status, created_at, updated_at)
             VALUES ('00000000-0000-0000-0000-000000000099', 'delta', 4, 'active',
                     '2024-05-02T12:00:00+00:00', '2024-05-02T12:00:00+00:00')",
            [],
        )
        .expect("insert delta");
        conn.execute(
            "INSERT INTO todo_state (id, slug, state, created_at, updated_at)
             VALUES ('00000000-0000-0000-0000-000000000099', 'delta',
                     '{\"kind\":\"feature\",\"lifecycle_phase\":\"draft\"}',
                     '2024-05-02T12:00:00+00:00', '2024-05-02T12:00:00+00:00')",
            [],
        )
        .expect("insert delta state");
    }

    let code = run(args_for(&fixture, "alpha-project", true, false), &service)
        .await
        .expect("force migration succeeds");
    assert_eq!(code, 0);

    // After --force the new row count reflects the updated source.
    assert_eq!(count(&pool, "select count(*) from workflow.todos").await, 4);
    assert_eq!(
        count(&pool, "select count(*) from workflow.roadmap_entries").await,
        4
    );

    let slugs: Vec<String> =
        sqlx::query_scalar("select slug from workflow.todos order by slug asc")
            .fetch_all(&pool)
            .await
            .expect("fetch slugs");
    assert_eq!(slugs, vec!["alpha", "beta", "delta", "gamma"]);

    // migrations_v1 row updated to the new SHA.
    assert_eq!(
        count(&pool, "select count(*) from workflow.migrations_v1").await,
        1
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
#[ignore]
async fn dry_run_rolls_back_without_persisting(pool: PgPool) {
    let fixture = build_v1_fixture();
    let service = build_service(pool.clone());

    let code = run(args_for(&fixture, "alpha-project", false, true), &service)
        .await
        .expect("dry-run succeeds");
    assert_eq!(code, 0);

    // No rows persisted because the transaction rolled back.
    assert_eq!(
        count(&pool, "select count(*) from workflow.projects").await,
        0
    );
    assert_eq!(count(&pool, "select count(*) from workflow.todos").await, 0);
    assert_eq!(
        count(&pool, "select count(*) from workflow.migrations_v1").await,
        0
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
#[ignore]
async fn missing_source_db_returns_error(pool: PgPool) {
    let service = build_service(pool.clone());
    let bogus = PathBuf::from("/definitely/does/not/exist/todos.db");

    let err = run(
        MigrateArgs {
            project: "ghost".to_owned(),
            source: Some(bogus.to_string_lossy().into_owned()),
            dry_run: false,
            force: false,
        },
        &service,
    )
    .await
    .expect_err("missing source should error");
    assert!(
        err.to_string().contains("v1 todos.db not found"),
        "error should explain missing file; got: {err}"
    );
}

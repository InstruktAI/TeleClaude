//! Integration test for the `telec migrate-identity-v1` migration helper.
//!
//! Each test exercises the function directly (rather than spawning the
//! binary) so we can drive a transient Postgres via `sqlx::test`. The
//! migration uses the same identity migrator the production code does,
//! so the schema is in place automatically.
//!
//! RV-4 contract: the migration writes through a real
//! [`identity::IdentityService`] event sink so non-dry-run migration
//! mutations publish `identity.*` envelopes. The tests use a recording
//! sink and assert that the expected events surface.

use std::fs::write;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use identity::events::{PrincipalCreated, TokenIssued, TokenRevoked};
use identity::{IdentityError, IdentityEventSink, IdentityService};
use rusqlite::Connection;
use sqlx::PgPool;
use sqlx::Row;
use tempfile::tempdir;

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("../identity/migrations");

#[derive(Default)]
struct RecordingSink {
    principals: Mutex<Vec<PrincipalCreated>>,
    issued: Mutex<Vec<TokenIssued>>,
    revoked: Mutex<Vec<TokenRevoked>>,
}

#[async_trait]
impl IdentityEventSink for RecordingSink {
    async fn emit_principal_created(&self, event: PrincipalCreated) -> Result<(), IdentityError> {
        self.principals.lock().unwrap().push(event);
        Ok(())
    }
    async fn emit_token_issued(&self, event: TokenIssued) -> Result<(), IdentityError> {
        self.issued.lock().unwrap().push(event);
        Ok(())
    }
    async fn emit_token_revoked(&self, event: TokenRevoked) -> Result<(), IdentityError> {
        self.revoked.lock().unwrap().push(event);
        Ok(())
    }
}

fn build_service(pool: PgPool) -> (IdentityService, Arc<RecordingSink>) {
    let sink: Arc<RecordingSink> = Arc::new(RecordingSink::default());
    (IdentityService::new(pool, sink.clone()), sink)
}

fn write_global_yaml(dir: &std::path::Path, body: &str) -> PathBuf {
    let path = dir.join("teleclaude.yml");
    write(&path, body).expect("write yaml");
    path
}

fn build_v1_tokens_db(dir: &std::path::Path, rows: &[(&str, &str, &str, &str)]) -> PathBuf {
    let path = dir.join("teleclaude.db");
    let conn = Connection::open(&path).expect("open sqlite");
    conn.execute_batch(
        "create table session_tokens (
            token text primary key,
            session_id text not null,
            principal text not null,
            role text not null
        );",
    )
    .expect("create v1 schema");
    for (token, session_id, principal, role) in rows {
        conn.execute(
            "insert into session_tokens (token, session_id, principal, role) values (?1, ?2, ?3, ?4)",
            rusqlite::params![token, session_id, principal, role],
        )
        .expect("insert v1 token row");
    }
    path
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn migrates_roster_writes_principals_via_real_sink(pool: PgPool) {
    let dir = tempdir().expect("tempdir");
    let config_path = write_global_yaml(
        dir.path(),
        r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
  proficiency: expert
- name: Member
  email: member@example.com
  role: member
  proficiency: intermediate
"#,
    );

    let (service, sink) = build_service(pool.clone());
    let args = telec_cli::migrate_identity::MigrateIdentityArgs {
        config_file: Some(config_path),
        tokens_db: None,
        dry_run: false,
    };
    let summary = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect("migration succeeds");

    assert_eq!(summary.humans_inserted, 2);
    assert_eq!(summary.humans_skipped_existing, 0);

    let count: i64 = sqlx::query_scalar("select count(*) from identity.principals")
        .fetch_one(&pool)
        .await
        .expect("count");
    assert_eq!(count, 2);

    // RV-4: events reach the configured sink instead of being swallowed
    // by an in-memory CountingSink.
    let emails: Vec<String> = {
        let emitted_principals = sink.principals.lock().unwrap();
        assert_eq!(
            emitted_principals.len(),
            2,
            "two principal.created events must reach the real sink"
        );
        emitted_principals
            .iter()
            .filter_map(|e| e.email.clone())
            .collect()
    };
    assert!(emails.contains(&"owner@example.com".to_string()));
    assert!(emails.contains(&"member@example.com".to_string()));

    let row = sqlx::query(
        "select role::text as role from identity.principals where email = 'owner@example.com'",
    )
    .fetch_one(&pool)
    .await
    .expect("fetch owner");
    let owner_role: String = row.try_get("role").expect("role");
    assert_eq!(
        owner_role, "owner",
        "first roster entry must be promoted to owner role"
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn migration_is_idempotent(pool: PgPool) {
    let dir = tempdir().expect("tempdir");
    let config_path = write_global_yaml(
        dir.path(),
        r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
"#,
    );

    let (service, _sink) = build_service(pool.clone());
    let args = telec_cli::migrate_identity::MigrateIdentityArgs {
        config_file: Some(config_path),
        tokens_db: None,
        dry_run: false,
    };

    let first = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect("first run");
    assert_eq!(first.humans_inserted, 1);

    let second = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect("second run");
    assert_eq!(second.humans_inserted, 0);
    assert_eq!(second.humans_skipped_existing, 1);

    let count: i64 = sqlx::query_scalar("select count(*) from identity.principals")
        .fetch_one(&pool)
        .await
        .expect("count");
    assert_eq!(count, 1);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn dry_run_leaves_postgres_state_unchanged(pool: PgPool) {
    let dir = tempdir().expect("tempdir");
    let config_path = write_global_yaml(
        dir.path(),
        r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
"#,
    );
    let v1_token = "11112222-3333-4444-5555-666677778888";
    let tokens_db = build_v1_tokens_db(
        dir.path(),
        &[(v1_token, "dry-run-session", "owner@example.com", "admin")],
    );

    let (service, sink) = build_service(pool.clone());
    let args = telec_cli::migrate_identity::MigrateIdentityArgs {
        config_file: Some(config_path),
        tokens_db: Some(tokens_db),
        dry_run: true,
    };

    let summary = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect("dry run");
    assert!(summary.dry_run);
    assert_eq!(summary.humans_inserted, 1);
    assert_eq!(summary.tokens_inserted, 1);

    let principal_count: i64 = sqlx::query_scalar("select count(*) from identity.principals")
        .fetch_one(&pool)
        .await
        .expect("count");
    assert_eq!(
        principal_count, 0,
        "dry-run must not leave principal rows behind"
    );

    let token_count: i64 = sqlx::query_scalar("select count(*) from identity.session_tokens")
        .fetch_one(&pool)
        .await
        .expect("token count");
    assert_eq!(token_count, 0, "dry-run must not leave token rows behind");

    assert!(
        sink.principals.lock().unwrap().is_empty(),
        "dry-run must not emit principal.created events"
    );
    assert!(
        sink.issued.lock().unwrap().is_empty(),
        "dry-run must not emit token.issued events"
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn unknown_role_aborts_migration_with_invalid_role(pool: PgPool) {
    // RV-8 alignment: unknown roles must fail with InvalidRole (surfaced
    // via anyhow context), not silently coerce to Member.
    let dir = tempdir().expect("tempdir");
    let config_path = write_global_yaml(
        dir.path(),
        r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
- name: Customer
  email: customer@example.com
  role: customer
"#,
    );

    let (service, _sink) = build_service(pool.clone());
    let args = telec_cli::migrate_identity::MigrateIdentityArgs {
        config_file: Some(config_path),
        tokens_db: None,
        dry_run: false,
    };
    let err = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect_err("migration aborts on unknown role");

    let chain = format!("{err:#}");
    assert!(
        chain.contains("invalid role"),
        "anyhow chain must surface IdentityError::InvalidRole, got: {chain}"
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn imports_v1_session_token_verbatim(pool: PgPool) {
    // RV-3: v1 token uuid and role must be preserved; non-UUID v1
    // session_id maps onto a deterministic v2 uuid via UUIDv5.
    let dir = tempdir().expect("tempdir");
    let config_path = write_global_yaml(
        dir.path(),
        r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
"#,
    );
    let v1_token = "11112222-3333-4444-5555-666677778888";
    let v1_session_id = "legacy-tmux-session"; // intentionally non-uuid
    let tokens_db = build_v1_tokens_db(
        dir.path(),
        &[(v1_token, v1_session_id, "owner@example.com", "admin")],
    );

    let (service, sink) = build_service(pool.clone());
    let args = telec_cli::migrate_identity::MigrateIdentityArgs {
        config_file: Some(config_path),
        tokens_db: Some(tokens_db),
        dry_run: false,
    };
    let summary = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect("migration succeeds");

    assert_eq!(summary.tokens_inserted, 1);
    assert_eq!(summary.tokens_skipped_existing, 0);

    // The v1 token uuid is present in v2 verbatim — interchangeable per
    // implementation-plan.md lines 477-483.
    let stored_token_count: i64 =
        sqlx::query_scalar("select count(*) from identity.session_tokens where token = $1")
            .bind(uuid::Uuid::parse_str(v1_token).unwrap())
            .fetch_one(&pool)
            .await
            .expect("count");
    assert_eq!(stored_token_count, 1);

    // The non-uuid v1 session id mapped onto a deterministic v2 uuid;
    // re-running the mapping yields the same value.
    let expected_session_uuid = telec_cli::migrate_identity::map_v1_session_id(v1_session_id);
    let stored_session_uuid: uuid::Uuid =
        sqlx::query_scalar("select session_id from identity.session_tokens where token = $1")
            .bind(uuid::Uuid::parse_str(v1_token).unwrap())
            .fetch_one(&pool)
            .await
            .expect("fetch session_id");
    assert_eq!(stored_session_uuid, expected_session_uuid.0);

    // RV-4: TokenIssued envelope is emitted for the imported row.
    let issued = sink.issued.lock().unwrap();
    assert_eq!(
        issued.len(),
        1,
        "TokenIssued must surface for the imported v1 row"
    );
    assert_eq!(issued[0].session_id.0, expected_session_uuid.0);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn token_import_is_idempotent_on_re_run(pool: PgPool) {
    let dir = tempdir().expect("tempdir");
    let config_path = write_global_yaml(
        dir.path(),
        r#"
people:
- name: Owner
  email: owner@example.com
  role: admin
"#,
    );
    let v1_token = "11112222-3333-4444-5555-666677778888";
    let tokens_db = build_v1_tokens_db(
        dir.path(),
        &[(v1_token, "legacy", "owner@example.com", "admin")],
    );

    let (service, _sink) = build_service(pool.clone());
    let args = telec_cli::migrate_identity::MigrateIdentityArgs {
        config_file: Some(config_path),
        tokens_db: Some(tokens_db),
        dry_run: false,
    };
    let first = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect("first");
    let second = telec_cli::migrate_identity::migrate_identity_v1(&service, &args)
        .await
        .expect("second");

    assert_eq!(first.tokens_inserted, 1);
    assert_eq!(second.tokens_inserted, 0);
    assert_eq!(second.tokens_skipped_existing, 1);
}

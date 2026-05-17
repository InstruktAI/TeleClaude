//! Integration test for the identity Postgres migration.
//!
//! Brings up a fresh database via `sqlx::test`, applies the identity
//! migrator, and inspects `information_schema` to confirm the schema +
//! tables + enum types landed. Re-running the migrator must succeed
//! without error (idempotent — `sqlx` records applied migrations in
//! `_sqlx_migrations`).

use sqlx::PgPool;

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[sqlx::test(migrator = "MIGRATOR")]
async fn applies_identity_schema(pool: PgPool) {
    let schema_exists: bool = sqlx::query_scalar(
        "select exists (select 1 from information_schema.schemata where schema_name = 'identity')",
    )
    .fetch_one(&pool)
    .await
    .expect("query schema existence");
    assert!(schema_exists, "identity schema must exist after migration");

    let principals_exists: bool = sqlx::query_scalar(
        "select exists (select 1 from information_schema.tables where table_schema = 'identity' and table_name = 'principals')",
    )
    .fetch_one(&pool)
    .await
    .expect("query principals table existence");
    assert!(principals_exists, "identity.principals table must exist");

    let tokens_exists: bool = sqlx::query_scalar(
        "select exists (select 1 from information_schema.tables where table_schema = 'identity' and table_name = 'session_tokens')",
    )
    .fetch_one(&pool)
    .await
    .expect("query session_tokens table existence");
    assert!(tokens_exists, "identity.session_tokens table must exist");

    let role_enum_exists: bool = sqlx::query_scalar(
        "select exists (select 1 from pg_type t join pg_namespace n on t.typnamespace = n.oid where n.nspname = 'identity' and t.typname = 'role')",
    )
    .fetch_one(&pool)
    .await
    .expect("query role enum");
    assert!(role_enum_exists, "identity.role enum must exist");

    let kind_enum_exists: bool = sqlx::query_scalar(
        "select exists (select 1 from pg_type t join pg_namespace n on t.typnamespace = n.oid where n.nspname = 'identity' and t.typname = 'principal_kind')",
    )
    .fetch_one(&pool)
    .await
    .expect("query principal_kind enum");
    assert!(kind_enum_exists, "identity.principal_kind enum must exist");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn human_principal_round_trips(pool: PgPool) {
    sqlx::query(
        "insert into identity.principals (kind, email, role) values ('human', 'owner@example.com', 'owner')",
    )
    .execute(&pool)
    .await
    .expect("insert human principal");

    let count: i64 = sqlx::query_scalar(
        "select count(*) from identity.principals where kind = 'human' and email = 'owner@example.com'",
    )
    .fetch_one(&pool)
    .await
    .expect("count human principal rows");

    assert_eq!(count, 1);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn shape_constraint_rejects_human_without_email(pool: PgPool) {
    let result =
        sqlx::query("insert into identity.principals (kind, role) values ('human', 'owner')")
            .execute(&pool)
            .await;

    assert!(
        result.is_err(),
        "shape constraint must reject human principal without email"
    );
}

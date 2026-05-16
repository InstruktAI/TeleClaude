//! Integration tests for the `storage` crate.
//!
//! These tests require a live Postgres reachable at `DATABASE_URL` (falling
//! back to the local docker-compose default). They are gated behind
//! `#[ignore]` so a default `cargo test` stays hermetic; run them via
//! `cargo test -p storage -- --ignored`.

use std::time::Duration;

use sqlx::Row;
use storage::{build_pool, build_pool_with};

const DEFAULT_DATABASE_URL: &str = "postgres://postgres:postgres@localhost:5432/teleclaude";

fn database_url() -> String {
    std::env::var("DATABASE_URL").unwrap_or_else(|_| DEFAULT_DATABASE_URL.to_string())
}

/// `build_pool` connects to docker-compose Postgres and a trivial `SELECT 1`
/// round-trips, proving the pool is usable end-to-end.
#[tokio::test]
#[ignore = "requires Postgres reachable at DATABASE_URL"]
async fn build_pool_round_trips_select_one() {
    let pool = build_pool(&database_url())
        .await
        .expect("connect to Postgres using build_pool defaults");

    let row = sqlx::query("SELECT 1::int4 AS value")
        .fetch_one(&pool)
        .await
        .expect("SELECT 1 succeeds");

    let value: i32 = row.try_get("value").expect("column 'value' is i32");
    assert_eq!(value, 1);
}

/// `build_pool_with` honors custom `max_connections` and `acquire_timeout`
/// while still producing a working pool.
#[tokio::test]
#[ignore = "requires Postgres reachable at DATABASE_URL"]
async fn build_pool_with_custom_options_round_trips() {
    let pool = build_pool_with(&database_url(), 2, Duration::from_secs(2))
        .await
        .expect("connect to Postgres using build_pool_with");

    let row = sqlx::query("SELECT 7::int4 AS value")
        .fetch_one(&pool)
        .await
        .expect("SELECT 7 succeeds");

    let value: i32 = row.try_get("value").expect("column 'value' is i32");
    assert_eq!(value, 7);
}

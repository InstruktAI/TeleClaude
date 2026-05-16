//! Smoke tests for the `telec roadmap` subtree.
//!
//! `#[ignore]`-gated; requires Postgres + Redis (docker-compose dev stack).
//! Opt in via `cargo test -p telec-cli -- --ignored` or `make
//! test-rust-integration`.
//!
//! Assertions inspect the CLI's structured JSON output (no substring
//! matches against rendered strings — reviewer Important-3) and verify
//! Redis Streams append on each emitting mutation.

use std::sync::atomic::{AtomicU32, Ordering};

use assert_cmd::Command;
use serde_json::Value;

static SUFFIX: AtomicU32 = AtomicU32::new(0);

const STREAM_ROADMAP_ADDED: &str = "events:workflow.roadmap.entry_added";
const STREAM_ROADMAP_REMOVED: &str = "events:workflow.roadmap.entry_removed";

const EXIT_DEFERRED_TO_V1: i32 = 2;

fn unique_slug(prefix: &str) -> String {
    let n = SUFFIX.fetch_add(1, Ordering::SeqCst);
    let pid = std::process::id();
    format!("{prefix}-{pid}-{n}")
}

fn telec() -> Command {
    let mut cmd = Command::cargo_bin("telec-cli").expect("locate telec-cli binary");
    if std::env::var("TELECLAUDE_OWNER_EMAIL").is_err() {
        cmd.env("TELECLAUDE_OWNER_EMAIL", "smoke@example.com");
    }
    cmd
}

fn require_smoke_env() -> bool {
    std::env::var("DATABASE_URL").is_ok() && std::env::var("REDIS_URL").is_ok()
}

fn stream_len(channel: &str) -> u64 {
    let url = std::env::var("REDIS_URL").expect("REDIS_URL must be set for smoke");
    let client = redis::Client::open(url).expect("connect redis");
    let mut conn = client.get_connection().expect("redis conn");
    redis::cmd("XLEN")
        .arg(channel)
        .query::<u64>(&mut conn)
        .expect("XLEN")
}

fn parse_json_stdout(out: &assert_cmd::assert::Assert) -> Value {
    let bytes = out.get_output().stdout.clone();
    serde_json::from_slice(&bytes).expect("CLI emitted invalid JSON")
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn roadmap_add_list_freeze_unfreeze_remove_round_trip() {
    if !require_smoke_env() {
        panic!("DATABASE_URL and REDIS_URL must be set for this test");
    }
    let slug = unique_slug("roadmap-smoke");

    let added_len_before = stream_len(STREAM_ROADMAP_ADDED);
    let removed_len_before = stream_len(STREAM_ROADMAP_REMOVED);

    let add = telec()
        .args(["roadmap", "add", &slug, "--description", "smoke entry"])
        .assert()
        .success();
    let added = parse_json_stdout(&add);
    assert_eq!(added["slug"], slug);
    assert_eq!(added["frozen"], Value::Bool(false));

    let list = telec()
        .args(["roadmap", "list", "--json"])
        .assert()
        .success();
    let listed: Value = parse_json_stdout(&list);
    let entries = listed.as_array().expect("roadmap list returns JSON array");
    let present = entries
        .iter()
        .any(|e| e.get("slug").and_then(Value::as_str) == Some(slug.as_str()));
    assert!(present, "roadmap list did not contain the newly added slug");

    let frozen = telec()
        .args(["roadmap", "freeze", &slug])
        .assert()
        .success();
    assert_eq!(parse_json_stdout(&frozen)["frozen"], Value::Bool(true));

    let unfrozen = telec()
        .args(["roadmap", "unfreeze", &slug])
        .assert()
        .success();
    assert_eq!(parse_json_stdout(&unfrozen)["frozen"], Value::Bool(false));

    telec()
        .args(["roadmap", "remove", &slug])
        .assert()
        .success();

    assert_eq!(
        stream_len(STREAM_ROADMAP_ADDED),
        added_len_before + 1,
        "workflow.roadmap.entry_added not appended to Redis Streams"
    );
    assert_eq!(
        stream_len(STREAM_ROADMAP_REMOVED),
        removed_len_before + 1,
        "workflow.roadmap.entry_removed not appended to Redis Streams"
    );
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn roadmap_migrate_icebox_defers_to_v1() {
    if !require_smoke_env() {
        panic!("DATABASE_URL and REDIS_URL must be set for this test");
    }
    telec()
        .args(["roadmap", "migrate-icebox"])
        .assert()
        .code(EXIT_DEFERRED_TO_V1);
}

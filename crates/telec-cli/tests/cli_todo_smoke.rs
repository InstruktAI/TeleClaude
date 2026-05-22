//! Smoke tests for the `telec todo` subtree.
//!
//! These tests round-trip a todo through `create`, `show`, and `remove`
//! against a real Postgres + Redis stack. They are still `#[ignore]`-gated so
//! a plain `cargo test` does not require the docker-compose dev services to
//! be up; opt in with `cargo test -p telec-cli -- --ignored` or via the
//! `make test-rust-integration` target which orchestrates docker-compose
//! around the run (reviewer Important-2).
//!
//! Assertions parse the CLI's JSON output and inspect structured fields
//! instead of substring-matching on stdout (reviewer Important-3). Event
//! emission is verified by reading the Redis Streams `XLEN` before and
//! after the CLI invocation, locking the wire contract that the H1 bridge
//! depends on.

use std::sync::atomic::{AtomicU32, Ordering};

use assert_cmd::Command;
use serde_json::Value;

static SUFFIX: AtomicU32 = AtomicU32::new(0);

/// Channel constants mirror `workflow::events::CHANNEL_*`. The redis client
/// in the smoke fixture reads the Streams key, so we prepend the
/// `events:` prefix used by `event_bus::EventBus::emit`.
const STREAM_TODO_CREATED: &str = "events:workflow.todo.created";
const STREAM_TODO_DELETED: &str = "events:workflow.todo.deleted";
const STREAM_ARTIFACT_WRITTEN: &str = "events:workflow.artifact.written";
const STREAM_ROADMAP_FROZEN: &str = "events:workflow.roadmap.entry_frozen";
const STREAM_ROADMAP_UNFROZEN: &str = "events:workflow.roadmap.entry_unfrozen";

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
fn todo_create_show_remove_round_trip() {
    if !require_smoke_env() {
        panic!("DATABASE_URL and REDIS_URL must be set for this test");
    }
    let slug = unique_slug("cli-smoke");

    let created_len_before = stream_len(STREAM_TODO_CREATED);
    let artifact_len_before = stream_len(STREAM_ARTIFACT_WRITTEN);
    let deleted_len_before = stream_len(STREAM_TODO_DELETED);

    let create = telec()
        .args([
            "todo",
            "create",
            &slug,
            "--kind",
            "feature",
            "--input",
            "smoke-test input",
        ])
        .assert()
        .success();
    let create_payload = parse_json_stdout(&create);
    assert_eq!(create_payload["slug"], slug);
    assert_eq!(create_payload["kind"], "feature");
    // RV2: new todos persist with PrdDrafting, never Draft.
    assert_eq!(create_payload["lifecycle_phase"], "prd_drafting");

    let show = telec().args(["todo", "show", &slug]).assert().success();
    let show_payload = parse_json_stdout(&show);
    assert_eq!(show_payload["slug"], slug);
    assert_eq!(show_payload["lifecycle_phase"], "prd_drafting");

    telec().args(["todo", "remove", &slug]).assert().success();

    // The create call fires TodoCreated + ArtifactWritten, the remove fires
    // TodoDeleted. All three must reach Redis Streams for the H1 bridge to
    // see them — that's the wire contract this test locks (Important-2).
    assert_eq!(
        stream_len(STREAM_TODO_CREATED),
        created_len_before + 1,
        "workflow.todo.created not appended to Redis Streams"
    );
    assert_eq!(
        stream_len(STREAM_ARTIFACT_WRITTEN),
        artifact_len_before + 1,
        "workflow.artifact.written not appended to Redis Streams"
    );
    assert_eq!(
        stream_len(STREAM_TODO_DELETED),
        deleted_len_before + 1,
        "workflow.todo.deleted not appended to Redis Streams"
    );
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn todo_list_freeze_unfreeze_round_trip() {
    if !require_smoke_env() {
        panic!("DATABASE_URL and REDIS_URL must be set for this test");
    }
    let slug = unique_slug("todo-list-smoke");

    let frozen_len_before = stream_len(STREAM_ROADMAP_FROZEN);
    let unfrozen_len_before = stream_len(STREAM_ROADMAP_UNFROZEN);

    telec()
        .args([
            "todo",
            "create",
            &slug,
            "--kind",
            "feature",
            "--input",
            "todo list smoke input",
        ])
        .assert()
        .success();

    let list = telec().args(["todo", "list", "--json"]).assert().success();
    let listed: Value = parse_json_stdout(&list);
    let entries = listed.as_array().expect("todo list returns JSON array");
    let present = entries
        .iter()
        .any(|e| e.get("slug").and_then(Value::as_str) == Some(slug.as_str()));
    assert!(present, "todo list did not contain the newly created slug");

    let frozen = telec().args(["todo", "freeze", &slug]).assert().success();
    assert_eq!(parse_json_stdout(&frozen)["frozen"], Value::Bool(true));

    let unfrozen = telec().args(["todo", "unfreeze", &slug]).assert().success();
    assert_eq!(parse_json_stdout(&unfrozen)["frozen"], Value::Bool(false));

    telec().args(["todo", "remove", &slug]).assert().success();

    assert_eq!(
        stream_len(STREAM_ROADMAP_FROZEN),
        frozen_len_before + 1,
        "workflow.roadmap.entry_frozen not appended to Redis Streams"
    );
    assert_eq!(
        stream_len(STREAM_ROADMAP_UNFROZEN),
        unfrozen_len_before + 1,
        "workflow.roadmap.entry_unfrozen not appended to Redis Streams"
    );
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn deferred_design_subcommand_exits_two() {
    if !require_smoke_env() {
        panic!("DATABASE_URL and REDIS_URL must be set for this test");
    }
    telec()
        .args(["todo", "design", "some-slug"])
        .assert()
        .code(EXIT_DEFERRED_TO_V1);
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn todo_create_without_input_artifact_fails() {
    // RV2 boundary check: the CLI refuses creation without --input.
    if !require_smoke_env() {
        panic!("DATABASE_URL and REDIS_URL must be set for this test");
    }
    let slug = unique_slug("cli-smoke-no-input");
    telec()
        .args(["todo", "create", &slug, "--kind", "feature"])
        .assert()
        .failure();
}

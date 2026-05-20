//! Smoke tests for the `telec workflow todo create` surface.
//!
//! `#[ignore]`-gated; requires Postgres + Redis (docker-compose dev stack).
//! Assertions use structured JSON from CLI output, Postgres rows, and Redis
//! stream envelopes instead of substring matching rendered stdout.

use std::sync::atomic::{AtomicU32, Ordering};

use assert_cmd::Command;
use redis::Value as RedisValue;
use serde_json::Value;
use sqlx::PgPool;
use tempfile::NamedTempFile;

static SUFFIX: AtomicU32 = AtomicU32::new(0);

const STREAM_TODO_CREATED: &str = "events:workflow.todo.created";

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

fn require_smoke_env() {
    if std::env::var("DATABASE_URL").is_err() || std::env::var("REDIS_URL").is_err() {
        panic!("DATABASE_URL and REDIS_URL must be set for this test");
    }
}

async fn pg_pool() -> PgPool {
    PgPool::connect(&std::env::var("DATABASE_URL").expect("DATABASE_URL must be set for smoke"))
        .await
        .expect("connect Postgres")
}

fn parse_json_stdout(out: &assert_cmd::assert::Assert) -> Value {
    let bytes = out.get_output().stdout.clone();
    serde_json::from_slice(&bytes).expect("CLI emitted invalid JSON")
}

async fn input_artifact_content(pool: &PgPool, slug: &str) -> String {
    sqlx::query_scalar(
        "select a.content
         from workflow.artifacts a
         join workflow.todos t on t.id = a.todo_id
         where t.slug = $1 and a.name = 'input'::workflow.artifact_name
         order by a.updated_at desc
         limit 1",
    )
    .bind(slug)
    .fetch_one(pool)
    .await
    .expect("read input artifact")
}

async fn dependency_slugs(pool: &PgPool, slug: &str) -> Vec<String> {
    sqlx::query_scalar(
        "select depends_on
         from workflow.roadmap_deps
         where slug = $1
         order by depends_on asc",
    )
    .bind(slug)
    .fetch_all(pool)
    .await
    .expect("read dependency slugs")
}

fn latest_created_envelope() -> Value {
    let url = std::env::var("REDIS_URL").expect("REDIS_URL must be set for smoke");
    let client = redis::Client::open(url).expect("connect redis");
    let mut conn = client.get_connection().expect("redis conn");
    let reply = redis::cmd("XREVRANGE")
        .arg(STREAM_TODO_CREATED)
        .arg("+")
        .arg("-")
        .arg("COUNT")
        .arg(1)
        .query::<RedisValue>(&mut conn)
        .expect("XREVRANGE latest todo created event");

    let RedisValue::Array(entries) = reply else {
        panic!("Redis XREVRANGE returned unexpected top-level shape");
    };
    let Some(RedisValue::Array(entry)) = entries.first() else {
        panic!("Redis stream has no todo created entries");
    };
    let Some(RedisValue::Array(fields)) = entry.get(1) else {
        panic!("Redis stream entry has no fields array");
    };

    let payload = fields
        .chunks(2)
        .find_map(|chunk| match chunk {
            [key, value] if redis_string(key).as_deref() == Some("payload") => redis_string(value),
            _ => None,
        })
        .expect("Redis stream entry has no payload field");

    serde_json::from_str(&payload).expect("Redis payload field contains invalid JSON")
}

fn redis_string(value: &RedisValue) -> Option<String> {
    match value {
        RedisValue::BulkString(bytes) => String::from_utf8(bytes.clone()).ok(),
        RedisValue::SimpleString(value) => Some(value.clone()),
        _ => None,
    }
}

#[tokio::test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
async fn workflow_create_forwards_positional_content_to_input_artifact() {
    require_smoke_env();
    let pool = pg_pool().await;
    let slug = unique_slug("workflow-create-positional");

    let create = telec()
        .args([
            "workflow",
            "todo",
            "create",
            &slug,
            "positional smoke content",
        ])
        .assert()
        .success();
    let payload = parse_json_stdout(&create);

    assert_eq!(payload["slug"], slug);
    assert_eq!(
        input_artifact_content(&pool, &slug).await,
        "positional smoke content"
    );
}

#[tokio::test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
async fn workflow_create_reads_input_file_content_to_input_artifact() {
    require_smoke_env();
    let pool = pg_pool().await;
    let slug = unique_slug("workflow-create-file");
    let file = NamedTempFile::new().expect("create temp input file");
    std::fs::write(file.path(), "file smoke content\n").expect("write temp input file");

    let create = telec()
        .args([
            "workflow",
            "todo",
            "create",
            &slug,
            "--input-file",
            file.path().to_str().expect("temp path is valid UTF-8"),
        ])
        .assert()
        .success();
    let payload = parse_json_stdout(&create);

    assert_eq!(payload["slug"], slug);
    assert_eq!(
        input_artifact_content(&pool, &slug).await,
        "file smoke content\n"
    );
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn workflow_create_silent_emits_non_pickup_created_payload() {
    require_smoke_env();
    let slug = unique_slug("workflow-create-silent");

    let create = telec()
        .args([
            "workflow",
            "todo",
            "create",
            &slug,
            "silent smoke content",
            "--silent",
        ])
        .assert()
        .success();
    let output = parse_json_stdout(&create);
    let envelope = latest_created_envelope();

    assert_eq!(output["slug"], slug);
    assert_eq!(envelope["payload"]["slug"], slug);
    assert_eq!(envelope["payload"]["creation_mode"], "silent");
    assert_eq!(envelope["payload"]["pickup_requested"], Value::Bool(false));
}

#[tokio::test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
async fn workflow_create_accepts_comma_and_repeated_after_as_identical_dep_sets() {
    require_smoke_env();
    let pool = pg_pool().await;
    let comma_slug = unique_slug("workflow-create-after-comma");
    let repeated_slug = unique_slug("workflow-create-after-repeated");

    let comma = telec()
        .args([
            "workflow",
            "todo",
            "create",
            &comma_slug,
            "comma dependencies",
            "--after",
            "a,b,c",
        ])
        .assert()
        .success();
    let repeated = telec()
        .args([
            "workflow",
            "todo",
            "create",
            &repeated_slug,
            "repeated dependencies",
            "--after",
            "a",
            "--after",
            "b",
            "--after",
            "c",
        ])
        .assert()
        .success();

    assert_eq!(
        parse_json_stdout(&comma)["after"],
        parse_json_stdout(&repeated)["after"]
    );
    assert_eq!(
        dependency_slugs(&pool, &comma_slug).await,
        dependency_slugs(&pool, &repeated_slug).await
    );
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn workflow_create_rejects_empty_positional_content_without_input_file() {
    require_smoke_env();
    let slug = unique_slug("workflow-create-empty");

    telec()
        .args(["workflow", "todo", "create", &slug, ""])
        .assert()
        .failure();
}

#[test]
#[ignore = "requires Postgres + Redis (docker-compose dev stack)"]
fn workflow_create_rejects_positional_content_plus_input_file_at_parse_boundary() {
    let slug = unique_slug("workflow-create-conflict");
    let file = NamedTempFile::new().expect("create temp input file");
    std::fs::write(file.path(), "file smoke content").expect("write temp input file");

    telec()
        .args([
            "workflow",
            "todo",
            "create",
            &slug,
            "positional smoke content",
            "--input-file",
            file.path().to_str().expect("temp path is valid UTF-8"),
        ])
        .assert()
        .failure();
}

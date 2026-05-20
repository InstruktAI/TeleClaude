//! Integration tests for `observability::init`.
//!
//! `init` installs a global subscriber and returns a `WorkerGuard`. Because
//! the subscriber install is once-per-process and the tests share a process,
//! one test exercises the successful end-to-end path (asserts the on-disk
//! line shape) and the next test, ordered by name to follow it, observes
//! the documented `AlreadyInitialized` behavior on the second call.
//!
//! The non-blocking writer batches lines on a background thread. To force a
//! flush before reading the file, **drop the `WorkerGuard`** — that signals
//! the background thread to drain its channel and join. Tests rely on this
//! explicitly via `drop(guard)` before opening the log file.
//!
//! Tests share a process-wide `Mutex` because they mutate environment
//! variables and call the once-per-process `init`.

use std::io::Read;
use std::path::PathBuf;
use std::sync::Mutex;

use tempfile::TempDir;

/// Serializes the env-mutating tests so they run cleanly under
/// `cargo test`'s default thread pool.
static SUITE_LOCK: Mutex<()> = Mutex::new(());

fn read_log(path: &PathBuf) -> String {
    let mut file = std::fs::File::open(path)
        .unwrap_or_else(|e| panic!("expected log file at {}: {e}", path.display()));
    let mut buf = String::new();
    file.read_to_string(&mut buf).unwrap();
    buf
}

/// End-to-end: `init` creates the directory, opens the file, installs a
/// subscriber, and subsequent `tracing` events render in logfmt with the
/// expected structural shape on disk.
///
/// Doubles as the idempotency test — a second `init` call must return
/// `AlreadyInitialized` rather than panic.
#[test]
fn init_creates_directory_writes_logfmt_and_is_idempotent() {
    let _guard = SUITE_LOCK.lock().unwrap_or_else(|e| e.into_inner());

    let tmp = TempDir::new().expect("tempdir");
    let log_dir = tmp.path().join("nested").join("logs");
    let log_path = log_dir.join("test-source.log");

    // Sanity: the nested directory does not exist yet — init must create it.
    assert!(!log_dir.exists());

    // Clear inherited env so the test is hermetic, then point init at the temp dir.
    std::env::remove_var("INSTRUKT_AI_LOG_ROOT");
    std::env::remove_var("TELECLAUDE_LOG_LEVEL");
    std::env::remove_var("RUST_LOG");
    std::env::set_var("INSTRUKT_AI_LOG_DIR", &log_dir);

    let worker_guard = observability::init("test-source").expect("first init succeeds");

    // mkdir -p worked.
    assert!(log_dir.is_dir(), "init must create parent directories");

    tracing::info!(slug = "my-todo", count = 7i64, "todo created");

    // Flush by dropping the worker guard. The non-blocking writer batches on
    // a background thread; the guard's drop drains the channel and joins.
    // After this point the line is on disk.
    drop(worker_guard);

    let contents = read_log(&log_path);
    let line = contents
        .lines()
        .next()
        .expect("at least one line was written");

    assert_structural_shape(line);

    // Idempotency: second init must not panic; it returns the documented error.
    // (The subscriber installed by the first call remains active; the second
    // call's guard would be discarded anyway, so we ignore the Ok arm too.)
    match observability::init("test-source") {
        Ok(_g) => panic!("second init should yield AlreadyInitialized, got Ok"),
        Err(observability::InitError::AlreadyInitialized) => {}
        Err(other) => panic!("second init should yield AlreadyInitialized, got {other:?}"),
    }

    std::env::remove_var("INSTRUKT_AI_LOG_DIR");
}

/// Pin the on-disk line shape so accidental regressions in field order,
/// quoting, level naming, or timestamp format are caught.
///
/// Snapshotting the timestamp directly would be flaky (it's `now()`); instead
/// we replace its value with a placeholder and snapshot the rest by hand.
/// `insta` would buy little here — the shape is small and the assertions
/// describe intent directly. (Matches the brief's "snapshot manually" carve-out.)
fn assert_structural_shape(line: &str) {
    // Split off the timestamp (first whitespace-delimited token).
    let (ts, rest) = line
        .split_once(' ')
        .expect("line must have at least one space");

    // Timestamp shape: 24 chars, YYYY-MM-DDTHH:MM:SS.mmmZ.
    assert_eq!(
        ts.len(),
        24,
        "timestamp length: expected 24 chars (millisecond precision + Z), got {ts:?}",
    );
    assert!(ts.ends_with('Z'), "timestamp must end with Z, got {ts:?}");
    assert_eq!(
        &ts[10..11],
        "T",
        "timestamp must separate date/time with T, got {ts:?}",
    );
    assert_eq!(
        &ts[19..20],
        ".",
        "timestamp must have fractional seconds, got {ts:?}",
    );

    // The remainder is the canonical fixed-shape line — pinned exactly so any
    // field reorder, requoting, or level rename trips the assertion.
    let expected = r#"level=INFO logger=init msg="todo created" count=7 slug=my-todo"#;
    assert_eq!(rest, expected);
}

//! observability — `tracing` wrapper emitting `instrukt_ai_logging` logfmt lines.
//!
//! Each binary calls [`init`] at startup with its source name and **holds the
//! returned [`WorkerGuard`]** for process lifetime. Output goes to
//! `/var/log/instrukt-ai/teleclaude/<source>.log` in the same logfmt schema
//! the v1 Python `instrukt_ai_logging` library produces, so the existing
//! `instrukt-ai-logs` query tool reads v1 and v2 lines indistinguishably.
//!
//! # Concurrency model
//!
//! Writes are non-blocking on the calling thread. Internally, the subscriber
//! sends each formatted line over an in-memory channel to a dedicated
//! background thread that performs the actual file I/O via
//! [`WatchedFileWriter`]. The returned [`WorkerGuard`] keeps that background
//! thread alive — dropping it (or letting `main` return without binding it)
//! drains pending writes and joins the thread. **Do not let the guard go out
//! of scope before the process is ready to exit** or buffered events will be
//! lost.
//!
//! # External log rotation
//!
//! The file writer cooperates with external rotation tools (logrotate,
//! newsyslog) by stat'ing the configured path before each write and reopening
//! it if the inode changed. This matches the Python `WatchedFileHandler`
//! pattern and keeps log rotation an ops concern, not an application concern.
//! No application-side rotation, no SIGHUP handlers required.
//!
//! # Environment variables
//!
//! - `INSTRUKT_AI_LOG_DIR` — full override of the log directory (test/dev
//!   convenience). Logs land at `<INSTRUKT_AI_LOG_DIR>/<source>.log`.
//! - `INSTRUKT_AI_LOG_ROOT` — v1-parity override of the log *root*. Logs land
//!   at `<INSTRUKT_AI_LOG_ROOT>/teleclaude/<source>.log`. Ignored when
//!   `INSTRUKT_AI_LOG_DIR` is set.
//! - `TELECLAUDE_LOG_LEVEL` — directive parsed by `tracing_subscriber`'s
//!   `EnvFilter` (accepts bare level names like `INFO` or per-target
//!   directives like `teleclaude=debug`). Takes precedence over `RUST_LOG`.
//! - `RUST_LOG` — fallback directive when `TELECLAUDE_LOG_LEVEL` is unset.
//!
//! # Format
//!
//! Each event renders as a single line:
//!
//! ```text
//! 2026-05-16T12:34:56.789Z level=INFO logger=my_crate::module msg="hello" key=value
//! ```
//!
//! Field names, ordering, quoting rules, the millisecond-precision UTC
//! timestamp, secret redaction (Telegram bot tokens, `Bearer` tokens,
//! OpenAI-style `sk-` keys), and message truncation at 4000 characters all
//! match the Python `LogfmtFormatter` byte-for-byte so the `instrukt-ai-logs`
//! merge tool reads both streams indistinguishably.

mod config;
mod file_writer;
mod format;

use std::io;
use std::path::PathBuf;

use tracing_appender::non_blocking::WorkerGuard;
use tracing_subscriber::filter::EnvFilter;
use tracing_subscriber::util::SubscriberInitExt;

use crate::file_writer::WatchedFileWriter;
use crate::format::LogfmtFormatter;

/// Errors returned by [`init`].
#[derive(Debug, thiserror::Error)]
pub enum InitError {
    /// Failed to create the log directory or open the log file.
    #[error("io error preparing log file at {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: io::Error,
    },
    /// `TELECLAUDE_LOG_LEVEL` or `RUST_LOG` was set to an invalid filter directive.
    #[error("invalid log filter directive {directive:?}: {message}")]
    InvalidFilter { directive: String, message: String },
    /// A global tracing subscriber was already installed for this process.
    ///
    /// `init` is idempotent in that it never panics on a second call, but the
    /// second call has no effect — the subscriber installed by the first call
    /// remains active. Callers that observe this error should treat it as a
    /// no-op.
    #[error("logging subscriber already initialized for this process")]
    AlreadyInitialized,
}

/// Initialize the global `tracing` subscriber for this process.
///
/// `source` is the logical identity of the producing process (e.g. `"telec"`,
/// `"telec-daemon"`). It selects the log file name within the
/// `instrukt-ai/teleclaude/` log directory.
///
/// Returns a [`WorkerGuard`] that **must be held** by the caller for the
/// process's lifetime. Dropping the guard drains the non-blocking writer's
/// buffer and joins the background I/O thread. Letting it fall out of scope
/// before the process is ready to exit will silently lose buffered log lines.
///
/// Calling this function a second time within the same process returns
/// [`InitError::AlreadyInitialized`] without modifying the active subscriber.
/// Callers in that path should treat the result as a no-op and discard the
/// error (no guard is returned, but the original install's guard is still
/// active elsewhere).
pub fn init(source: &str) -> Result<WorkerGuard, InitError> {
    let log_path = config::resolve_log_path(source);

    if let Some(parent) = log_path.parent() {
        std::fs::create_dir_all(parent).map_err(|source| InitError::Io {
            path: log_path.clone(),
            source,
        })?;
    }

    let watched = WatchedFileWriter::open(log_path.clone()).map_err(|source| InitError::Io {
        path: log_path.clone(),
        source,
    })?;

    let (non_blocking, guard) = tracing_appender::non_blocking(watched);

    let filter = build_env_filter()?;

    // Install the subscriber FIRST. Order matters: `LogTracer::init` causes
    // the global tracing dispatcher to be read on each forwarded log call,
    // and `dispatcher::get_default` will lazily install a no-op default if
    // no subscriber is present yet. If we installed the bridge before our
    // subscriber, a single transient `log!` (e.g. from `tracing_appender`'s
    // worker thread starting up) would lock in the no-op default and our
    // own `try_init` below would then fail with `AlreadyInitialized`.
    tracing_subscriber::fmt()
        .with_writer(non_blocking)
        .with_env_filter(filter)
        .event_format(LogfmtFormatter)
        .finish()
        .try_init()
        .map_err(|_| InitError::AlreadyInitialized)?;

    // Now bridge the older `log` crate into `tracing` so dependents using
    // `log` (e.g. transitive deps like `hyper`, `reqwest`) flow through the
    // subscriber we just installed. `log::set_logger` returns an error if
    // already set, which we tolerate so multiple `init` calls in test suites
    // don't fail on the bridge install.
    let _ = tracing_log::LogTracer::init();

    Ok(guard)
}

fn build_env_filter() -> Result<EnvFilter, InitError> {
    let (var_name, directive) = match std::env::var("TELECLAUDE_LOG_LEVEL") {
        Ok(v) if !v.is_empty() => ("TELECLAUDE_LOG_LEVEL", v),
        _ => match std::env::var("RUST_LOG") {
            Ok(v) if !v.is_empty() => ("RUST_LOG", v),
            _ => ("default", "info".to_string()),
        },
    };

    EnvFilter::try_new(&directive).map_err(|e| InitError::InvalidFilter {
        directive: format!("{var_name}={directive}"),
        message: e.to_string(),
    })
}

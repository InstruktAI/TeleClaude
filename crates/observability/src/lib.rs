//! observability — `tracing` wrapper emitting `instrukt_ai_logging` logfmt lines.
//!
//! Each binary calls [`init`] at startup with its source name. Output goes to
//! `/var/log/instrukt-ai/teleclaude/<source>.log` in the same logfmt schema
//! the v1 Python `instrukt_ai_logging` library produces, so the existing
//! `instrukt-ai-logs` query tool reads v1 and v2 lines indistinguishably.
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
//! Field names, ordering, quoting rules, and the millisecond-precision UTC
//! timestamp match the Python `LogfmtFormatter` byte-for-byte so the
//! `instrukt-ai-logs` merge tool's timestamp parser (which splits on the
//! first space) reads both streams.

mod config;
mod format;

use std::fs::OpenOptions;
use std::io;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use tracing_subscriber::filter::EnvFilter;
use tracing_subscriber::fmt::writer::MakeWriter;
use tracing_subscriber::util::SubscriberInitExt;

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
/// Calling this function a second time within the same process returns
/// [`InitError::AlreadyInitialized`] without modifying the active subscriber.
pub fn init(source: &str) -> Result<(), InitError> {
    let log_path = config::resolve_log_path(source);

    if let Some(parent) = log_path.parent() {
        std::fs::create_dir_all(parent).map_err(|source| InitError::Io {
            path: log_path.clone(),
            source,
        })?;
    }

    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|source| InitError::Io {
            path: log_path.clone(),
            source,
        })?;

    let writer = FileMakeWriter::new(file);
    let filter = build_env_filter()?;

    tracing_subscriber::fmt()
        .with_writer(writer)
        .with_env_filter(filter)
        .event_format(LogfmtFormatter)
        .finish()
        .try_init()
        .map_err(|_| InitError::AlreadyInitialized)
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

/// `MakeWriter` impl over a shared file handle.
///
/// `tracing-subscriber` calls `make_writer` per event; we hand back a guard
/// that locks the shared `Mutex<File>` so multiple events serialize cleanly
/// even if the runtime spawns concurrent writers.
struct FileMakeWriter {
    file: Arc<Mutex<std::fs::File>>,
}

impl FileMakeWriter {
    fn new(file: std::fs::File) -> Self {
        Self {
            file: Arc::new(Mutex::new(file)),
        }
    }
}

impl<'a> MakeWriter<'a> for FileMakeWriter {
    type Writer = FileGuardWriter;

    fn make_writer(&'a self) -> Self::Writer {
        FileGuardWriter {
            file: Arc::clone(&self.file),
        }
    }
}

struct FileGuardWriter {
    file: Arc<Mutex<std::fs::File>>,
}

impl io::Write for FileGuardWriter {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        let mut guard = self
            .file
            .lock()
            .map_err(|_| io::Error::other("log file mutex poisoned"))?;
        guard.write(buf)
    }

    fn flush(&mut self) -> io::Result<()> {
        let mut guard = self
            .file
            .lock()
            .map_err(|_| io::Error::other("log file mutex poisoned"))?;
        guard.flush()
    }
}

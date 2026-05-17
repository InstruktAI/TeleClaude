//! Error type for the config crate.
//!
//! Loader and effective-config functions surface failures as
//! [`ConfigError`]. Each variant maps to one classifiable failure mode the
//! caller may want to react to differently (missing file vs. parse error
//! vs. validation failure vs. overlay merge conflict).

use std::path::PathBuf;

/// Errors returned by the config crate.
#[derive(thiserror::Error, Debug)]
pub enum ConfigError {
    /// The requested config file did not exist.
    ///
    /// Loaders return this only when a path was supplied and the file is
    /// truly absent. The "no file at all" case (e.g. no project overlay
    /// configured) is represented by `Option::None`, not by this error.
    #[error("config file not found: {0}")]
    FileNotFound(PathBuf),

    /// YAML parsing failed for a known file.
    #[error("config parse failed: {file} — {error}")]
    ParseFailed { file: PathBuf, error: String },

    /// Schema validation rejected the loaded overlay.
    #[error("config validation failed: {0}")]
    ValidationFailed(String),

    /// Two overlays asserted incompatible values for the same field at a
    /// scope where merging is not defined.
    #[error("overlay merge conflict: field={field} reason={reason}")]
    MergeConflict { field: String, reason: String },

    /// A filesystem operation other than "file not found" failed.
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

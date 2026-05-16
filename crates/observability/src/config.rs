//! Environment-driven path resolution for the log file.
//!
//! Mirrors the v1 Python `instrukt_ai_logging` library's logic:
//!
//! - `INSTRUKT_AI_LOG_DIR` (TeleClaude-specific override): when set, the
//!   directory is used verbatim and the log file is `<dir>/<source>.log`.
//! - `INSTRUKT_AI_LOG_ROOT` (v1 parity): when set, the directory is
//!   `<root>/teleclaude/` and the log file is `<root>/teleclaude/<source>.log`.
//! - Otherwise the default `/var/log/instrukt-ai/teleclaude/<source>.log`.

use std::path::PathBuf;

const APP_NAME: &str = "teleclaude";
const DEFAULT_LOG_ROOT: &str = "/var/log/instrukt-ai";

pub(crate) fn resolve_log_path(source: &str) -> PathBuf {
    let dir = match std::env::var("INSTRUKT_AI_LOG_DIR") {
        Ok(v) if !v.is_empty() => PathBuf::from(v),
        _ => {
            let root = match std::env::var("INSTRUKT_AI_LOG_ROOT") {
                Ok(v) if !v.is_empty() => PathBuf::from(v),
                _ => PathBuf::from(DEFAULT_LOG_ROOT),
            };
            root.join(APP_NAME)
        }
    };
    dir.join(format!("{source}.log"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    // Tests in this module mutate process-wide env vars, so they must serialize.
    // The std `Mutex` is fine; this is a unit-test helper, not production code.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn with_env<F: FnOnce()>(vars: &[(&str, Option<&str>)], body: F) {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let prior: Vec<(String, Option<String>)> = vars
            .iter()
            .map(|(k, _)| (k.to_string(), std::env::var(k).ok()))
            .collect();
        for (k, v) in vars {
            match v {
                Some(val) => std::env::set_var(k, val),
                None => std::env::remove_var(k),
            }
        }
        body();
        for (k, v) in prior {
            match v {
                Some(val) => std::env::set_var(&k, val),
                None => std::env::remove_var(&k),
            }
        }
    }

    #[test]
    fn default_path_uses_var_log_instrukt_ai_teleclaude() {
        with_env(
            &[
                ("INSTRUKT_AI_LOG_DIR", None),
                ("INSTRUKT_AI_LOG_ROOT", None),
            ],
            || {
                let path = resolve_log_path("telec-daemon");
                assert_eq!(
                    path,
                    PathBuf::from("/var/log/instrukt-ai/teleclaude/telec-daemon.log"),
                );
            },
        );
    }

    #[test]
    fn log_root_override_appends_app_segment() {
        with_env(
            &[
                ("INSTRUKT_AI_LOG_DIR", None),
                ("INSTRUKT_AI_LOG_ROOT", Some("/tmp/x")),
            ],
            || {
                let path = resolve_log_path("worker-build");
                assert_eq!(path, PathBuf::from("/tmp/x/teleclaude/worker-build.log"),);
            },
        );
    }

    #[test]
    fn log_dir_override_skips_app_segment_and_wins_over_root() {
        with_env(
            &[
                ("INSTRUKT_AI_LOG_DIR", Some("/tmp/direct")),
                ("INSTRUKT_AI_LOG_ROOT", Some("/tmp/should-be-ignored")),
            ],
            || {
                let path = resolve_log_path("telec");
                assert_eq!(path, PathBuf::from("/tmp/direct/telec.log"));
            },
        );
    }
}

//! Per-TTY and global login-file resolution.
//!
//! Mirrors v1's [`teleclaude/cli/session_auth.py`] semantics: the user
//! runs `telec auth login <email>`, which writes
//!
//! - `~/.teleclaude/session-auth/{tty_key}.json` when a controlling TTY is
//!   present (where `tty_key` is the basename of the TTY path, e.g.
//!   `ttys003` for `/dev/ttys003`), and
//! - `~/.teleclaude/session-auth/global_identity.json` as a global fallback
//!   (always updated alongside the per-TTY file, per v1 "last login wins
//!   globally" rule).
//!
//! Resolution at startup walks the same order:
//!
//! 1. Per-TTY file (when a controlling TTY is detectable);
//! 2. Global fallback;
//! 3. None when neither file exists.
//!
//! The functions here are pure with respect to env vars and TTY detection
//! — the caller passes the relevant context in — so unit tests can drive
//! every branch without touching the real filesystem layout.

use std::ffi::{CStr, OsString};
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};

use serde::Deserialize;

use crate::errors::IdentityError;

/// Subdirectory under `$HOME` that holds the session-auth JSON files.
pub const SESSION_AUTH_SUBDIR: &str = ".teleclaude/session-auth";

/// File name used when no per-TTY file resolves and the global fallback
/// applies.
pub const GLOBAL_LOGIN_FILE_NAME: &str = "global_identity.json";

/// Try to discover the path of the controlling TTY for the current
/// process. Returns `None` when no TTY is attached (e.g. piped or running
/// under launchd).
pub fn detect_tty() -> Option<String> {
    // Try fds 0/1/2 in turn; the first one that resolves to a real TTY
    // path wins. Falls back to the `SSH_TTY` environment variable when
    // none of the fds are attached.
    for fd in [0, 1, 2] {
        // SAFETY: `libc::ttyname` returns a thread-local static buffer
        // or null; we copy the bytes out immediately so the returned
        // pointer is not held past the call.
        let raw = unsafe { libc::ttyname(fd) };
        if !raw.is_null() {
            // SAFETY: the pointer is non-null and points at a NUL-
            // terminated C string per ttyname(3); the OS guarantees
            // valid lifetime through the immediate `CStr::from_ptr` copy.
            let cstr = unsafe { CStr::from_ptr(raw) };
            let bytes = cstr.to_bytes().to_vec();
            let path = OsString::from_vec(bytes);
            if let Some(s) = path.to_str() {
                return Some(s.to_owned());
            }
        }
    }
    std::env::var("SSH_TTY").ok()
}

/// Convert a TTY path to its v1-compatible filesystem key.
///
/// `/dev/ttys003` → `ttys003`. The basename is what
/// `teleclaude/cli/session_auth.py` uses as the per-TTY file's stem.
pub fn tty_key(tty_path: &str) -> String {
    tty_path.rsplit('/').next().unwrap_or(tty_path).to_owned()
}

/// Compute the per-TTY auth file path for a given home dir and TTY.
pub fn per_tty_path(home_dir: &Path, tty_path: &str) -> PathBuf {
    home_dir
        .join(SESSION_AUTH_SUBDIR)
        .join(format!("{}.json", tty_key(tty_path)))
}

/// Compute the global auth file path for a given home dir.
pub fn global_login_path(home_dir: &Path) -> PathBuf {
    home_dir
        .join(SESSION_AUTH_SUBDIR)
        .join(GLOBAL_LOGIN_FILE_NAME)
}

#[derive(Debug, Clone, Deserialize)]
struct LoginPayload {
    email: String,
}

/// Read the email from a single login file. Returns `Ok(None)` when the
/// file is missing or empty, surfaces parse / IO errors otherwise.
pub fn read_login_file(path: &Path) -> Result<Option<String>, IdentityError> {
    match std::fs::read_to_string(path) {
        Ok(raw) => {
            let trimmed = raw.trim();
            if trimmed.is_empty() {
                return Ok(None);
            }
            // v1 supports both a JSON object {"email":"..."} and a raw
            // email-only line. Try JSON first, fall back to the raw
            // email when JSON parsing fails.
            if let Ok(payload) = serde_json::from_str::<LoginPayload>(trimmed) {
                return Ok(Some(normalize_email(&payload.email)));
            }
            if trimmed.contains('@') {
                return Ok(Some(normalize_email(trimmed)));
            }
            Err(IdentityError::AuthMalformed(format!(
                "login file {} did not contain a valid email",
                path.display()
            )))
        }
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(IdentityError::AuthMalformed(format!(
            "login file {} could not be read: {err}",
            path.display()
        ))),
    }
}

/// Resolve the login email for the current process, applying v1's
/// resolution order: per-TTY when `tty_path` is supplied, otherwise the
/// global file.
pub fn read_login_email(
    home_dir: &Path,
    tty_path: Option<&str>,
) -> Result<Option<String>, IdentityError> {
    if let Some(tty) = tty_path {
        if let Some(email) = read_login_file(&per_tty_path(home_dir, tty))? {
            return Ok(Some(email));
        }
    }
    read_login_file(&global_login_path(home_dir))
}

fn normalize_email(value: &str) -> String {
    value.trim().to_lowercase()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::write;
    use tempfile::tempdir;

    fn write_dir(home: &Path) {
        let dir = home.join(SESSION_AUTH_SUBDIR);
        std::fs::create_dir_all(&dir).expect("mkdir session-auth");
    }

    #[test]
    fn tty_key_strips_leading_dev_path() {
        assert_eq!(tty_key("/dev/ttys003"), "ttys003");
        assert_eq!(tty_key("ttys003"), "ttys003");
        assert_eq!(tty_key("/dev/pts/12"), "12");
    }

    #[test]
    fn read_login_file_json_payload_extracts_email() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("file.json");
        write(
            &path,
            r#"{"email":"Owner@Example.COM","tty":"/dev/ttys003","updated_at":"2026-05-17T12:00:00Z"}"#,
        )
        .expect("write");

        let email = read_login_file(&path).expect("read").expect("some email");
        assert_eq!(email, "owner@example.com");
    }

    #[test]
    fn read_login_file_plain_email_fallback() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("file.json");
        write(&path, "  Owner@Example.com\n").expect("write");

        let email = read_login_file(&path).expect("read").expect("some email");
        assert_eq!(email, "owner@example.com");
    }

    #[test]
    fn read_login_file_missing_returns_none() {
        let dir = tempdir().expect("tempdir");
        let result = read_login_file(&dir.path().join("absent.json")).expect("read");
        assert!(result.is_none());
    }

    #[test]
    fn read_login_file_malformed_yields_auth_malformed() {
        let dir = tempdir().expect("tempdir");
        let path = dir.path().join("garbage.json");
        write(&path, "not-an-email").expect("write");
        let err = read_login_file(&path).expect_err("expected AuthMalformed");
        assert!(matches!(err, IdentityError::AuthMalformed(_)));
    }

    #[test]
    fn read_login_email_prefers_per_tty_file() {
        let home = tempdir().expect("tempdir");
        write_dir(home.path());
        write(
            per_tty_path(home.path(), "/dev/ttys003"),
            r#"{"email":"per-tty@example.com"}"#,
        )
        .expect("write per-tty");
        write(
            global_login_path(home.path()),
            r#"{"email":"global@example.com"}"#,
        )
        .expect("write global");

        let email = read_login_email(home.path(), Some("/dev/ttys003"))
            .expect("read")
            .expect("some email");
        assert_eq!(email, "per-tty@example.com");
    }

    #[test]
    fn read_login_email_falls_back_to_global_when_per_tty_missing() {
        let home = tempdir().expect("tempdir");
        write_dir(home.path());
        write(
            global_login_path(home.path()),
            r#"{"email":"global@example.com"}"#,
        )
        .expect("write global");

        let email = read_login_email(home.path(), Some("/dev/ttys003"))
            .expect("read")
            .expect("some email");
        assert_eq!(email, "global@example.com");
    }

    #[test]
    fn read_login_email_uses_global_when_no_tty() {
        let home = tempdir().expect("tempdir");
        write_dir(home.path());
        write(
            global_login_path(home.path()),
            r#"{"email":"global@example.com"}"#,
        )
        .expect("write global");

        let email = read_login_email(home.path(), None)
            .expect("read")
            .expect("some email");
        assert_eq!(email, "global@example.com");
    }

    #[test]
    fn read_login_email_returns_none_when_neither_file_exists() {
        let home = tempdir().expect("tempdir");
        write_dir(home.path());

        let result = read_login_email(home.path(), Some("/dev/ttys003")).expect("read");
        assert!(result.is_none());
    }
}

//! Principal resolution across every transport TeleClaude supports.
//!
//! Resolution is centralized here; authorization happens in each service
//! that owns the resource being accessed. Every function in this module
//! returns a [`Principal`] — services pattern-match on it for their own
//! authorization decisions and never touch raw transport evidence.
//!
//! Two flavors of resolution:
//!
//! 1. **Pure** — `resolve_from_env`, `resolve_from_http_with`, and
//!    `resolve_from_session_token_with` take callbacks for env lookup and
//!    token validation. They are unit-testable without a database.
//! 2. **Service** — `IdentityService` (Wave D) composes the pure functions
//!    with a real `PgPool` and `TokenValidator`.

use std::path::Path;

use async_trait::async_trait;

use crate::errors::IdentityError;
use crate::login::{detect_tty, read_login_email};
use crate::models::{Principal, Role, Token};

/// Environment variable that carries the workspace owner's email
/// (single-user MVP fallback; see auth-model.md). Used only when no TTY
/// login file is present and no `TELEC_SESSION_TOKEN` is set.
pub const OWNER_EMAIL_ENV: &str = "TELECLAUDE_OWNER_EMAIL";

/// Environment variable that carries an agent session's auth token.
///
/// Daemon-spawned sessions inject this so subsequent CLI invocations
/// inside the session resolve as `Principal::AgentSession`.
pub const SESSION_TOKEN_ENV: &str = "TELEC_SESSION_TOKEN";

/// HTTP header carrying a session token issued by `issue_session_token`.
pub const HEADER_SESSION_TOKEN: &str = "x-session-token";

/// HTTP header carrying the TTY-scoped email of the human invoking telec.
pub const HEADER_TELEC_EMAIL: &str = "x-telec-email";

/// Abstract over the kind of inputs HTTP and session-token resolution take.
///
/// Production callers provide a database-backed implementation; tests
/// provide an in-memory map.
#[async_trait]
pub trait TokenValidator: Send + Sync {
    /// Look up the [`Principal`] a token authorizes.
    ///
    /// Implementations return
    /// - `Ok(principal)` for a live, unrevoked token,
    /// - `Err(IdentityError::TokenNotFound)` when the token does not exist,
    /// - `Err(IdentityError::TokenRevoked)` when `revoked_at` is set.
    async fn validate(&self, token: Token) -> Result<Principal, IdentityError>;
}

/// Resolve the current principal from the process environment alone
/// (no DB, no TTY filesystem).
///
/// Looks up `TELECLAUDE_OWNER_EMAIL` and, when set, returns
/// `Principal::Human { role: Owner }`. Otherwise surfaces
/// [`IdentityError::AuthMissing`].
///
/// Production callers normally use the richer
/// [`crate::resolve::resolve_from_env_with_login`] which composes this
/// env path with the TTY login files plus `TELEC_SESSION_TOKEN`
/// validation.
pub fn resolve_from_env() -> Result<Principal, IdentityError> {
    resolve_with(|key| std::env::var(key).ok())
}

/// Resolve a principal using a caller-supplied env lookup.
///
/// Exposed primarily for testability: production callers should use
/// [`resolve_from_env`]. Returns [`IdentityError::AuthMissing`] when
/// `TELECLAUDE_OWNER_EMAIL` is absent or empty.
pub fn resolve_with<F>(env_lookup: F) -> Result<Principal, IdentityError>
where
    F: Fn(&str) -> Option<String>,
{
    let raw = env_lookup(OWNER_EMAIL_ENV).unwrap_or_default();
    let email = raw.trim();
    if email.is_empty() {
        return Err(IdentityError::AuthMissing);
    }
    Ok(Principal::Human {
        email: email.to_string(),
        role: Role::Owner,
    })
}

/// Resolve a principal from the full v1-mirroring resolution stack —
/// session token (env), then per-TTY login file, then global login file,
/// then the single-user MVP `TELECLAUDE_OWNER_EMAIL` fallback.
///
/// `home_dir` is normally `$HOME`; tests pass a tempdir-scoped path.
/// `tty_path` is normally [`crate::login::detect_tty`]; tests pass an
/// explicit string. `env_lookup` and `validator` keep the function pure
/// with respect to the process environment and the token table.
///
/// Returns:
/// - `Principal::AgentSession { .. }` when a valid `TELEC_SESSION_TOKEN`
///   is present in the environment.
/// - `Principal::Human { role: Member }` when a TTY login file resolves
///   the email — `Member` is intentionally conservative; service-level
///   authorization promotes it based on configured roster.
/// - `Principal::Human { role: Owner }` when only
///   `TELECLAUDE_OWNER_EMAIL` is set (single-user MVP).
/// - [`IdentityError::AuthMissing`] when no evidence resolves.
pub async fn resolve_from_env_with_login<F, V>(
    env_lookup: F,
    home_dir: &Path,
    tty_path: Option<&str>,
    validator: &V,
) -> Result<Principal, IdentityError>
where
    F: Fn(&str) -> Option<String> + Send + Sync,
    V: TokenValidator + ?Sized,
{
    // 1. Session token (highest precedence — agent-driven path).
    if let Some(raw) = env_lookup(SESSION_TOKEN_ENV).filter(|v| !v.trim().is_empty()) {
        let token = Token::parse(raw.trim()).map_err(|_| IdentityError::InvalidToken)?;
        return validator.validate(token).await;
    }

    // 2. v1 TTY login file (per-TTY then global).
    if let Some(email) = read_login_email(home_dir, tty_path)? {
        return Ok(Principal::Human {
            email,
            role: Role::Member,
        });
    }

    // 3. MVP env fallback — single-user owner email.
    if let Some(raw) = env_lookup(OWNER_EMAIL_ENV).filter(|v| !v.trim().is_empty()) {
        return Ok(Principal::Human {
            email: raw.trim().to_string(),
            role: Role::Owner,
        });
    }

    Err(IdentityError::AuthMissing)
}

/// Production convenience: resolves home dir from `$HOME` and detects the
/// TTY via [`crate::login::detect_tty`]. Equivalent to
/// [`resolve_from_env_with_login`] for callers that do not need to inject
/// these for testing.
pub async fn resolve_from_environment<V: TokenValidator + ?Sized>(
    validator: &V,
) -> Result<Principal, IdentityError> {
    let home = std::env::var("HOME")
        .map_err(|_| IdentityError::AuthMalformed("HOME environment variable not set".into()))?;
    let tty = detect_tty();
    resolve_from_env_with_login(
        |key| std::env::var(key).ok(),
        Path::new(&home),
        tty.as_deref(),
        validator,
    )
    .await
}

/// Resolve a principal from a process environment that may carry either a
/// session token or an owner-email env var.
///
/// Precedence:
/// 1. `TELEC_SESSION_TOKEN` parsed and validated via `validator` — returns
///    the principal the token authorizes.
/// 2. `TELECLAUDE_OWNER_EMAIL` non-empty — returns
///    `Principal::Human { role: Owner }`.
/// 3. Otherwise — returns [`IdentityError::AuthMissing`].
pub async fn resolve_from_env_with<F, V>(
    env_lookup: F,
    validator: &V,
) -> Result<Principal, IdentityError>
where
    F: Fn(&str) -> Option<String> + Send + Sync,
    V: TokenValidator + ?Sized,
{
    if let Some(raw) = env_lookup(SESSION_TOKEN_ENV).filter(|v| !v.trim().is_empty()) {
        let token = Token::parse(raw.trim()).map_err(|_| IdentityError::InvalidToken)?;
        return validator.validate(token).await;
    }

    match env_lookup(OWNER_EMAIL_ENV).filter(|v| !v.trim().is_empty()) {
        Some(raw) => Ok(Principal::Human {
            email: raw.trim().to_string(),
            role: Role::Owner,
        }),
        None => Err(IdentityError::AuthMissing),
    }
}

/// Resolve a principal directly from a session token.
///
/// Thin wrapper over [`TokenValidator::validate`]. Exists as a named entry
/// point so middleware and tests can call the resolution flow without
/// reaching for the trait method directly.
pub async fn resolve_from_session_token_with<V: TokenValidator + ?Sized>(
    token: Token,
    validator: &V,
) -> Result<Principal, IdentityError> {
    validator.validate(token).await
}

/// Resolve a principal from HTTP headers.
///
/// Precedence (matches v1's [`teleclaude/api/auth.py`] flow):
/// 1. `x-session-token` present and valid — returns the token's principal.
/// 2. `x-telec-email` present — returns `Principal::Human { role: Member }`.
///    Role assignment when only the email is asserted is intentionally
///    conservative; the per-service authorization layer is responsible for
///    promoting the role from configuration where appropriate.
/// 3. No recognized headers — returns [`IdentityError::AuthMissing`].
///
/// `lookup` is a closure that returns the header value for a given
/// (lower-case) header name. Production callers wrap their concrete
/// header-map type with this closure; tests pass a `HashMap`-backed one.
pub async fn resolve_from_http_with<F, V>(
    lookup: F,
    validator: &V,
) -> Result<Principal, IdentityError>
where
    F: Fn(&str) -> Option<String> + Send + Sync,
    V: TokenValidator + ?Sized,
{
    if let Some(raw) = lookup(HEADER_SESSION_TOKEN).filter(|v| !v.trim().is_empty()) {
        let token = Token::parse(raw.trim()).map_err(|_| IdentityError::InvalidToken)?;
        return validator.validate(token).await;
    }

    if let Some(raw) = lookup(HEADER_TELEC_EMAIL).filter(|v| !v.trim().is_empty()) {
        return Ok(Principal::Human {
            email: raw.trim().to_string(),
            role: Role::Member,
        });
    }

    Err(IdentityError::AuthMissing)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::login::{global_login_path, per_tty_path, SESSION_AUTH_SUBDIR};
    use shared::SessionId;
    use std::collections::HashMap;
    use std::fs::{create_dir_all, write};
    use tempfile::tempdir;

    /// In-memory [`TokenValidator`] for unit tests. Maps tokens to
    /// principal values (live tokens) plus a separate set of revoked
    /// tokens — every resolution code path is exercised without touching
    /// Postgres.
    #[derive(Default)]
    struct MockValidator {
        live: HashMap<Token, Principal>,
        revoked: std::collections::HashSet<Token>,
    }

    impl MockValidator {
        fn with_live(mut self, token: Token, principal: Principal) -> Self {
            self.live.insert(token, principal);
            self
        }
        fn with_revoked(mut self, token: Token) -> Self {
            self.revoked.insert(token);
            self
        }
    }

    #[async_trait]
    impl TokenValidator for MockValidator {
        async fn validate(&self, token: Token) -> Result<Principal, IdentityError> {
            if self.revoked.contains(&token) {
                return Err(IdentityError::TokenRevoked);
            }
            self.live
                .get(&token)
                .cloned()
                .ok_or(IdentityError::TokenNotFound)
        }
    }

    fn agent_principal() -> Principal {
        Principal::AgentSession {
            session_id: SessionId::new(),
            role: Role::Member,
        }
    }

    #[test]
    fn resolves_owner_when_env_present() {
        let principal = resolve_with(|_| Some("owner@example.com".to_string()))
            .expect("expected owner principal");

        assert!(matches!(
            principal,
            Principal::Human { email, role: Role::Owner } if email == "owner@example.com"
        ));
    }

    #[test]
    fn returns_auth_missing_when_env_absent() {
        let result = resolve_with(|_| None);
        assert!(matches!(result, Err(IdentityError::AuthMissing)));
    }

    #[test]
    fn returns_auth_missing_when_env_blank() {
        let result = resolve_with(|_| Some("   ".to_string()));
        assert!(matches!(result, Err(IdentityError::AuthMissing)));
    }

    #[test]
    fn trims_whitespace_around_owner_email() {
        let principal = resolve_with(|_| Some("  owner@example.com  ".to_string()))
            .expect("expected owner principal");

        assert!(matches!(
            principal,
            Principal::Human { email, .. } if email == "owner@example.com"
        ));
    }

    #[tokio::test]
    async fn env_resolution_prefers_token_over_owner_email() {
        let token = Token::new();
        let validator = MockValidator::default().with_live(token, agent_principal());

        let env = HashMap::from([
            (SESSION_TOKEN_ENV.to_string(), token.to_string()),
            (OWNER_EMAIL_ENV.to_string(), "owner@example.com".to_string()),
        ]);

        let principal = resolve_from_env_with(|key| env.get(key).cloned(), &validator)
            .await
            .expect("token wins");

        assert!(matches!(principal, Principal::AgentSession { .. }));
    }

    #[tokio::test]
    async fn env_resolution_falls_back_to_owner_email() {
        let validator = MockValidator::default();
        let env = HashMap::from([(OWNER_EMAIL_ENV.to_string(), "owner@example.com".to_string())]);

        let principal = resolve_from_env_with(|key| env.get(key).cloned(), &validator)
            .await
            .expect("fallback to email");

        assert!(matches!(
            principal,
            Principal::Human {
                role: Role::Owner,
                ..
            }
        ));
    }

    #[tokio::test]
    async fn env_resolution_yields_auth_missing_when_no_evidence() {
        let validator = MockValidator::default();
        let env: HashMap<String, String> = HashMap::new();

        let err = resolve_from_env_with(|key| env.get(key).cloned(), &validator)
            .await
            .expect_err("expected AuthMissing");

        assert!(matches!(err, IdentityError::AuthMissing));
    }

    #[tokio::test]
    async fn env_resolution_yields_invalid_token_for_unparseable_value() {
        let validator = MockValidator::default();
        let env = HashMap::from([(SESSION_TOKEN_ENV.to_string(), "not-a-uuid".to_string())]);

        let err = resolve_from_env_with(|key| env.get(key).cloned(), &validator)
            .await
            .expect_err("expected InvalidToken");

        assert!(matches!(err, IdentityError::InvalidToken));
    }

    #[tokio::test]
    async fn token_resolution_surfaces_revoked_error() {
        let token = Token::new();
        let validator = MockValidator::default().with_revoked(token);

        let err = resolve_from_session_token_with(token, &validator)
            .await
            .expect_err("expected TokenRevoked");

        assert!(matches!(err, IdentityError::TokenRevoked));
    }

    #[tokio::test]
    async fn token_resolution_surfaces_not_found_error() {
        let validator = MockValidator::default();

        let err = resolve_from_session_token_with(Token::new(), &validator)
            .await
            .expect_err("expected TokenNotFound");

        assert!(matches!(err, IdentityError::TokenNotFound));
    }

    #[tokio::test]
    async fn http_resolution_prefers_token_header() {
        let token = Token::new();
        let validator = MockValidator::default().with_live(token, agent_principal());
        let headers = HashMap::from([
            (HEADER_SESSION_TOKEN.to_string(), token.to_string()),
            (
                HEADER_TELEC_EMAIL.to_string(),
                "owner@example.com".to_string(),
            ),
        ]);

        let principal = resolve_from_http_with(|name| headers.get(name).cloned(), &validator)
            .await
            .expect("token wins");

        assert!(matches!(principal, Principal::AgentSession { .. }));
    }

    #[tokio::test]
    async fn http_resolution_returns_human_for_email_header_only() {
        let validator = MockValidator::default();
        let headers = HashMap::from([(
            HEADER_TELEC_EMAIL.to_string(),
            "owner@example.com".to_string(),
        )]);

        let principal = resolve_from_http_with(|name| headers.get(name).cloned(), &validator)
            .await
            .expect("human fallback");

        assert!(matches!(
            principal,
            Principal::Human {
                role: Role::Member,
                ..
            }
        ));
    }

    #[tokio::test]
    async fn http_resolution_returns_auth_missing_when_no_headers() {
        let validator = MockValidator::default();
        let headers: HashMap<String, String> = HashMap::new();

        let err = resolve_from_http_with(|name| headers.get(name).cloned(), &validator)
            .await
            .expect_err("expected AuthMissing");

        assert!(matches!(err, IdentityError::AuthMissing));
    }

    fn seed_session_auth_dir(home: &Path) {
        create_dir_all(home.join(SESSION_AUTH_SUBDIR)).expect("mkdir session-auth");
    }

    #[tokio::test]
    async fn login_resolution_prefers_session_token_over_login_files() {
        let token = Token::new();
        let validator = MockValidator::default().with_live(token, agent_principal());
        let home = tempdir().expect("tempdir");
        seed_session_auth_dir(home.path());
        write(
            global_login_path(home.path()),
            r#"{"email":"global@example.com"}"#,
        )
        .expect("write global");
        let env = HashMap::from([(SESSION_TOKEN_ENV.to_string(), token.to_string())]);

        let principal = resolve_from_env_with_login(
            |key| env.get(key).cloned(),
            home.path(),
            Some("/dev/ttys003"),
            &validator,
        )
        .await
        .expect("token wins");

        assert!(matches!(principal, Principal::AgentSession { .. }));
    }

    #[tokio::test]
    async fn login_resolution_uses_per_tty_file_when_present() {
        let validator = MockValidator::default();
        let home = tempdir().expect("tempdir");
        seed_session_auth_dir(home.path());
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

        let principal =
            resolve_from_env_with_login(|_| None, home.path(), Some("/dev/ttys003"), &validator)
                .await
                .expect("per-tty wins");

        assert!(matches!(
            principal,
            Principal::Human { email, role: Role::Member } if email == "per-tty@example.com"
        ));
    }

    #[tokio::test]
    async fn login_resolution_falls_back_to_global_then_owner_env() {
        let validator = MockValidator::default();
        let home = tempdir().expect("tempdir");
        seed_session_auth_dir(home.path());
        write(
            global_login_path(home.path()),
            r#"{"email":"global@example.com"}"#,
        )
        .expect("write global");

        let principal =
            resolve_from_env_with_login(|_| None, home.path(), Some("/dev/ttys003"), &validator)
                .await
                .expect("global wins after per-tty miss");

        assert!(matches!(
            principal,
            Principal::Human { email, role: Role::Member } if email == "global@example.com"
        ));
    }

    #[tokio::test]
    async fn login_resolution_falls_back_to_owner_email_when_no_login_files() {
        let validator = MockValidator::default();
        let home = tempdir().expect("tempdir");
        seed_session_auth_dir(home.path());
        let env = HashMap::from([(OWNER_EMAIL_ENV.to_string(), "owner@example.com".to_string())]);

        let principal = resolve_from_env_with_login(
            |key| env.get(key).cloned(),
            home.path(),
            Some("/dev/ttys003"),
            &validator,
        )
        .await
        .expect("env fallback");

        assert!(matches!(
            principal,
            Principal::Human { email, role: Role::Owner } if email == "owner@example.com"
        ));
    }

    #[tokio::test]
    async fn login_resolution_returns_auth_missing_when_no_evidence() {
        let validator = MockValidator::default();
        let home = tempdir().expect("tempdir");
        seed_session_auth_dir(home.path());

        let err =
            resolve_from_env_with_login(|_| None, home.path(), Some("/dev/ttys003"), &validator)
                .await
                .expect_err("expected AuthMissing");

        assert!(matches!(err, IdentityError::AuthMissing));
    }

    #[tokio::test]
    async fn login_resolution_surfaces_invalid_token_for_garbage_env_value() {
        let validator = MockValidator::default();
        let home = tempdir().expect("tempdir");
        seed_session_auth_dir(home.path());
        let env = HashMap::from([(SESSION_TOKEN_ENV.to_string(), "garbage".to_string())]);

        let err =
            resolve_from_env_with_login(|key| env.get(key).cloned(), home.path(), None, &validator)
                .await
                .expect_err("expected InvalidToken");

        assert!(matches!(err, IdentityError::InvalidToken));
    }

    #[tokio::test]
    async fn login_resolution_surfaces_malformed_login_file() {
        let validator = MockValidator::default();
        let home = tempdir().expect("tempdir");
        seed_session_auth_dir(home.path());
        write(global_login_path(home.path()), "this is not an email").expect("write malformed");

        let err = resolve_from_env_with_login(|_| None, home.path(), None, &validator)
            .await
            .expect_err("expected AuthMalformed");

        assert!(matches!(err, IdentityError::AuthMalformed(_)));
    }

    #[tokio::test]
    async fn http_resolution_surfaces_invalid_token() {
        let validator = MockValidator::default();
        let headers = HashMap::from([(HEADER_SESSION_TOKEN.to_string(), "garbage".to_string())]);

        let err = resolve_from_http_with(|name| headers.get(name).cloned(), &validator)
            .await
            .expect_err("expected InvalidToken");

        assert!(matches!(err, IdentityError::InvalidToken));
    }
}

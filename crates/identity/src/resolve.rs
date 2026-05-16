//! Environment-based principal resolution.
//!
//! Single-user MVP: if `TELECLAUDE_OWNER_EMAIL` is set and non-empty, the
//! caller is the workspace owner. The CLI is responsible for loading any
//! `.env` file before invoking these helpers; this module performs a pure
//! env lookup so it stays trivially testable via dependency injection.

use crate::errors::IdentityError;
use crate::models::{Principal, Role};

/// Environment variable that carries the workspace owner's email.
pub const OWNER_EMAIL_ENV: &str = "TELECLAUDE_OWNER_EMAIL";

/// Resolve the current principal from the process environment.
///
/// Returns [`IdentityError::OwnerEmailUnset`] when the owner email variable
/// is missing or empty.
pub fn resolve_from_env() -> Result<Principal, IdentityError> {
    resolve_with(|key| std::env::var(key).ok())
}

/// Resolve a principal using a caller-supplied env lookup.
///
/// Exposed primarily for testability: production callers should use
/// [`resolve_from_env`].
pub fn resolve_with<F>(env_lookup: F) -> Result<Principal, IdentityError>
where
    F: Fn(&str) -> Option<String>,
{
    let raw = env_lookup(OWNER_EMAIL_ENV).unwrap_or_default();
    let email = raw.trim();
    if email.is_empty() {
        return Err(IdentityError::OwnerEmailUnset);
    }
    Ok(Principal::Human {
        email: email.to_string(),
        role: Role::Owner,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn returns_unset_when_env_absent() {
        let result = resolve_with(|_| None);

        assert!(matches!(result, Err(IdentityError::OwnerEmailUnset)));
    }

    #[test]
    fn returns_unset_when_env_blank() {
        let result = resolve_with(|_| Some("   ".to_string()));

        assert!(matches!(result, Err(IdentityError::OwnerEmailUnset)));
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

    #[test]
    fn looks_up_owner_email_env_var() {
        let requested = std::cell::Cell::new(false);
        let _ = resolve_with(|key| {
            if key == OWNER_EMAIL_ENV {
                requested.set(true);
            }
            None
        });

        assert!(requested.get());
    }
}

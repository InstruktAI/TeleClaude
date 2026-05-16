//! Error type for the identity crate.

/// Errors returned by identity-resolution helpers.
#[derive(thiserror::Error, Debug)]
pub enum IdentityError {
    /// The `TELECLAUDE_OWNER_EMAIL` environment variable was missing or empty.
    #[error("TELECLAUDE_OWNER_EMAIL is unset or empty")]
    OwnerEmailUnset,
}

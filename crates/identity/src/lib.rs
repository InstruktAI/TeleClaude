//! identity — single-user MVP stub.
//!
//! Resolves the current [`Principal`] from the environment. The full
//! identity service (HTTP resolution, session tokens, storage) is deferred
//! to a later wave; this MVP exposes only the types and helpers the CLI and
//! services need today.

pub mod errors;
pub mod models;
pub mod resolve;

pub use errors::IdentityError;
pub use models::{Principal, Role};
pub use resolve::{resolve_from_env, resolve_with, OWNER_EMAIL_ENV};

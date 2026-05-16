//! shared — primitive types reused across v2 crates.
//!
//! The public surface is intentionally tiny: domain identifiers and time
//! helpers used by every service crate.

pub mod ids;
pub mod time;

pub use ids::{slug_from_string, ProjectId, SessionId, Slug, SlugError, TodoId};
pub use time::{now, Timestamp};

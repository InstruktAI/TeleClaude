//! Time primitives used across v2 services.
//!
//! All timestamps in v2 are UTC. Local-time conversions are presentation
//! concerns and belong to UI layers, never to domain models.

use chrono::{DateTime, Utc};

/// The canonical timestamp type used by v2 service crates.
pub type Timestamp = DateTime<Utc>;

/// Current wall-clock time in UTC.
pub fn now() -> Timestamp {
    Utc::now()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn now_is_non_decreasing_across_consecutive_calls() {
        let first = now();
        let second = now();
        assert!(second >= first);
    }
}

//! Newtype identifiers for v2 services.
//!
//! Each domain identifier is a distinct type so the compiler rejects passing
//! a `ProjectId` where a `TodoId` is required. `Slug` carries the only
//! validation the type needs: non-empty, not whitespace-only.

use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Error returned when constructing a [`Slug`] from an invalid string.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum SlugError {
    #[error("slug must not be empty")]
    Empty,
    #[error("slug must not be whitespace-only")]
    Whitespace,
}

/// A human-readable identifier used across the v2 workflow surface.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Slug(pub String);

impl Slug {
    /// Construct a [`Slug`] from a string slice, rejecting empty and
    /// whitespace-only input.
    pub fn new(value: &str) -> Result<Self, SlugError> {
        slug_from_string(value)
    }

    /// Borrow the underlying string.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for Slug {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl FromStr for Slug {
    type Err = SlugError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        slug_from_string(s)
    }
}

/// Validate and construct a [`Slug`].
///
/// Rejects empty strings and whitespace-only input. Any other character
/// content is preserved verbatim — broader slug normalization belongs in
/// higher-level workflow code, not in the primitive type.
pub fn slug_from_string(value: &str) -> Result<Slug, SlugError> {
    if value.is_empty() {
        return Err(SlugError::Empty);
    }
    if value.chars().all(char::is_whitespace) {
        return Err(SlugError::Whitespace);
    }
    Ok(Slug(value.to_owned()))
}

/// Identifier for a todo aggregate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, sqlx::Type)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct TodoId(pub Uuid);

impl TodoId {
    /// Generate a fresh random [`TodoId`] (UUID v4).
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

impl Default for TodoId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for TodoId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl FromStr for TodoId {
    type Err = uuid::Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Uuid::parse_str(s).map(Self)
    }
}

/// Identifier for a project aggregate.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, sqlx::Type)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct ProjectId(pub Uuid);

impl ProjectId {
    /// Generate a fresh random [`ProjectId`] (UUID v4).
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

impl Default for ProjectId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for ProjectId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl FromStr for ProjectId {
    type Err = uuid::Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Uuid::parse_str(s).map(Self)
    }
}

/// Identifier for an agent session.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, sqlx::Type)]
#[serde(transparent)]
#[sqlx(transparent)]
pub struct SessionId(pub Uuid);

impl SessionId {
    /// Generate a fresh random [`SessionId`] (UUID v4).
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }
}

impl Default for SessionId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for SessionId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}

impl FromStr for SessionId {
    type Err = uuid::Error;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Uuid::parse_str(s).map(Self)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_from_string_accepts_simple_identifier() {
        let slug = slug_from_string("v2-mvp-bootstrap").expect("simple slug parses");
        assert_eq!(slug.as_str(), "v2-mvp-bootstrap");
    }

    #[test]
    fn slug_from_string_rejects_empty_input() {
        let result = slug_from_string("");
        assert_eq!(result, Err(SlugError::Empty));
    }

    #[test]
    fn slug_from_string_rejects_whitespace_only_input() {
        let result = slug_from_string("   \t\n");
        assert_eq!(result, Err(SlugError::Whitespace));
    }

    #[test]
    fn slug_serde_round_trip_preserves_value() {
        let slug = Slug("round-trip".to_owned());
        let encoded = serde_json::to_string(&slug).expect("serialize slug");
        let decoded: Slug = serde_json::from_str(&encoded).expect("deserialize slug");
        assert_eq!(decoded, slug);
    }

    #[test]
    fn slug_from_str_matches_constructor() {
        let parsed: Slug = "from-str-path".parse().expect("parses via FromStr");
        assert_eq!(
            parsed,
            Slug::new("from-str-path").expect("ctor accepts value")
        );
    }

    #[test]
    fn todo_id_display_and_from_str_round_trip() {
        let id = TodoId::new();
        let parsed: TodoId = id.to_string().parse().expect("uuid round-trip parses");
        assert_eq!(parsed, id);
    }

    #[test]
    fn todo_id_serde_round_trip_is_transparent() {
        let id = TodoId::new();
        let encoded = serde_json::to_string(&id).expect("serialize todo id");
        let inner_encoded = serde_json::to_string(&id.0).expect("serialize inner uuid");
        assert_eq!(encoded, inner_encoded);
    }

    #[test]
    fn project_id_serde_round_trip_recovers_value() {
        let id = ProjectId::new();
        let encoded = serde_json::to_string(&id).expect("serialize project id");
        let decoded: ProjectId = serde_json::from_str(&encoded).expect("deserialize project id");
        assert_eq!(decoded, id);
    }

    #[test]
    fn session_id_serde_round_trip_recovers_value() {
        let id = SessionId::new();
        let encoded = serde_json::to_string(&id).expect("serialize session id");
        let decoded: SessionId = serde_json::from_str(&encoded).expect("deserialize session id");
        assert_eq!(decoded, id);
    }

    #[test]
    fn session_id_from_str_rejects_invalid_input() {
        let result: Result<SessionId, _> = "not-a-uuid".parse();
        assert!(result.is_err());
    }
}

//! Workflow event channel constants and typed payload schemas.
//!
//! Channels follow the v2 naming convention `{service}.{aggregate}.{verb_past}`
//! (see `docs/project/design/architecture-v2/event-bus-transports.md`). Each
//! channel constant pairs with exactly one payload struct in this module.
//! Payloads serialize to/from JSON via `serde` for the Redis Streams envelope.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use shared::{ProjectId, Slug, TodoId};

use crate::models::{ArtifactName, LifecyclePhase};

/// Channel for [`TodoCreated`] events.
pub const CHANNEL_TODO_CREATED: &str = "workflow.todo.created";
/// Channel for [`TodoUpdated`] events.
pub const CHANNEL_TODO_UPDATED: &str = "workflow.todo.updated";
/// Channel for [`TodoDeleted`] events.
pub const CHANNEL_TODO_DELETED: &str = "workflow.todo.deleted";
/// Channel for [`TodoPhaseAdvanced`] events.
pub const CHANNEL_TODO_PHASE_ADVANCED: &str = "workflow.todo.phase_advanced";
/// Channel for [`RoadmapEntryAdded`] events.
pub const CHANNEL_ROADMAP_ENTRY_ADDED: &str = "workflow.roadmap.entry_added";
/// Channel for [`RoadmapEntryMoved`] events.
pub const CHANNEL_ROADMAP_ENTRY_MOVED: &str = "workflow.roadmap.entry_moved";
/// Channel for [`RoadmapEntryRemoved`] events.
pub const CHANNEL_ROADMAP_ENTRY_REMOVED: &str = "workflow.roadmap.entry_removed";
/// Channel for [`ArtifactWritten`] events.
pub const CHANNEL_ARTIFACT_WRITTEN: &str = "workflow.artifact.written";
/// Channel for [`ArtifactDeleted`] events.
pub const CHANNEL_ARTIFACT_DELETED: &str = "workflow.artifact.deleted";

/// Emitted when a new todo aggregate is created.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TodoCreated {
    pub todo_id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub lifecycle_phase: LifecyclePhase,
    pub created_at: DateTime<Utc>,
}

/// Emitted when a todo aggregate's mutable fields change.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TodoUpdated {
    pub todo_id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub updated_at: DateTime<Utc>,
}

/// Emitted when a todo aggregate is removed.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TodoDeleted {
    pub todo_id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub deleted_at: DateTime<Utc>,
}

/// Emitted when a todo transitions between lifecycle phases.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TodoPhaseAdvanced {
    pub todo_id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub from_phase: LifecyclePhase,
    pub to_phase: LifecyclePhase,
    pub signal: Option<String>,
    pub occurred_at: DateTime<Utc>,
}

/// Emitted when a slug is added to a project's roadmap.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RoadmapEntryAdded {
    pub project_id: ProjectId,
    pub slug: Slug,
    pub position: i32,
    pub added_at: DateTime<Utc>,
}

/// Emitted when a roadmap entry is reordered within a project.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RoadmapEntryMoved {
    pub project_id: ProjectId,
    pub slug: Slug,
    pub from_position: i32,
    pub to_position: i32,
    pub moved_at: DateTime<Utc>,
}

/// Emitted when a slug is removed from a project's roadmap.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RoadmapEntryRemoved {
    pub project_id: ProjectId,
    pub slug: Slug,
    pub removed_at: DateTime<Utc>,
}

/// Emitted when an artifact version is written for a todo.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactWritten {
    pub todo_id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub name: ArtifactName,
    pub digest: String,
    pub written_at: DateTime<Utc>,
}

/// Emitted when an artifact and its version history are removed.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactDeleted {
    pub todo_id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub name: ArtifactName,
    pub deleted_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn fixed_timestamp() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 5, 16, 12, 0, 0).unwrap()
    }

    fn sample_slug() -> Slug {
        Slug::new("sample-todo").expect("constant slug parses")
    }

    fn sample_todo_id() -> TodoId {
        TodoId::new()
    }

    fn sample_project_id() -> ProjectId {
        ProjectId::new()
    }

    #[test]
    fn channel_todo_created_matches_literal() {
        assert_eq!(CHANNEL_TODO_CREATED, "workflow.todo.created");
    }

    #[test]
    fn channel_todo_updated_matches_literal() {
        assert_eq!(CHANNEL_TODO_UPDATED, "workflow.todo.updated");
    }

    #[test]
    fn channel_todo_deleted_matches_literal() {
        assert_eq!(CHANNEL_TODO_DELETED, "workflow.todo.deleted");
    }

    #[test]
    fn channel_todo_phase_advanced_matches_literal() {
        assert_eq!(CHANNEL_TODO_PHASE_ADVANCED, "workflow.todo.phase_advanced");
    }

    #[test]
    fn channel_roadmap_entry_added_matches_literal() {
        assert_eq!(CHANNEL_ROADMAP_ENTRY_ADDED, "workflow.roadmap.entry_added");
    }

    #[test]
    fn channel_roadmap_entry_moved_matches_literal() {
        assert_eq!(CHANNEL_ROADMAP_ENTRY_MOVED, "workflow.roadmap.entry_moved");
    }

    #[test]
    fn channel_roadmap_entry_removed_matches_literal() {
        assert_eq!(
            CHANNEL_ROADMAP_ENTRY_REMOVED,
            "workflow.roadmap.entry_removed"
        );
    }

    #[test]
    fn channel_artifact_written_matches_literal() {
        assert_eq!(CHANNEL_ARTIFACT_WRITTEN, "workflow.artifact.written");
    }

    #[test]
    fn channel_artifact_deleted_matches_literal() {
        assert_eq!(CHANNEL_ARTIFACT_DELETED, "workflow.artifact.deleted");
    }

    #[test]
    fn todo_created_round_trips_through_json() {
        let value = TodoCreated {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            lifecycle_phase: LifecyclePhase::Draft,
            created_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize TodoCreated");
        let decoded: TodoCreated = serde_json::from_str(&encoded).expect("deserialize TodoCreated");
        assert_eq!(decoded, value);
    }

    #[test]
    fn todo_updated_round_trips_through_json() {
        let value = TodoUpdated {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            updated_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize TodoUpdated");
        let decoded: TodoUpdated = serde_json::from_str(&encoded).expect("deserialize TodoUpdated");
        assert_eq!(decoded, value);
    }

    #[test]
    fn todo_deleted_round_trips_through_json() {
        let value = TodoDeleted {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            deleted_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize TodoDeleted");
        let decoded: TodoDeleted = serde_json::from_str(&encoded).expect("deserialize TodoDeleted");
        assert_eq!(decoded, value);
    }

    #[test]
    fn todo_phase_advanced_round_trips_through_json() {
        let value = TodoPhaseAdvanced {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            from_phase: LifecyclePhase::PrdDrafting,
            to_phase: LifecyclePhase::PrdHumanApproval,
            signal: Some("PRD_APPROVED".to_owned()),
            occurred_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize TodoPhaseAdvanced");
        let decoded: TodoPhaseAdvanced =
            serde_json::from_str(&encoded).expect("deserialize TodoPhaseAdvanced");
        assert_eq!(decoded, value);
    }

    #[test]
    fn roadmap_entry_added_round_trips_through_json() {
        let value = RoadmapEntryAdded {
            project_id: sample_project_id(),
            slug: sample_slug(),
            position: 3,
            added_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize RoadmapEntryAdded");
        let decoded: RoadmapEntryAdded =
            serde_json::from_str(&encoded).expect("deserialize RoadmapEntryAdded");
        assert_eq!(decoded, value);
    }

    #[test]
    fn roadmap_entry_moved_round_trips_through_json() {
        let value = RoadmapEntryMoved {
            project_id: sample_project_id(),
            slug: sample_slug(),
            from_position: 1,
            to_position: 4,
            moved_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize RoadmapEntryMoved");
        let decoded: RoadmapEntryMoved =
            serde_json::from_str(&encoded).expect("deserialize RoadmapEntryMoved");
        assert_eq!(decoded, value);
    }

    #[test]
    fn roadmap_entry_removed_round_trips_through_json() {
        let value = RoadmapEntryRemoved {
            project_id: sample_project_id(),
            slug: sample_slug(),
            removed_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize RoadmapEntryRemoved");
        let decoded: RoadmapEntryRemoved =
            serde_json::from_str(&encoded).expect("deserialize RoadmapEntryRemoved");
        assert_eq!(decoded, value);
    }

    #[test]
    fn artifact_written_round_trips_through_json() {
        let value = ArtifactWritten {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            name: ArtifactName::Prd,
            digest: "sha256:deadbeef".to_owned(),
            written_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize ArtifactWritten");
        let decoded: ArtifactWritten =
            serde_json::from_str(&encoded).expect("deserialize ArtifactWritten");
        assert_eq!(decoded, value);
    }

    #[test]
    fn artifact_deleted_round_trips_through_json() {
        let value = ArtifactDeleted {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            name: ArtifactName::TestSpecs,
            deleted_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize ArtifactDeleted");
        let decoded: ArtifactDeleted =
            serde_json::from_str(&encoded).expect("deserialize ArtifactDeleted");
        assert_eq!(decoded, value);
    }
}

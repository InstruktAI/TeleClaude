//! Workflow event channel constants and typed payload schemas.
//!
//! Channels follow the v2 naming convention `{service}.{aggregate}.{verb_past}`
//! (see `docs/project/design/architecture-v2/event-bus-transports.md`). Each
//! channel constant pairs with exactly one payload struct in this module.
//! Payloads serialize to/from JSON via `serde` for the Redis Streams envelope.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use shared::{ProjectId, Slug, TodoId};

use crate::models::{ArtifactName, CreationMode, LifecyclePhase, TodoKind};

/// Channel for [`TodoCreated`] events.
pub const CHANNEL_TODO_CREATED: &str = "workflow.todo.created";
/// Channel for [`TodoUpdated`] events.
pub const CHANNEL_TODO_UPDATED: &str = "workflow.todo.updated";
/// Channel for [`TodoRenamed`] events.
pub const CHANNEL_TODO_RENAMED: &str = "workflow.todo.renamed";
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
    pub kind: TodoKind,
    #[serde(default)]
    pub creation_mode: CreationMode,
    #[serde(default = "crate::models::default_pickup_requested")]
    pub pickup_requested: bool,
    #[serde(default)]
    pub created_by_principal: String,
    #[serde(default)]
    pub project_path: String,
}

/// Emitted when a todo aggregate's mutable fields change.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TodoUpdated {
    pub todo_id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub updated_at: DateTime<Utc>,
    #[serde(default)]
    pub change_summary: String,
    #[serde(default)]
    pub updated_by_principal: String,
    #[serde(default)]
    pub project_path: String,
}

/// Emitted when a todo aggregate is renamed.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TodoRenamed {
    pub todo_id: TodoId,
    pub old_slug: Slug,
    pub new_slug: Slug,
    pub project_id: ProjectId,
    pub project_path: String,
    pub renamed_at: DateTime<Utc>,
    pub renamed_by_principal: String,
    pub rewritten_reference_count: u64,
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
    use serde::Serialize;

    use crate::models::{CreationMode, TodoKind};

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

    #[derive(Serialize)]
    struct LegacyTodoCreated {
        todo_id: TodoId,
        slug: Slug,
        project_id: ProjectId,
        lifecycle_phase: LifecyclePhase,
        created_at: DateTime<Utc>,
        kind: TodoKind,
    }

    #[derive(Serialize)]
    struct LegacyTodoUpdated {
        todo_id: TodoId,
        slug: Slug,
        project_id: ProjectId,
        updated_at: DateTime<Utc>,
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
    fn channel_todo_renamed_matches_literal() {
        assert_eq!(CHANNEL_TODO_RENAMED, "workflow.todo.renamed");
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
            kind: TodoKind::Feature,
            creation_mode: CreationMode::Pickup,
            pickup_requested: true,
            created_by_principal: "owner@example.com".to_owned(),
            project_path: "/tmp/test-project".to_owned(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize TodoCreated");
        let decoded: TodoCreated = serde_json::from_str(&encoded).expect("deserialize TodoCreated");
        assert_eq!(decoded, value);
    }

    #[test]
    fn old_shape_todo_created_decodes_with_creation_defaults() {
        let legacy = LegacyTodoCreated {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            lifecycle_phase: LifecyclePhase::PrdDrafting,
            created_at: fixed_timestamp(),
            kind: TodoKind::Bug,
        };
        let encoded = serde_json::to_string(&legacy).expect("serialize legacy TodoCreated");

        let decoded: TodoCreated = serde_json::from_str(&encoded).expect("deserialize TodoCreated");

        assert_eq!(decoded.todo_id, legacy.todo_id);
        assert_eq!(decoded.slug, legacy.slug);
        assert_eq!(decoded.project_id, legacy.project_id);
        assert_eq!(decoded.lifecycle_phase, legacy.lifecycle_phase);
        assert_eq!(decoded.created_at, legacy.created_at);
        assert_eq!(decoded.kind, TodoKind::Bug);
        assert_eq!(decoded.creation_mode, CreationMode::Pickup);
        assert!(decoded.pickup_requested);
        assert!(decoded.created_by_principal.is_empty());
        assert!(decoded.project_path.is_empty());
    }

    #[test]
    fn todo_created_missing_kind_is_rejected() {
        // kind is mandatory: an event without it must fail to deserialize (no silent default).
        let json = serde_json::json!({
            "todo_id": sample_todo_id(),
            "slug": sample_slug(),
            "project_id": sample_project_id(),
            "lifecycle_phase": LifecyclePhase::Draft,
            "created_at": fixed_timestamp(),
        });
        let result: Result<TodoCreated, _> = serde_json::from_value(json);
        assert!(
            result.is_err(),
            "missing kind must be rejected, not defaulted"
        );
    }

    #[test]
    fn silent_todo_created_round_trips_through_json() {
        let value = TodoCreated {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            lifecycle_phase: LifecyclePhase::PrdDrafting,
            created_at: fixed_timestamp(),
            kind: TodoKind::Bug,
            creation_mode: CreationMode::Silent,
            pickup_requested: false,
            created_by_principal: "owner@example.com".to_owned(),
            project_path: "/tmp/test-project".to_owned(),
        };

        let encoded = serde_json::to_string(&value).expect("serialize TodoCreated");
        let decoded: TodoCreated = serde_json::from_str(&encoded).expect("deserialize TodoCreated");

        assert_eq!(decoded, value);
        assert_eq!(decoded.creation_mode, CreationMode::Silent);
        assert!(!decoded.pickup_requested);
    }

    #[test]
    fn todo_updated_round_trips_through_json() {
        let value = TodoUpdated {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            updated_at: fixed_timestamp(),
            change_summary: "description changed".to_owned(),
            updated_by_principal: "owner@example.com".to_owned(),
            project_path: "/tmp/test-project".to_owned(),
        };
        let encoded = serde_json::to_string(&value).expect("serialize TodoUpdated");
        let decoded: TodoUpdated = serde_json::from_str(&encoded).expect("deserialize TodoUpdated");
        assert_eq!(decoded, value);
    }

    #[test]
    fn old_shape_todo_updated_decodes_with_defaults() {
        let legacy = LegacyTodoUpdated {
            todo_id: sample_todo_id(),
            slug: sample_slug(),
            project_id: sample_project_id(),
            updated_at: fixed_timestamp(),
        };
        let encoded = serde_json::to_string(&legacy).expect("serialize legacy TodoUpdated");

        let decoded: TodoUpdated = serde_json::from_str(&encoded).expect("deserialize TodoUpdated");

        assert_eq!(decoded.todo_id, legacy.todo_id);
        assert_eq!(decoded.slug, legacy.slug);
        assert_eq!(decoded.project_id, legacy.project_id);
        assert_eq!(decoded.updated_at, legacy.updated_at);
        assert!(decoded.change_summary.is_empty());
        assert!(decoded.updated_by_principal.is_empty());
        assert!(decoded.project_path.is_empty());
    }

    #[test]
    fn todo_renamed_round_trips_through_json() {
        let value = TodoRenamed {
            todo_id: sample_todo_id(),
            old_slug: sample_slug(),
            new_slug: Slug::new("sample-renamed").expect("constant slug parses"),
            project_id: sample_project_id(),
            project_path: "/tmp/test-project".to_owned(),
            renamed_at: fixed_timestamp(),
            renamed_by_principal: "owner@example.com".to_owned(),
            rewritten_reference_count: 2,
        };

        let encoded = serde_json::to_string(&value).expect("serialize TodoRenamed");
        let decoded: TodoRenamed = serde_json::from_str(&encoded).expect("deserialize TodoRenamed");

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

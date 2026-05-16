//! Workflow domain models — todos, roadmap entries, artifacts, and the
//! lifecycle/kind/artifact-name enums that drive them.
//!
//! These types mirror the v1 Python lifecycle in `teleclaude/types/lifecycle.py`
//! exactly: same phase names, same prepare/work stage membership. Serde uses
//! `snake_case` for lifecycle/kind enums and `kebab-case` for artifact names
//! so the wire format matches the CLI's `telec todo artifacts <name>` literal
//! values verbatim. `sqlx::Type` derives bind these enums to the matching
//! Postgres enum types defined by D1's migrations.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use shared::{ProjectId, Slug, TodoId};
use uuid::Uuid;

/// Authoritative lifecycle phase for a workflow todo.
///
/// Variants and ordering mirror v1's `LifecyclePhase`. The `stage()` helper
/// maps each variant to the prepare/work bucket used by the orchestrator.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, sqlx::Type)]
#[serde(rename_all = "snake_case")]
#[sqlx(type_name = "workflow.lifecycle_phase", rename_all = "snake_case")]
pub enum LifecyclePhase {
    Draft,
    PrdDrafting,
    PrdHumanApproval,
    ArchitectureDrafting,
    ArchitectureReview,
    ArchitectureHumanApproval,
    TestSpecsDrafting,
    TestSpecsReview,
    TestSpecsHumanApproval,
    PlanDrafting,
    PlanReview,
    PlanHumanApproval,
    Prepared,
    Blocked,
    BuildStarted,
    BuildComplete,
    ReviewChangesRequested,
    ReviewApproved,
    FinalizeReady,
    HandedOff,
}

/// Coarse-grained stage bucket used by the prepare/work orchestrators.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LifecycleStage {
    Prepare,
    Work,
}

/// Discriminator for how a todo was scoped.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[serde(rename_all = "snake_case")]
#[sqlx(type_name = "workflow.todo_kind", rename_all = "snake_case")]
pub enum TodoKind {
    Feature,
    Bug,
    Refactor,
    Migration,
    Prepped,
}

/// Canonical artifact name. Serde and sqlx both emit kebab-case literals
/// so the wire/db values match the CLI's `<name>` argument (e.g.
/// `test-specs`, `requirements-review-findings`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[serde(rename_all = "kebab-case")]
#[sqlx(type_name = "workflow.artifact_name", rename_all = "kebab-case")]
pub enum ArtifactName {
    Input,
    Prd,
    Requirements,
    Architecture,
    TestSpecs,
    ImplementationPlan,
    Bug,
    QualityChecklist,
    DesignSpec,
    Deferrals,
    RequirementsReviewFindings,
    ArchitectureReviewFindings,
    SpecReviewFindings,
    PlanReviewFindings,
    ReviewFindings,
}

impl LifecyclePhase {
    /// Map a phase to its coarse-grained stage. Prepare covers every phase
    /// up to and including `Prepared` plus `Blocked`; Work covers everything
    /// from `BuildStarted` through `HandedOff`.
    pub fn stage(self) -> LifecycleStage {
        match self {
            Self::Draft
            | Self::PrdDrafting
            | Self::PrdHumanApproval
            | Self::ArchitectureDrafting
            | Self::ArchitectureReview
            | Self::ArchitectureHumanApproval
            | Self::TestSpecsDrafting
            | Self::TestSpecsReview
            | Self::TestSpecsHumanApproval
            | Self::PlanDrafting
            | Self::PlanReview
            | Self::PlanHumanApproval
            | Self::Prepared
            | Self::Blocked => LifecycleStage::Prepare,
            Self::BuildStarted
            | Self::BuildComplete
            | Self::ReviewChangesRequested
            | Self::ReviewApproved
            | Self::FinalizeReady
            | Self::HandedOff => LifecycleStage::Work,
        }
    }

    /// `true` only for `HandedOff` — the lifecycle's single terminal state.
    pub fn is_terminal(self) -> bool {
        matches!(self, Self::HandedOff)
    }
}

/// A workflow todo aggregate.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Todo {
    pub id: TodoId,
    pub slug: Slug,
    pub project_id: ProjectId,
    pub kind: TodoKind,
    pub lifecycle_phase: LifecyclePhase,
    pub group: Option<String>,
    pub after: Vec<Slug>,
    pub description: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub delivered_at: Option<DateTime<Utc>>,
}

/// A roadmap entry — the ordered, project-scoped view of todos.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoadmapEntry {
    pub id: Uuid,
    pub project_id: ProjectId,
    pub slug: Slug,
    pub group: Option<String>,
    pub position: i32,
    pub frozen: bool,
    pub after: Vec<Slug>,
    pub description: Option<String>,
    pub delivered_at: Option<DateTime<Utc>>,
    pub commit_hash: Option<String>,
}

/// A versioned artifact attached to a todo (PRD, plan, findings, etc.).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Artifact {
    pub id: Uuid,
    pub todo_id: TodoId,
    pub name: ArtifactName,
    pub digest: String,
    pub content: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lifecycle_phase_serde_round_trip_prepare_variant() {
        let encoded = serde_json::to_string(&LifecyclePhase::PrdDrafting).expect("serialize");
        assert_eq!(encoded, "\"prd_drafting\"");
    }

    #[test]
    fn lifecycle_phase_serde_round_trip_work_variant() {
        let decoded: LifecyclePhase =
            serde_json::from_str("\"build_started\"").expect("deserialize");
        assert_eq!(decoded, LifecyclePhase::BuildStarted);
    }

    #[test]
    fn lifecycle_phase_serde_round_trip_terminal_variant() {
        let encoded = serde_json::to_string(&LifecyclePhase::HandedOff).expect("serialize");
        let decoded: LifecyclePhase = serde_json::from_str(&encoded).expect("deserialize");
        assert_eq!(decoded, LifecyclePhase::HandedOff);
    }

    #[test]
    fn lifecycle_stage_serde_encodes_prepare_as_snake_case() {
        let encoded = serde_json::to_string(&LifecycleStage::Prepare).expect("serialize");
        assert_eq!(encoded, "\"prepare\"");
    }

    #[test]
    fn lifecycle_stage_serde_decodes_work_from_snake_case() {
        let decoded: LifecycleStage = serde_json::from_str("\"work\"").expect("deserialize");
        assert_eq!(decoded, LifecycleStage::Work);
    }

    #[test]
    fn todo_kind_serde_round_trip_feature() {
        let encoded = serde_json::to_string(&TodoKind::Feature).expect("serialize");
        assert_eq!(encoded, "\"feature\"");
    }

    #[test]
    fn artifact_name_serde_encodes_single_word_as_lowercase() {
        let encoded = serde_json::to_string(&ArtifactName::Prd).expect("serialize");
        assert_eq!(encoded, "\"prd\"");
    }

    #[test]
    fn artifact_name_serde_encodes_two_words_as_kebab_case() {
        let encoded = serde_json::to_string(&ArtifactName::TestSpecs).expect("serialize");
        assert_eq!(encoded, "\"test-specs\"");
    }

    #[test]
    fn artifact_name_serde_decodes_longest_kebab_case_value() {
        let decoded: ArtifactName =
            serde_json::from_str("\"requirements-review-findings\"").expect("deserialize");
        assert_eq!(decoded, ArtifactName::RequirementsReviewFindings);
    }

    #[test]
    fn lifecycle_phase_stage_maps_prepare_side_to_prepare() {
        assert_eq!(
            LifecyclePhase::PlanDrafting.stage(),
            LifecycleStage::Prepare
        );
    }

    #[test]
    fn lifecycle_phase_stage_maps_work_side_to_work() {
        assert_eq!(LifecyclePhase::ReviewApproved.stage(), LifecycleStage::Work);
    }

    #[test]
    fn lifecycle_phase_is_terminal_true_for_handed_off() {
        assert!(LifecyclePhase::HandedOff.is_terminal());
    }

    #[test]
    fn lifecycle_phase_is_terminal_false_for_non_terminal() {
        assert!(!LifecyclePhase::FinalizeReady.is_terminal());
    }
}

//! Lifecycle phase transitions.
//!
//! [`WorkflowService::advance_phase`] delegates legality to the pure
//! [`next_lifecycle_phase`] state machine, then atomically writes the new
//! phase, appends a row to `workflow.state_transitions`, and emits
//! [`crate::events::TodoPhaseAdvanced`]. Illegal signals surface as
//! [`WorkflowError::InvalidTransition`] without touching the row.

use chrono::Utc;
use identity::Principal;
use shared::{ProjectId, Slug};

use crate::errors::WorkflowError;
use crate::events::{TodoPhaseAdvanced, CHANNEL_TODO_PHASE_ADVANCED};
use crate::models::Todo;
use crate::service::artifacts::resolve_todo;
use crate::service::WorkflowService;
use crate::state_machine::{next_lifecycle_phase, LifecycleSignal};

impl WorkflowService {
    /// Advance a todo's lifecycle phase via an authoritative signal.
    ///
    /// Reads the current phase, asks the state machine for the next phase,
    /// writes both the phase update and the audit row to
    /// `workflow.state_transitions` in one transaction, then emits the
    /// phase-advanced event.
    pub async fn advance_phase(
        &self,
        project: ProjectId,
        slug: &Slug,
        signal: LifecycleSignal,
        principal: &Principal,
    ) -> Result<Todo, WorkflowError> {
        let (todo_pk, _todo_uuid) = resolve_todo(self, project, slug).await?;

        let mut tx = self.pool().begin().await?;

        let current_phase: crate::models::LifecyclePhase =
            sqlx::query_scalar("select lifecycle_phase from workflow.todos where id = $1")
                .bind(todo_pk)
                .fetch_one(&mut *tx)
                .await?;

        let next_phase = next_lifecycle_phase(current_phase, signal).map_err(|err| {
            WorkflowError::InvalidTransition {
                from: err.current,
                to: current_phase, // state machine has no concrete target on failure
            }
        })?;

        sqlx::query(
            "update workflow.todos
             set lifecycle_phase = $1, updated_at = now()
             where id = $2",
        )
        .bind(next_phase)
        .bind(todo_pk)
        .execute(&mut *tx)
        .await?;

        let signal_label = signal_label(signal);
        sqlx::query(
            "insert into workflow.state_transitions
                (todo_id, from_phase, to_phase, signal, principal)
             values ($1, $2, $3, $4, $5::jsonb)",
        )
        .bind(todo_pk)
        .bind(current_phase)
        .bind(next_phase)
        .bind(&signal_label)
        .bind(serde_json::to_value(principal)?)
        .execute(&mut *tx)
        .await?;

        tx.commit().await?;

        let todo = self.get_todo(project, slug).await?;

        self.publish(
            CHANNEL_TODO_PHASE_ADVANCED,
            &TodoPhaseAdvanced {
                todo_id: todo.id,
                slug: todo.slug.clone(),
                project_id: todo.project_id,
                from_phase: current_phase,
                to_phase: next_phase,
                signal: Some(signal_label),
                occurred_at: Utc::now(),
            },
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;

        Ok(todo)
    }
}

/// Render a [`LifecycleSignal`] as its serde snake_case label for storage
/// and for the event payload. Falls back to debug form (impossible in
/// practice — serde never fails on a Copy enum without strings).
fn signal_label(signal: LifecycleSignal) -> String {
    serde_json::to_value(signal)
        .ok()
        .and_then(|v| v.as_str().map(str::to_owned))
        .unwrap_or_else(|| format!("{signal:?}"))
}

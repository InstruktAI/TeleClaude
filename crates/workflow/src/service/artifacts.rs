//! Artifact operations.
//!
//! Mirrors `telec todo artifacts {list, read, write, remove}` and the v1
//! storage in `teleclaude/core/todos_db/_artifacts.py`. Two tables back
//! every artifact:
//!
//! * `workflow.artifacts` — the **current** content per `(todo, name)`.
//! * `workflow.artifact_versions` — an **append-only** history. Every write
//!   inserts here, even no-op rewrites, so `telec todo artifacts diff` can
//!   resolve any two snapshots by digest.
//!
//! Digests are SHA-256 over the artifact content, lower-case hex.

use chrono::{DateTime, Utc};
use identity::Principal;
use sha2::{Digest, Sha256};
use shared::{ProjectId, Slug, TodoId};
use sqlx::Row;
use uuid::Uuid;

use crate::errors::WorkflowError;
use crate::events::{
    ArtifactDeleted, ArtifactWritten, CHANNEL_ARTIFACT_DELETED, CHANNEL_ARTIFACT_WRITTEN,
};
use crate::models::{Artifact, ArtifactName};
use crate::service::WorkflowService;

impl WorkflowService {
    /// List the artifact names currently attached to a todo, in insertion
    /// order. Empty `Vec` if none.
    pub async fn list_artifacts(
        &self,
        project: ProjectId,
        slug: &Slug,
    ) -> Result<Vec<Artifact>, WorkflowError> {
        let (todo_pk, todo_uuid) = resolve_todo(self, project, slug).await?;

        let rows = sqlx::query(
            "select id, name, content, digest, created_at, updated_at
             from workflow.artifacts
             where todo_id = $1
             order by created_at asc",
        )
        .bind(todo_pk)
        .fetch_all(self.pool())
        .await?;

        rows.into_iter()
            .map(|row| row_to_artifact(row, todo_uuid))
            .collect()
    }

    /// Read the current content of one artifact.
    ///
    /// Returns [`WorkflowError::ArtifactNotFound`] when the named artifact
    /// has never been written for this todo.
    pub async fn read_artifact(
        &self,
        project: ProjectId,
        slug: &Slug,
        name: ArtifactName,
    ) -> Result<Artifact, WorkflowError> {
        let (todo_pk, todo_uuid) = resolve_todo(self, project, slug).await?;

        let maybe = sqlx::query(
            "select id, name, content, digest, created_at, updated_at
             from workflow.artifacts
             where todo_id = $1 and name = $2",
        )
        .bind(todo_pk)
        .bind(name)
        .fetch_optional(self.pool())
        .await?;

        match maybe {
            Some(row) => row_to_artifact(row, todo_uuid),
            None => Err(WorkflowError::ArtifactNotFound {
                todo: slug.clone(),
                name,
            }),
        }
    }

    /// Write artifact content.
    ///
    /// Upserts the current row in `workflow.artifacts` and **always** appends
    /// a new row to `workflow.artifact_versions` — even when the content is
    /// identical to the previous version — so the history is a complete
    /// audit trail. Emits `workflow.artifact.written`.
    pub async fn write_artifact(
        &self,
        project: ProjectId,
        slug: &Slug,
        name: ArtifactName,
        content: String,
        principal: &Principal,
    ) -> Result<Artifact, WorkflowError> {
        let (todo_pk, todo_uuid) = resolve_todo(self, project, slug).await?;
        let digest = sha256_hex(&content);
        let updated_by = updated_by(principal);

        let mut tx = self.pool().begin().await?;

        // Append-only history first.
        sqlx::query(
            "insert into workflow.artifact_versions
                (todo_id, name, content, digest, updated_by)
             values ($1, $2, $3, $4, $5)",
        )
        .bind(todo_pk)
        .bind(name)
        .bind(&content)
        .bind(&digest)
        .bind(updated_by.as_deref())
        .execute(&mut *tx)
        .await?;

        // Upsert current row.
        let row = sqlx::query(
            "insert into workflow.artifacts
                (todo_id, name, content, digest, updated_by)
             values ($1, $2, $3, $4, $5)
             on conflict (todo_id, name) do update
               set content = excluded.content,
                   digest = excluded.digest,
                   updated_by = excluded.updated_by,
                   updated_at = now()
             returning id, name, content, digest, created_at, updated_at",
        )
        .bind(todo_pk)
        .bind(name)
        .bind(&content)
        .bind(&digest)
        .bind(updated_by.as_deref())
        .fetch_one(&mut *tx)
        .await?;

        let artifact = row_to_artifact(row, todo_uuid)?;
        tx.commit().await?;

        self.publish(
            CHANNEL_ARTIFACT_WRITTEN,
            &ArtifactWritten {
                todo_id: todo_uuid,
                slug: slug.clone(),
                project_id: project,
                name,
                digest: artifact.digest.clone(),
                written_at: artifact.updated_at,
            },
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;

        Ok(artifact)
    }

    /// Remove an artifact and **all** of its versions.
    ///
    /// Returns [`WorkflowError::ArtifactNotFound`] when no current row
    /// exists. Emits `workflow.artifact.deleted`.
    pub async fn remove_artifact(
        &self,
        project: ProjectId,
        slug: &Slug,
        name: ArtifactName,
        principal: &Principal,
    ) -> Result<(), WorkflowError> {
        let (todo_pk, todo_uuid) = resolve_todo(self, project, slug).await?;

        let mut tx = self.pool().begin().await?;

        let result = sqlx::query("delete from workflow.artifacts where todo_id = $1 and name = $2")
            .bind(todo_pk)
            .bind(name)
            .execute(&mut *tx)
            .await?;
        if result.rows_affected() == 0 {
            return Err(WorkflowError::ArtifactNotFound {
                todo: slug.clone(),
                name,
            });
        }

        sqlx::query("delete from workflow.artifact_versions where todo_id = $1 and name = $2")
            .bind(todo_pk)
            .bind(name)
            .execute(&mut *tx)
            .await?;

        tx.commit().await?;

        self.publish(
            CHANNEL_ARTIFACT_DELETED,
            &ArtifactDeleted {
                todo_id: todo_uuid,
                slug: slug.clone(),
                project_id: project,
                name,
                deleted_at: Utc::now(),
            },
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;

        Ok(())
    }
}

/// Resolve a `(project, slug)` to the bigserial `id` and public `uuid_id`
/// of the underlying todo, or [`WorkflowError::TodoNotFound`] if missing.
pub(crate) async fn resolve_todo(
    svc: &WorkflowService,
    project: ProjectId,
    slug: &Slug,
) -> Result<(i64, TodoId), WorkflowError> {
    let row = sqlx::query(
        "select id, uuid_id from workflow.todos
         where project_id = $1 and slug = $2",
    )
    .bind(project)
    .bind(slug.as_str())
    .fetch_optional(svc.pool())
    .await?;
    match row {
        Some(r) => Ok((
            r.try_get::<i64, _>("id")?,
            TodoId(r.try_get::<Uuid, _>("uuid_id")?),
        )),
        None => Err(WorkflowError::TodoNotFound(slug.clone())),
    }
}

fn row_to_artifact(row: sqlx::postgres::PgRow, todo_id: TodoId) -> Result<Artifact, WorkflowError> {
    // `workflow.artifacts.id` is `bigserial`; the public `Artifact.id` field
    // is `Uuid` in the v2 model. Generate a stable per-row UUID from the
    // bigserial via `Uuid::from_u128` so identical reads yield identical UUIDs.
    let pk: i64 = row.try_get("id")?;
    Ok(Artifact {
        id: Uuid::from_u128(pk as u128),
        todo_id,
        name: row.try_get("name")?,
        digest: row.try_get::<String, _>("digest")?,
        content: row.try_get::<String, _>("content")?,
        created_at: row.try_get::<DateTime<Utc>, _>("created_at")?,
        updated_at: row.try_get::<DateTime<Utc>, _>("updated_at")?,
    })
}

pub(crate) fn sha256_hex(content: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content.as_bytes());
    format!("{:x}", hasher.finalize())
}

pub(crate) fn updated_by(principal: &Principal) -> Option<String> {
    match principal {
        Principal::Human { email, .. } => Some(email.clone()),
        Principal::AgentSession { session_id, .. } => Some(format!("agent:{session_id}")),
        Principal::System { service } => Some(format!("system:{service}")),
        // `Principal::Anonymous` is `#[non_exhaustive]` outside the identity
        // crate so the catch-all is the only legal way to handle it here.
        _ => None,
    }
}

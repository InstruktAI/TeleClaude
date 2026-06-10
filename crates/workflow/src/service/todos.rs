//! Todo CRUD.
//!
//! Mirrors the v1 `telec todo` surface (create, dump, remove, show) and the
//! storage operations in `teleclaude/core/todos_db/_state.py`. The schema
//! holds two IDs per row: an opaque `bigserial id` used for foreign-key
//! edges inside the schema and a public `uuid_id` exposed to callers via
//! the [`TodoId`] newtype. CRUD never returns the bigserial id.
//!
//! ## Create
//!
//! A todo always carries a 1:1 [`RoadmapEntry`] **and** an
//! [`ArtifactName::Input`] artifact. `create_todo` opens a transaction,
//! inserts the roadmap entry at the tail of the project's roadmap, inserts
//! kinded todos at `lifecycle_phase = 'prd_drafting'` and kind-less todos at
//! `lifecycle_phase = 'draft'` (v2 kind-less -> Draft pending
//! v2-workflow-cutover reconciliation; v1 is authoritative), persists the required input artifact
//! (current row + append-only history), commits, then emits
//! [`crate::events::TodoCreated`] followed by
//! [`crate::events::ArtifactWritten`]. v2 deliberately refuses
//! empty-input creation — the reviewer-flagged RV2 regression is closed by
//! requiring the caller to supply `input_content`.
//!
//! ## Duplicate slugs
//!
//! Slugs are unique per `(project_id, slug)`; the underlying constraint
//! violation surfaces as [`WorkflowError::DuplicateSlug`] (matched on the
//! Postgres SQLSTATE `23505`).

use chrono::{DateTime, Utc};
use identity::Principal;
use shared::{ProjectId, Slug, TodoId};
use sqlx::types::Json;
use sqlx::Row;

use crate::errors::WorkflowError;
use crate::events::{
    ArtifactWritten, TodoCreated, TodoDeleted, TodoUpdated, CHANNEL_ARTIFACT_WRITTEN,
    CHANNEL_TODO_CREATED, CHANNEL_TODO_DELETED, CHANNEL_TODO_UPDATED,
};
use crate::models::{ArtifactName, CreationMode, LifecyclePhase, Todo, TodoKind};
use crate::service::artifacts::{sha256_hex, updated_by};
use crate::service::WorkflowService;

/// Arguments for creating a todo aggregate and its required input artifact.
#[derive(Debug, Clone)]
pub struct CreateTodoArgs {
    pub project: ProjectId,
    pub slug: Slug,
    pub kind: Option<TodoKind>,
    pub description: Option<String>,
    pub after: Vec<Slug>,
    pub group: Option<String>,
    pub input_content: String,
    pub creation_mode: CreationMode,
}

/// Patch applied by [`WorkflowService::update_todo`].
///
/// Field semantics use the double-`Option` pattern: `None` means "leave the
/// column alone"; `Some(None)` means "set the column to `NULL`"; `Some(Some(value))`
/// means "set the column to `value`".
#[derive(Debug, Clone, Default)]
pub struct TodoPatch {
    /// Free-form description.
    pub description: Option<Option<String>>,
    /// Dependency slugs (replaces the existing array verbatim).
    pub after: Option<Vec<Slug>>,
    /// Group label.
    pub group: Option<Option<String>>,
}

impl WorkflowService {
    /// List every todo in the project.
    ///
    /// Order: roadmap position ascending. Returns an empty `Vec` when the
    /// project has no todos.
    pub async fn list_todos(&self, project: ProjectId) -> Result<Vec<Todo>, WorkflowError> {
        let rows = sqlx::query(
            "select t.uuid_id, t.slug, t.project_id, t.kind, t.lifecycle_phase,
                    t.group_slug, t.after, t.description, t.created_at, t.updated_at,
                    t.delivered_at
             from workflow.todos t
             join workflow.roadmap_entries r on r.id = t.roadmap_entry_id
             where t.project_id = $1
             order by r.position asc, t.created_at asc",
        )
        .bind(project)
        .fetch_all(self.pool())
        .await?;

        rows.into_iter().map(row_to_todo).collect()
    }

    /// Fetch a single todo by `(project, slug)`.
    ///
    /// Returns [`WorkflowError::TodoNotFound`] if no row matches.
    pub async fn get_todo(&self, project: ProjectId, slug: &Slug) -> Result<Todo, WorkflowError> {
        let maybe_row = sqlx::query(
            "select uuid_id, slug, project_id, kind, lifecycle_phase, group_slug,
                    after, description, created_at, updated_at, delivered_at
             from workflow.todos
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .fetch_optional(self.pool())
        .await?;

        match maybe_row {
            Some(row) => row_to_todo(row),
            None => Err(WorkflowError::TodoNotFound(slug.clone())),
        }
    }

    /// Create a new todo plus its 1:1 roadmap entry.
    ///
    /// Atomic: roadmap entry, todo, and dependency edges are inserted in one
    /// transaction. The roadmap entry is appended to the tail of the project
    /// (no `--before`); use [`WorkflowService::add_roadmap_entry`] for
    /// finer ordering control. Emits `workflow.todo.created`.
    pub async fn create_todo(
        &self,
        args: CreateTodoArgs,
        principal: &Principal,
    ) -> Result<Todo, WorkflowError> {
        let CreateTodoArgs {
            project,
            slug,
            kind,
            description,
            after,
            group,
            input_content,
            creation_mode,
        } = args;

        // v2 deviation from v1 (reviewer RV2): a todo cannot exist without
        // an input artifact. The contract is enforced here so every transport
        // — CLI, future HTTP — converges on the same invariant.
        if input_content.is_empty() {
            return Err(WorkflowError::EmptyInputArtifact);
        }

        let lifecycle_phase = if kind.is_some() {
            LifecyclePhase::PrdDrafting
        } else {
            LifecyclePhase::Draft
        };
        let after_strings: Vec<String> = after.iter().map(|s| s.as_str().to_owned()).collect();
        let input_digest = sha256_hex(&input_content);
        let updated_by_value = updated_by(principal);

        let mut tx = self.pool().begin().await?;

        let next_position: i32 = sqlx::query_scalar(
            "select coalesce(max(position), 0) + 1 from workflow.roadmap_entries
             where project_id = $1",
        )
        .bind(project)
        .fetch_one(&mut *tx)
        .await?;

        let roadmap_id: i64 = sqlx::query_scalar(
            "insert into workflow.roadmap_entries
                (project_id, slug, position, group_slug, description, after)
             values ($1, $2, $3, $4, $5, $6::jsonb)
             returning id",
        )
        .bind(project)
        .bind(slug.as_str())
        .bind(next_position)
        .bind(group.as_deref())
        .bind(description.as_deref())
        .bind(serde_json::to_value(&after_strings)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(|err| classify_unique_violation(err, &slug))?;

        let row = sqlx::query(
            "insert into workflow.todos
                (project_id, roadmap_entry_id, slug, kind, lifecycle_phase, group_slug,
                 description, after)
             values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
             returning uuid_id, slug, project_id, kind, lifecycle_phase, group_slug,
                       after, description, created_at, updated_at, delivered_at",
        )
        .bind(project)
        .bind(roadmap_id)
        .bind(slug.as_str())
        .bind(kind)
        .bind(lifecycle_phase)
        .bind(group.as_deref())
        .bind(description.as_deref())
        .bind(serde_json::to_value(&after_strings)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(|err| classify_unique_violation(err, &slug))?;

        insert_roadmap_deps(&mut tx, project, &slug, &after).await?;

        let todo = row_to_todo(row)?;
        let todo_pk = todo_pk_from_uuid(&mut tx, todo.id).await?;

        // Append-only artifact history first.
        sqlx::query(
            "insert into workflow.artifact_versions
                (todo_id, name, content, digest, updated_by)
             values ($1, $2, $3, $4, $5)",
        )
        .bind(todo_pk)
        .bind(ArtifactName::Input)
        .bind(&input_content)
        .bind(&input_digest)
        .bind(updated_by_value.as_deref())
        .execute(&mut *tx)
        .await?;

        // Then the current row.
        let artifact_row = sqlx::query(
            "insert into workflow.artifacts
                (todo_id, name, content, digest, updated_by)
             values ($1, $2, $3, $4, $5)
             returning updated_at",
        )
        .bind(todo_pk)
        .bind(ArtifactName::Input)
        .bind(&input_content)
        .bind(&input_digest)
        .bind(updated_by_value.as_deref())
        .fetch_one(&mut *tx)
        .await?;
        let artifact_updated_at: DateTime<Utc> = artifact_row.try_get("updated_at")?;
        let project_path: String =
            sqlx::query_scalar("select root_path from workflow.projects where id = $1")
                .bind(project)
                .fetch_one(&mut *tx)
                .await?;

        tx.commit().await?;

        self.publish(
            CHANNEL_TODO_CREATED,
            &TodoCreated {
                todo_id: todo.id,
                slug: todo.slug.clone(),
                project_id: todo.project_id,
                lifecycle_phase: todo.lifecycle_phase,
                created_at: todo.created_at,
                kind: todo.kind,
                creation_mode,
                pickup_requested: matches!(creation_mode, CreationMode::Pickup),
                created_by_principal: updated_by_value.clone().unwrap_or_default(),
                project_path,
            },
            principal,
        )
        .await?;

        self.publish(
            CHANNEL_ARTIFACT_WRITTEN,
            &ArtifactWritten {
                todo_id: todo.id,
                slug: todo.slug.clone(),
                project_id: todo.project_id,
                name: ArtifactName::Input,
                digest: input_digest,
                written_at: artifact_updated_at,
            },
            principal,
        )
        .await?;

        Ok(todo)
    }

    /// Apply a patch to an existing todo and emit `workflow.todo.updated`.
    ///
    /// Only fields present in `patch` are touched (see [`TodoPatch`] for the
    /// "leave alone vs set NULL" semantics). Returns the fully-refreshed
    /// [`Todo`]. [`WorkflowError::TodoNotFound`] if the slug is unknown.
    pub async fn update_todo(
        &self,
        project: ProjectId,
        slug: &Slug,
        patch: TodoPatch,
        principal: &Principal,
    ) -> Result<Todo, WorkflowError> {
        let mut tx = self.pool().begin().await?;

        // Ensure the row exists before we issue conditional updates so the
        // not-found case is unambiguous regardless of patch shape.
        let exists: Option<i64> =
            sqlx::query_scalar("select id from workflow.todos where project_id = $1 and slug = $2")
                .bind(project)
                .bind(slug.as_str())
                .fetch_optional(&mut *tx)
                .await?;
        if exists.is_none() {
            return Err(WorkflowError::TodoNotFound(slug.clone()));
        }

        if let Some(description) = &patch.description {
            sqlx::query(
                "update workflow.todos
                 set description = $1, updated_at = now()
                 where project_id = $2 and slug = $3",
            )
            .bind(description.as_deref())
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;
        }

        if let Some(group) = &patch.group {
            sqlx::query(
                "update workflow.todos
                 set group_slug = $1, updated_at = now()
                 where project_id = $2 and slug = $3",
            )
            .bind(group.as_deref())
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;
        }

        if let Some(after) = &patch.after {
            let after_strings: Vec<String> = after.iter().map(|s| s.as_str().to_owned()).collect();
            sqlx::query(
                "update workflow.todos
                 set after = $1::jsonb, updated_at = now()
                 where project_id = $2 and slug = $3",
            )
            .bind(serde_json::to_value(&after_strings)?)
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;

            sqlx::query(
                "update workflow.roadmap_entries
                 set after = $1::jsonb, updated_at = now()
                 where project_id = $2 and slug = $3",
            )
            .bind(serde_json::to_value(&after_strings)?)
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;

            sqlx::query("delete from workflow.roadmap_deps where project_id = $1 and slug = $2")
                .bind(project)
                .bind(slug.as_str())
                .execute(&mut *tx)
                .await?;

            insert_roadmap_deps(&mut tx, project, slug, after).await?;
        }

        let row = sqlx::query(
            "select uuid_id, slug, project_id, kind, lifecycle_phase, group_slug,
                    after, description, created_at, updated_at, delivered_at
             from workflow.todos
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .fetch_one(&mut *tx)
        .await?;
        let todo = row_to_todo(row)?;

        tx.commit().await?;

        self.publish(
            CHANNEL_TODO_UPDATED,
            &TodoUpdated {
                todo_id: todo.id,
                slug: todo.slug.clone(),
                project_id: todo.project_id,
                updated_at: todo.updated_at,
                change_summary: String::new(),
                updated_by_principal: String::new(),
                project_path: String::new(),
            },
            principal,
        )
        .await?;

        Ok(todo)
    }

    /// Delete a todo (and its roadmap entry, artifacts, versions, and state
    /// transitions, via `on delete cascade`). Emits `workflow.todo.deleted`.
    pub async fn delete_todo(
        &self,
        project: ProjectId,
        slug: &Slug,
        principal: &Principal,
    ) -> Result<(), WorkflowError> {
        let mut tx = self.pool().begin().await?;

        let row = sqlx::query(
            "select uuid_id, roadmap_entry_id
             from workflow.todos
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .fetch_optional(&mut *tx)
        .await?;

        let (todo_id, roadmap_entry_id) = match row {
            Some(r) => (
                TodoId(r.try_get::<uuid::Uuid, _>("uuid_id")?),
                r.try_get::<i64, _>("roadmap_entry_id")?,
            ),
            None => return Err(WorkflowError::TodoNotFound(slug.clone())),
        };

        sqlx::query("delete from workflow.roadmap_entries where id = $1")
            .bind(roadmap_entry_id)
            .execute(&mut *tx)
            .await?;

        sqlx::query("delete from workflow.roadmap_deps where project_id = $1 and slug = $2")
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;

        tx.commit().await?;

        self.publish(
            CHANNEL_TODO_DELETED,
            &TodoDeleted {
                todo_id,
                slug: slug.clone(),
                project_id: project,
                deleted_at: Utc::now(),
            },
            principal,
        )
        .await?;

        Ok(())
    }
}

/// Translate a row from `workflow.todos` into the public [`Todo`] aggregate.
fn row_to_todo(row: sqlx::postgres::PgRow) -> Result<Todo, WorkflowError> {
    let after_json: Json<Vec<String>> = row.try_get("after")?;
    let after: Vec<Slug> = after_json
        .0
        .into_iter()
        .map(|s| Slug::new(&s))
        .collect::<Result<_, _>>()
        .map_err(|err| {
            WorkflowError::Db(sqlx::Error::Decode(Box::new(std::io::Error::new(
                std::io::ErrorKind::InvalidData,
                format!("after slug decode: {err}"),
            ))))
        })?;
    Ok(Todo {
        id: TodoId(row.try_get("uuid_id")?),
        slug: Slug(row.try_get::<String, _>("slug")?),
        project_id: row.try_get("project_id")?,
        kind: row.try_get("kind")?,
        lifecycle_phase: row.try_get("lifecycle_phase")?,
        group: row.try_get::<Option<String>, _>("group_slug")?,
        after,
        description: row.try_get::<Option<String>, _>("description")?,
        created_at: row.try_get::<DateTime<Utc>, _>("created_at")?,
        updated_at: row.try_get::<DateTime<Utc>, _>("updated_at")?,
        delivered_at: row.try_get::<Option<DateTime<Utc>>, _>("delivered_at")?,
    })
}

/// Resolve a public [`TodoId`] (UUID) to the internal BIGSERIAL primary key
/// inside an open transaction so subsequent inserts can use it without a
/// second roundtrip.
async fn todo_pk_from_uuid(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    todo_id: TodoId,
) -> Result<i64, WorkflowError> {
    let pk: i64 = sqlx::query_scalar("select id from workflow.todos where uuid_id = $1")
        .bind(todo_id.0)
        .fetch_one(&mut **tx)
        .await?;
    Ok(pk)
}

pub(super) async fn insert_roadmap_deps(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    project: ProjectId,
    slug: &Slug,
    after: &[Slug],
) -> Result<(), WorkflowError> {
    for dep in after {
        sqlx::query(
            "insert into workflow.roadmap_deps (project_id, slug, depends_on)
             values ($1, $2, $3)
             on conflict do nothing",
        )
        .bind(project)
        .bind(slug.as_str())
        .bind(dep.as_str())
        .execute(&mut **tx)
        .await?;
    }
    Ok(())
}

/// Map Postgres `23505 unique_violation` on a roadmap/todo slug insert to
/// [`WorkflowError::DuplicateSlug`]; pass everything else through unchanged.
fn classify_unique_violation(err: sqlx::Error, slug: &Slug) -> WorkflowError {
    if let sqlx::Error::Database(db_err) = &err {
        if db_err.code().as_deref() == Some("23505") {
            return WorkflowError::DuplicateSlug(slug.clone());
        }
    }
    WorkflowError::Db(err)
}

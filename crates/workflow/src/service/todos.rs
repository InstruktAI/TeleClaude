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
//! the todo at `lifecycle_phase = 'prd_drafting'`, persists the required
//! input artifact (current row + append-only history), commits, then emits
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

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use chrono::{DateTime, Utc};
use git2::BranchType;
use identity::Principal;
use rusqlite::OptionalExtension;
use shared::{ProjectId, Slug, TodoId};
use sqlx::types::Json;
use sqlx::Row;

use crate::errors::WorkflowError;
use crate::events::{
    ArtifactWritten, TodoCreated, TodoDeleted, TodoRenamed, TodoUpdated, CHANNEL_ARTIFACT_WRITTEN,
    CHANNEL_TODO_CREATED, CHANNEL_TODO_DELETED, CHANNEL_TODO_RENAMED, CHANNEL_TODO_UPDATED,
    TODO_UPDATE_CHANGE_AFTER, TODO_UPDATE_CHANGE_ARTIFACT, TODO_UPDATE_CHANGE_DESCRIPTION,
    TODO_UPDATE_CHANGE_GROUP, TODO_UPDATE_CHANGE_KIND,
};
use crate::models::{
    ArtifactName, CreationMode, LifecyclePhase, Todo, TodoDiff, TodoDiffSection, TodoKind,
};
use crate::service::artifacts::{
    artifact_name_label, artifact_version_content, sha256_hex, short_digest, unified_diff,
    updated_by,
};
use crate::service::WorkflowService;

const WORKTREE_DIR: &str = "trees";
const WORKSPACE_DIR: &str = "workspace";

/// Arguments for creating a todo aggregate and its required input artifact.
#[derive(Debug, Clone)]
pub struct CreateTodoArgs {
    pub project: ProjectId,
    pub slug: Slug,
    pub kind: TodoKind,
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

/// Typed mutation request for [`WorkflowService::update_todo`].
#[derive(Debug, Clone)]
pub struct UpdateTodoArgs {
    pub project: ProjectId,
    pub slug: Slug,
    pub group: Option<Option<String>>,
    pub description: Option<Option<String>>,
    pub kind: Option<TodoKind>,
    pub after: Option<Vec<Slug>>,
    pub content: Option<String>,
    pub artifact: Option<ArtifactName>,
    pub prepped: bool,
}

/// Summary returned by [`WorkflowService::rename_todo`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenameOutcome {
    pub todo_id: TodoId,
    pub old_slug: Slug,
    pub new_slug: Slug,
    pub rewritten_reference_count: u64,
}

impl Default for UpdateTodoArgs {
    fn default() -> Self {
        Self {
            project: ProjectId::default(),
            slug: Slug("todo".to_owned()),
            group: None,
            description: None,
            kind: None,
            after: None,
            content: None,
            artifact: None,
            prepped: false,
        }
    }
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
        // RV2: a brand-new todo with an input artifact starts at PrdDrafting,
        // never Draft. Draft remains an enum variant only for migrated v1
        // data; the state machine never produces it after migration.
        .bind(LifecyclePhase::PrdDrafting)
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

    /// Apply a typed update request to an existing todo and emit
    /// `workflow.todo.updated`.
    ///
    /// All fields are validated before mutation and all DB writes happen in
    /// one transaction, so a refused content write leaves metadata unchanged.
    pub async fn update_todo(
        &self,
        args: UpdateTodoArgs,
        principal: &Principal,
    ) -> Result<Todo, WorkflowError> {
        let UpdateTodoArgs {
            project,
            slug,
            group,
            description,
            kind,
            after,
            content,
            artifact,
            prepped,
        } = args;

        if prepped && artifact.is_some_and(|name| name != ArtifactName::ImplementationPlan) {
            return Err(WorkflowError::AmbiguousTodoUpdate);
        }
        if prepped && !matches!(principal, Principal::Human { .. }) {
            return Err(WorkflowError::PreppedUpdateRequiresHuman);
        }

        let artifact_write = match content {
            Some(content) => {
                if artifact.is_none() && is_patch_blob(&content) {
                    return Err(WorkflowError::PatchBlobRejected);
                }
                let name = if prepped {
                    ArtifactName::ImplementationPlan
                } else {
                    artifact.unwrap_or(ArtifactName::Input)
                };
                ensure_writable_artifact(name)?;
                Some((name, content))
            }
            None => None,
        };

        let mut tx = self.pool().begin().await?;

        // Ensure the row exists before we issue conditional updates so the
        // not-found case is unambiguous regardless of patch shape.
        let row = sqlx::query(
            "select id, uuid_id, lifecycle_phase
             from workflow.todos
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .fetch_optional(&mut *tx)
        .await?;
        let Some(row) = row else {
            return Err(WorkflowError::TodoNotFound(slug.clone()));
        };
        let todo_pk: i64 = row.try_get("id")?;
        let todo_id = TodoId(row.try_get("uuid_id")?);
        let current_phase: LifecyclePhase = row.try_get("lifecycle_phase")?;

        if let Some(next_kind) = kind {
            if !matches!(
                current_phase.stage(),
                crate::models::LifecycleStage::Prepare
            ) {
                return Err(WorkflowError::KindUpdatePhaseMismatch {
                    slug: slug.clone(),
                    phase: current_phase,
                    kind: next_kind,
                });
            }
        }

        let mut changed_fields: Vec<&'static str> = Vec::new();

        if let Some(description) = &description {
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
            changed_fields.push(TODO_UPDATE_CHANGE_DESCRIPTION);
        }

        if let Some(group) = &group {
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

            sqlx::query(
                "update workflow.roadmap_entries
                 set group_slug = $1, updated_at = now()
                 where project_id = $2 and slug = $3",
            )
            .bind(group.as_deref())
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;
            changed_fields.push(TODO_UPDATE_CHANGE_GROUP);
        }

        if let Some(next_kind) = kind {
            sqlx::query(
                "update workflow.todos
                 set kind = $1, updated_at = now()
                 where project_id = $2 and slug = $3",
            )
            .bind(next_kind)
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;
            changed_fields.push(TODO_UPDATE_CHANGE_KIND);
        }

        if let Some(after) = &after {
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

            insert_roadmap_deps(&mut tx, project, &slug, after).await?;
            changed_fields.push(TODO_UPDATE_CHANGE_AFTER);
        }

        if let Some((name, content)) = artifact_write {
            let digest = sha256_hex(&content);
            let updated_by_value = updated_by(principal);
            sqlx::query(
                "insert into workflow.artifact_versions
                    (todo_id, name, content, digest, updated_by)
                 values ($1, $2, $3, $4, $5)",
            )
            .bind(todo_pk)
            .bind(name)
            .bind(&content)
            .bind(&digest)
            .bind(updated_by_value.as_deref())
            .execute(&mut *tx)
            .await?;

            sqlx::query(
                "insert into workflow.artifacts
                    (todo_id, name, content, digest, updated_by)
                 values ($1, $2, $3, $4, $5)
                 on conflict (todo_id, name) do update
                   set content = excluded.content,
                       digest = excluded.digest,
                       updated_by = excluded.updated_by,
                       updated_at = now()",
            )
            .bind(todo_pk)
            .bind(name)
            .bind(&content)
            .bind(&digest)
            .bind(updated_by_value.as_deref())
            .execute(&mut *tx)
            .await?;
            changed_fields.push(TODO_UPDATE_CHANGE_ARTIFACT);
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
        let project_path: String =
            sqlx::query_scalar("select root_path from workflow.projects where id = $1")
                .bind(project)
                .fetch_one(&mut *tx)
                .await?;
        let updated_by_value = updated_by(principal).unwrap_or_default();
        let change_summary = changed_fields.join(",");

        tx.commit().await?;

        self.publish(
            CHANNEL_TODO_UPDATED,
            &TodoUpdated {
                todo_id,
                slug: todo.slug.clone(),
                project_id: todo.project_id,
                updated_at: todo.updated_at,
                change_summary,
                updated_by_principal: updated_by_value,
                project_path,
            },
            principal,
        )
        .await?;

        Ok(todo)
    }

    /// Compatibility wrapper for legacy surfaces that still carry
    /// [`TodoPatch`].
    pub async fn patch_todo(
        &self,
        project: ProjectId,
        slug: &Slug,
        patch: TodoPatch,
        principal: &Principal,
    ) -> Result<Todo, WorkflowError> {
        self.update_todo(
            UpdateTodoArgs {
                project,
                slug: slug.clone(),
                group: patch.group,
                description: patch.description,
                after: patch.after,
                ..UpdateTodoArgs::default()
            },
            principal,
        )
        .await
    }

    /// Atomically re-key a live todo slug across structured workflow tables
    /// and managed snippet `delivered_by` frontmatter.
    pub async fn rename_todo(
        &self,
        project: ProjectId,
        old_slug: &Slug,
        new_slug: Slug,
        principal: &Principal,
    ) -> Result<RenameOutcome, WorkflowError> {
        if old_slug == &new_slug {
            return Err(WorkflowError::TodoRenameNoop {
                slug: old_slug.clone(),
            });
        }

        let row = sqlx::query(
            "select t.id, t.uuid_id, r.status::text as status, p.root_path
             from workflow.todos t
             join workflow.roadmap_entries r on r.id = t.roadmap_entry_id
             join workflow.projects p on p.id = t.project_id
             where t.project_id = $1 and t.slug = $2",
        )
        .bind(project)
        .bind(old_slug.as_str())
        .fetch_optional(self.pool())
        .await?;
        let Some(row) = row else {
            return Err(WorkflowError::TodoNotFound(old_slug.clone()));
        };
        let todo_id = TodoId(row.try_get("uuid_id")?);
        let status: String = row.try_get("status")?;
        let project_path: String = row.try_get("root_path")?;
        if status == "delivered" {
            return Err(WorkflowError::TodoRenameDelivered {
                slug: old_slug.clone(),
            });
        }

        let collision: bool = sqlx::query_scalar(
            "select exists(
               select 1 from workflow.roadmap_entries
               where project_id = $1 and slug = $2
                 and status in ('active', 'icebox', 'delivered')
             )",
        )
        .bind(project)
        .bind(new_slug.as_str())
        .fetch_one(self.pool())
        .await?;
        if collision {
            return Err(WorkflowError::TodoRenameCollision {
                slug: new_slug.clone(),
            });
        }

        let project_root = Path::new(&project_path);
        ensure_no_nonterminal_daemon_refs(project_root, old_slug)?;

        let snippet_rewrites =
            plan_snippet_delivered_by_rewrites(project_root, old_slug, &new_slug)?;
        let surface_moves = move_todo_slug_surfaces(project_root, old_slug, &new_slug)?;

        if let Err(err) = apply_snippet_rewrite_plan(&snippet_rewrites) {
            rollback_todo_slug_surfaces(project_root, &surface_moves)?;
            return Err(err);
        }
        let db_result = self
            .rename_todo_in_transaction(project, old_slug, &new_slug)
            .await;
        if let Err(err) = db_result {
            restore_snippet_rewrite_plan(&snippet_rewrites)?;
            rollback_todo_slug_surfaces(project_root, &surface_moves)?;
            return Err(err);
        }

        reconcile_post_commit_slug_refs(project_root, old_slug, &new_slug);

        let renamed_at = Utc::now();
        let renamed_by_principal = updated_by(principal).unwrap_or_default();
        let rewritten_reference_count = snippet_rewrites.len() as u64;

        self.publish(
            CHANNEL_TODO_RENAMED,
            &TodoRenamed {
                todo_id,
                old_slug: old_slug.clone(),
                new_slug: new_slug.clone(),
                project_id: project,
                project_path,
                renamed_at,
                renamed_by_principal,
                rewritten_reference_count,
            },
            principal,
        )
        .await?;

        Ok(RenameOutcome {
            todo_id,
            old_slug: old_slug.clone(),
            new_slug,
            rewritten_reference_count,
        })
    }

    async fn rename_todo_in_transaction(
        &self,
        project: ProjectId,
        old_slug: &Slug,
        new_slug: &Slug,
    ) -> Result<(), WorkflowError> {
        let mut tx = self.pool().begin().await?;

        sqlx::query(
            "update workflow.todos
             set slug = $1, updated_at = now()
             where project_id = $2 and slug = $3",
        )
        .bind(new_slug.as_str())
        .bind(project)
        .bind(old_slug.as_str())
        .execute(&mut *tx)
        .await?;

        sqlx::query(
            "update workflow.roadmap_entries
             set slug = $1, updated_at = now()
             where project_id = $2 and slug = $3",
        )
        .bind(new_slug.as_str())
        .bind(project)
        .bind(old_slug.as_str())
        .execute(&mut *tx)
        .await?;

        rewrite_after_jsonb(&mut tx, "workflow.todos", project, old_slug, new_slug).await?;
        rewrite_after_jsonb(
            &mut tx,
            "workflow.roadmap_entries",
            project,
            old_slug,
            new_slug,
        )
        .await?;
        rewrite_roadmap_dependency_edges(&mut tx, project, old_slug, new_slug).await?;

        tx.commit().await?;
        Ok(())
    }

    /// Build the todo-scoped refinement diff across reviewed artifacts and
    /// snippets whose `delivered_by` frontmatter includes this slug.
    pub async fn todo_diff(
        &self,
        project: ProjectId,
        slug: &Slug,
    ) -> Result<TodoDiff, WorkflowError> {
        let row = sqlx::query(
            "select t.id, t.state_extra, p.root_path
             from workflow.todos t
             join workflow.projects p on p.id = t.project_id
             where t.project_id = $1 and t.slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .fetch_optional(self.pool())
        .await?;
        let Some(row) = row else {
            return Err(WorkflowError::TodoNotFound(slug.clone()));
        };

        let todo_pk: i64 = row.try_get("id")?;
        let state_extra: serde_json::Value = row.try_get("state_extra")?;
        let project_path: String = row.try_get("root_path")?;

        let mut sections = Vec::new();
        let mut diagnostics = Vec::new();
        self.append_artifact_diff_sections(
            todo_pk,
            slug,
            &state_extra,
            &mut sections,
            &mut diagnostics,
        )
        .await?;
        append_snippet_diff_sections(
            self.pool(),
            Path::new(&project_path),
            slug,
            &mut sections,
            &mut diagnostics,
        )
        .await?;

        Ok(TodoDiff {
            slug: slug.clone(),
            sections,
            diagnostics,
        })
    }

    async fn append_artifact_diff_sections(
        &self,
        todo_pk: i64,
        slug: &Slug,
        state_extra: &serde_json::Value,
        sections: &mut Vec<TodoDiffSection>,
        diagnostics: &mut Vec<String>,
    ) -> Result<(), WorkflowError> {
        let rows = sqlx::query(
            "select name, digest, content
             from workflow.artifacts
             where todo_id = $1
             order by name::text asc",
        )
        .bind(todo_pk)
        .fetch_all(self.pool())
        .await?;

        for row in rows {
            let name: ArtifactName = row.try_get("name")?;
            let Some(review_key) = review_key_for_artifact(name) else {
                continue;
            };
            let label = artifact_name_label(name);
            let current_digest: String = row.try_get("digest")?;
            let current_content: String = row.try_get("content")?;
            let Some(approved_digest) = approved_digest(state_extra, review_key) else {
                diagnostics.push(format!("baseline-absent: {label}"));
                continue;
            };
            if approved_digest == current_digest {
                continue;
            }
            let baseline_content =
                match artifact_version_content(self.pool(), todo_pk, slug, name, &approved_digest)
                    .await
                {
                    Ok(content) => content,
                    Err(WorkflowError::ArtifactVersionNotFound { .. }) => {
                        diagnostics.push(format!("baseline-absent: {label}"));
                        continue;
                    }
                    Err(err) => return Err(err),
                };
            sections.push(TodoDiffSection {
                label: label.to_owned(),
                baseline: approved_digest.clone(),
                current: current_digest.clone(),
                diff: unified_diff(
                    &format!("{label}@{}", short_digest(&approved_digest)),
                    &format!("{label}@{}", short_digest(&current_digest)),
                    &baseline_content,
                    &current_content,
                ),
                prefix: None,
            });
        }

        Ok(())
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

async fn rewrite_after_jsonb(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    table: &str,
    project: ProjectId,
    old_slug: &Slug,
    new_slug: &Slug,
) -> Result<(), WorkflowError> {
    let sql = match table {
        "workflow.todos" => {
            "select slug, after from workflow.todos
             where project_id = $1"
        }
        "workflow.roadmap_entries" => {
            "select slug, after from workflow.roadmap_entries
             where project_id = $1"
        }
        _ => unreachable!("workflow table name is hard-coded"),
    };
    let rows = sqlx::query(sql).bind(project).fetch_all(&mut **tx).await?;

    for row in rows {
        let slug = Slug(row.try_get::<String, _>("slug")?);
        let after_json: Json<Vec<String>> = row.try_get("after")?;
        let mut changed = false;
        let rewritten: Vec<String> = after_json
            .0
            .into_iter()
            .map(|dep| {
                if dep == old_slug.as_str() {
                    changed = true;
                    new_slug.as_str().to_owned()
                } else {
                    dep
                }
            })
            .collect();
        if !changed {
            continue;
        }

        let update_sql = match table {
            "workflow.todos" => {
                "update workflow.todos
                 set after = $1::jsonb, updated_at = now()
                 where project_id = $2 and slug = $3"
            }
            "workflow.roadmap_entries" => {
                "update workflow.roadmap_entries
                 set after = $1::jsonb, updated_at = now()
                 where project_id = $2 and slug = $3"
            }
            _ => unreachable!("workflow table name is hard-coded"),
        };
        sqlx::query(update_sql)
            .bind(serde_json::to_value(&rewritten)?)
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut **tx)
            .await?;
    }

    Ok(())
}

async fn rewrite_roadmap_dependency_edges(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    project: ProjectId,
    old_slug: &Slug,
    new_slug: &Slug,
) -> Result<(), WorkflowError> {
    let rows = sqlx::query(
        "select slug, depends_on
         from workflow.roadmap_deps
         where project_id = $1 and (slug = $2 or depends_on = $2)",
    )
    .bind(project)
    .bind(old_slug.as_str())
    .fetch_all(&mut **tx)
    .await?;

    sqlx::query("delete from workflow.roadmap_deps where project_id = $1 and (slug = $2 or depends_on = $2)")
        .bind(project)
        .bind(old_slug.as_str())
        .execute(&mut **tx)
        .await?;

    for row in rows {
        let slug: String = row.try_get("slug")?;
        let depends_on: String = row.try_get("depends_on")?;
        let next_slug = if slug == old_slug.as_str() {
            new_slug.as_str()
        } else {
            slug.as_str()
        };
        let next_depends_on = if depends_on == old_slug.as_str() {
            new_slug.as_str()
        } else {
            depends_on.as_str()
        };
        sqlx::query(
            "insert into workflow.roadmap_deps (project_id, slug, depends_on)
             values ($1, $2, $3)
             on conflict do nothing",
        )
        .bind(project)
        .bind(next_slug)
        .bind(next_depends_on)
        .execute(&mut **tx)
        .await?;
    }

    Ok(())
}

#[derive(Debug)]
struct SnippetRewritePlan {
    path: PathBuf,
    original: String,
    rewritten: String,
}

#[derive(Debug)]
enum TodoSlugSurfaceMove {
    Worktree {
        old_path: PathBuf,
        new_path: PathBuf,
        git_managed: bool,
    },
    LocalBranch {
        old_slug: String,
        new_slug: String,
    },
    Workspace {
        old_path: PathBuf,
        new_path: PathBuf,
    },
}

impl TodoSlugSurfaceMove {
    fn surface(&self) -> &'static str {
        match self {
            TodoSlugSurfaceMove::Worktree { .. } => "worktree",
            TodoSlugSurfaceMove::LocalBranch { .. } => "local_branch",
            TodoSlugSurfaceMove::Workspace { .. } => "workspace",
        }
    }
}

fn plan_snippet_delivered_by_rewrites(
    project_root: &Path,
    old_slug: &Slug,
    new_slug: &Slug,
) -> Result<Vec<SnippetRewritePlan>, WorkflowError> {
    let docs_root = project_root.join("docs");
    if !docs_root.exists() {
        return Ok(Vec::new());
    }

    let mut paths = Vec::new();
    collect_markdown_files(&docs_root, &mut paths)?;
    paths.sort();

    let mut plans = Vec::new();
    for path in paths {
        let content = fs::read_to_string(&path)?;
        let Some((frontmatter, body)) = split_frontmatter(&content) else {
            continue;
        };
        let (next_frontmatter, changed) =
            rewrite_delivered_by_frontmatter(frontmatter, old_slug, new_slug);
        if !changed {
            continue;
        }
        if contains_slug_token(body, old_slug) {
            return Err(WorkflowError::TodoRenameUnsafeReference {
                path: path.display().to_string(),
                slug: old_slug.clone(),
            });
        }
        let rewritten = format!("---\n{next_frontmatter}\n---\n{body}");
        plans.push(SnippetRewritePlan {
            path,
            original: content,
            rewritten,
        });
    }

    Ok(plans)
}

fn collect_markdown_files(dir: &Path, paths: &mut Vec<PathBuf>) -> Result<(), WorkflowError> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            collect_markdown_files(&path, paths)?;
        } else if path.extension().is_some_and(|ext| ext == "md") {
            paths.push(path);
        }
    }
    Ok(())
}

fn split_frontmatter(content: &str) -> Option<(&str, &str)> {
    let rest = content.strip_prefix("---\n")?;
    let boundary = rest.find("\n---\n")?;
    let frontmatter = &rest[..boundary];
    let body = &rest[boundary + "\n---\n".len()..];
    Some((frontmatter, body))
}

fn rewrite_delivered_by_frontmatter(
    frontmatter: &str,
    old_slug: &Slug,
    new_slug: &Slug,
) -> (String, bool) {
    let mut changed = false;
    let mut in_delivered_by = false;
    let mut delivered_by_already_has_new_slug =
        frontmatter_delivered_by_contains(frontmatter, new_slug);
    let mut lines = Vec::new();

    for line in frontmatter.lines() {
        let trimmed = line.trim_start();
        if in_delivered_by
            && !trimmed.is_empty()
            && !line.starts_with(' ')
            && !line.starts_with('-')
        {
            in_delivered_by = false;
        }

        let mut next_line = line.to_owned();
        if trimmed.starts_with("delivered_by:") {
            in_delivered_by = true;
            if let Some(rewritten) = rewrite_delivered_by_inline(line, old_slug, new_slug) {
                next_line = rewritten;
                changed = true;
            }
        }
        if in_delivered_by && !trimmed.starts_with("delivered_by:") {
            if delivered_by_list_item_matches(line, old_slug) && delivered_by_already_has_new_slug {
                changed = true;
                continue;
            }
            if let Some(rewritten) = rewrite_delivered_by_list_item(line, old_slug, new_slug) {
                next_line = rewritten;
                changed = true;
                delivered_by_already_has_new_slug = true;
            } else if delivered_by_list_item_matches(line, new_slug) {
                delivered_by_already_has_new_slug = true;
            }
        }
        lines.push(next_line);
    }

    (lines.join("\n"), changed)
}

fn rewrite_delivered_by_inline(line: &str, old_slug: &Slug, new_slug: &Slug) -> Option<String> {
    let (prefix, value) = line.split_once("delivered_by:")?;
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return None;
    }
    if let Some(inner) = trimmed.strip_prefix('[').and_then(|v| v.strip_suffix(']')) {
        if !inner
            .split(',')
            .any(|item| unquoted_yaml_scalar(item) == old_slug.as_str())
        {
            return None;
        }
        let mut changed = false;
        let mut new_slug_seen = false;
        let items = inner
            .split(',')
            .filter_map(|item| {
                let item = item.trim();
                let scalar = unquoted_yaml_scalar(item);
                let replacement = if scalar == old_slug.as_str() {
                    changed = true;
                    new_slug.as_str()
                } else {
                    scalar
                };
                if replacement == new_slug.as_str() {
                    if new_slug_seen {
                        changed = true;
                        return None;
                    }
                    new_slug_seen = true;
                }
                if scalar == old_slug.as_str() {
                    Some(new_slug.as_str().to_owned())
                } else {
                    Some(item.to_owned())
                }
            })
            .collect::<Vec<_>>();
        if changed {
            return Some(format!("{prefix}delivered_by: [{}]", items.join(", ")));
        }
        return None;
    }
    if unquoted_yaml_scalar(trimmed) == old_slug.as_str() {
        return Some(format!("{prefix}delivered_by: {}", new_slug.as_str()));
    }
    None
}

fn delivered_by_list_item_matches(line: &str, slug: &Slug) -> bool {
    let leading_len = line.len() - line.trim_start().len();
    let rest = &line[leading_len..];
    let Some(after_dash) = rest.strip_prefix('-') else {
        return false;
    };
    let whitespace_len = after_dash.len() - after_dash.trim_start().len();
    let value_start = leading_len + 1 + whitespace_len;
    let value = &line[value_start..];
    let token_len = yaml_scalar_token_len(value);
    token_len > 0 && unquoted_yaml_scalar(value[..token_len].trim()) == slug.as_str()
}

fn rewrite_delivered_by_list_item(line: &str, old_slug: &Slug, new_slug: &Slug) -> Option<String> {
    let leading_len = line.len() - line.trim_start().len();
    let leading = &line[..leading_len];
    let rest = &line[leading_len..];
    let after_dash = rest.strip_prefix('-')?;
    let whitespace_len = after_dash.len() - after_dash.trim_start().len();
    let value_start = leading_len + 1 + whitespace_len;
    let value = &line[value_start..];
    let token_len = yaml_scalar_token_len(value);
    if token_len == 0 {
        return None;
    }
    let token = &value[..token_len];
    if unquoted_yaml_scalar(token.trim()) == old_slug.as_str() {
        let suffix = &value[token_len..];
        return Some(format!("{leading}- {}{}", new_slug.as_str(), suffix));
    }
    None
}

fn yaml_scalar_token_len(value: &str) -> usize {
    let trimmed_len = value.len() - value.trim_start().len();
    let value = &value[trimmed_len..];
    if value.is_empty() {
        return 0;
    }
    let mut chars = value.char_indices();
    let Some((_, first)) = chars.next() else {
        return 0;
    };
    if first == '"' || first == '\'' {
        for (idx, ch) in chars {
            if ch == first {
                return trimmed_len + idx + ch.len_utf8();
            }
        }
        return value.len();
    }
    for (idx, ch) in value.char_indices() {
        if ch.is_whitespace() || matches!(ch, ',' | ']' | '#') {
            return trimmed_len + idx;
        }
    }
    trimmed_len + value.len()
}

fn unquoted_yaml_scalar(value: &str) -> &str {
    value.trim().trim_matches('"').trim_matches('\'')
}

fn contains_slug_token(text: &str, slug: &Slug) -> bool {
    let needle = slug.as_str();
    text.match_indices(needle).any(|(idx, _)| {
        let before_ok = idx == 0
            || text[..idx]
                .chars()
                .next_back()
                .is_none_or(|ch| !is_slug_char(ch));
        let after_idx = idx + needle.len();
        let after_ok = after_idx == text.len()
            || text[after_idx..]
                .chars()
                .next()
                .is_none_or(|ch| !is_slug_char(ch));
        before_ok && after_ok
    })
}

fn is_slug_char(ch: char) -> bool {
    ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_')
}

fn apply_snippet_rewrite_plan(plans: &[SnippetRewritePlan]) -> Result<(), WorkflowError> {
    let mut applied = Vec::new();
    for plan in plans {
        if let Err(err) = fs::write(&plan.path, &plan.rewritten) {
            let original_error = WorkflowError::Io(err);
            restore_snippet_rewrite_plan(&applied)?;
            return Err(original_error);
        }
        applied.push(SnippetRewritePlan {
            path: plan.path.clone(),
            original: plan.original.clone(),
            rewritten: plan.rewritten.clone(),
        });
    }
    Ok(())
}

fn restore_snippet_rewrite_plan(plans: &[SnippetRewritePlan]) -> Result<(), WorkflowError> {
    let mut first_error = None;
    for plan in plans.iter().rev() {
        if let Err(err) = fs::write(&plan.path, &plan.original) {
            tracing::warn!(
                path = %plan.path.display(),
                error = ?err,
                "snippet rewrite rollback failed"
            );
            if first_error.is_none() {
                first_error = Some(err);
            }
        }
    }
    if let Some(err) = first_error {
        Err(WorkflowError::Io(err))
    } else {
        Ok(())
    }
}

fn move_todo_slug_surfaces(
    project_root: &Path,
    old_slug: &Slug,
    new_slug: &Slug,
) -> Result<Vec<TodoSlugSurfaceMove>, WorkflowError> {
    let mut moves = Vec::new();
    let result = (|| -> Result<(), WorkflowError> {
        let old_worktree = project_root.join(WORKTREE_DIR).join(old_slug.as_str());
        let new_worktree = project_root.join(WORKTREE_DIR).join(new_slug.as_str());
        if path_exists(&old_worktree) {
            ensure_surface_destination_absent("worktree", &new_worktree)?;
            if project_has_git(project_root) {
                // git2 does not expose the porcelain-equivalent `git worktree move`;
                // the CLI keeps Git's administrative worktree metadata coherent.
                run_git_command(
                    project_root,
                    &[
                        "worktree".to_owned(),
                        "move".to_owned(),
                        old_worktree.to_string_lossy().into_owned(),
                        new_worktree.to_string_lossy().into_owned(),
                    ],
                )?;
                moves.push(TodoSlugSurfaceMove::Worktree {
                    old_path: old_worktree,
                    new_path: new_worktree,
                    git_managed: true,
                });
            } else {
                move_path("worktree", &old_worktree, &new_worktree)?;
                moves.push(TodoSlugSurfaceMove::Worktree {
                    old_path: old_worktree,
                    new_path: new_worktree,
                    git_managed: false,
                });
            }
        }

        if let Ok(repo) = git2::Repository::discover(project_root) {
            if let Ok(mut branch) = repo.find_branch(old_slug.as_str(), BranchType::Local) {
                if repo
                    .find_branch(new_slug.as_str(), BranchType::Local)
                    .is_ok()
                {
                    return Err(WorkflowError::TodoRenameSurfaceCollision {
                        surface: "local_branch".to_owned(),
                        target: new_slug.as_str().to_owned(),
                    });
                }
                branch.rename(new_slug.as_str(), false)?;
                moves.push(TodoSlugSurfaceMove::LocalBranch {
                    old_slug: old_slug.as_str().to_owned(),
                    new_slug: new_slug.as_str().to_owned(),
                });
            }
        }

        let old_workspace = project_root.join(WORKSPACE_DIR).join(old_slug.as_str());
        let new_workspace = project_root.join(WORKSPACE_DIR).join(new_slug.as_str());
        if path_exists(&old_workspace) {
            move_path("workspace", &old_workspace, &new_workspace)?;
            moves.push(TodoSlugSurfaceMove::Workspace {
                old_path: old_workspace,
                new_path: new_workspace,
            });
        }

        Ok(())
    })();

    if let Err(err) = result {
        let _ = rollback_todo_slug_surfaces(project_root, &moves);
        return Err(err);
    }

    Ok(moves)
}

fn rollback_todo_slug_surfaces(
    project_root: &Path,
    moves: &[TodoSlugSurfaceMove],
) -> Result<(), WorkflowError> {
    let mut first_error = None;
    for move_ in moves.iter().rev() {
        let result = match move_ {
            TodoSlugSurfaceMove::Workspace { old_path, new_path } => {
                rollback_path(old_path, new_path)
            }
            TodoSlugSurfaceMove::Worktree {
                old_path,
                new_path,
                git_managed,
            } => {
                if *git_managed {
                    run_git_command(
                        project_root,
                        &[
                            "worktree".to_owned(),
                            "move".to_owned(),
                            new_path.to_string_lossy().into_owned(),
                            old_path.to_string_lossy().into_owned(),
                        ],
                    )
                } else {
                    rollback_path(old_path, new_path)
                }
            }
            TodoSlugSurfaceMove::LocalBranch { old_slug, new_slug } => {
                rename_local_branch(project_root, new_slug, old_slug)
            }
        };
        if let Err(err) = result {
            tracing::warn!(
                surface = move_.surface(),
                error = ?err,
                "todo rename surface rollback failed"
            );
            if first_error.is_none() {
                first_error = Some(err);
            }
        }
    }
    if let Some(err) = first_error {
        Err(err)
    } else {
        Ok(())
    }
}

fn path_exists(path: &Path) -> bool {
    path.exists() || path.is_symlink()
}

fn project_has_git(project_root: &Path) -> bool {
    path_exists(&project_root.join(".git"))
}

fn ensure_surface_destination_absent(
    surface: &str,
    destination: &Path,
) -> Result<(), WorkflowError> {
    if path_exists(destination) {
        return Err(WorkflowError::TodoRenameSurfaceCollision {
            surface: surface.to_owned(),
            target: destination.display().to_string(),
        });
    }
    Ok(())
}

fn move_path(surface: &str, source: &Path, destination: &Path) -> Result<(), WorkflowError> {
    ensure_surface_destination_absent(surface, destination)?;
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::rename(source, destination)?;
    Ok(())
}

fn rollback_path(source: &Path, destination: &Path) -> Result<(), WorkflowError> {
    if path_exists(destination) && !path_exists(source) {
        if let Some(parent) = source.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::rename(destination, source)?;
    }
    Ok(())
}

fn rename_local_branch(
    project_root: &Path,
    old_slug: &str,
    new_slug: &str,
) -> Result<(), WorkflowError> {
    let repo = git2::Repository::discover(project_root)?;
    let mut branch = repo.find_branch(old_slug, BranchType::Local)?;
    branch.rename(new_slug, false)?;
    Ok(())
}

fn run_git_command(project_root: &Path, args: &[String]) -> Result<(), WorkflowError> {
    let output = Command::new("git")
        .arg("-C")
        .arg(project_root)
        .args(args)
        .output()?;
    if output.status.success() {
        return Ok(());
    }
    Err(WorkflowError::GitCommand {
        command: format!("git {}", args.join(" ")),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    })
}

fn delete_old_remote_slug_ref(project_root: &Path, old_slug: &Slug) -> Result<(), WorkflowError> {
    if !project_has_git(project_root) {
        return Ok(());
    }
    // git2's `Remote::push` requires building its own credential callbacks; the
    // git CLI here reuses the user's configured credential helpers and SSH agent
    // so post-commit remote cleanup stays best-effort and side-channel-free.
    let remote = Command::new("git")
        .arg("-C")
        .arg(project_root)
        .args(["remote", "get-url", "origin"])
        .output()?;
    if !remote.status.success() {
        return Ok(());
    }
    run_git_command(
        project_root,
        &[
            "push".to_owned(),
            "origin".to_owned(),
            "--delete".to_owned(),
            old_slug.as_str().to_owned(),
        ],
    )
}

fn ensure_no_nonterminal_daemon_refs(
    project_root: &Path,
    old_slug: &Slug,
) -> Result<(), WorkflowError> {
    let Some(conn) = open_daemon_db(project_root)? else {
        return Ok(());
    };
    let cwd = project_root.to_string_lossy();
    if table_has_columns(
        &conn,
        "operations",
        &["operation_id", "state", "slug", "cwd"],
    )? {
        let operation_id: Option<String> = conn
            .query_row(
                "select operation_id
                 from operations
                 where state in ('queued', 'running')
                   and (slug = ?1 or (slug is null and cwd = ?2))
                 order by created_at desc
                 limit 1",
                rusqlite::params![old_slug.as_str(), cwd.as_ref()],
                |row| row.get(0),
            )
            .optional()
            .map_err(daemon_db_error)?;
        if let Some(operation_id) = operation_id {
            return Err(WorkflowError::TodoRenameOperationBound {
                slug: old_slug.clone(),
                operation_id,
            });
        }
    }

    let session_columns = sqlite_columns(&conn, "sessions")?;
    if session_columns.contains(&"session_id".to_owned())
        && session_columns.contains(&"closed_at".to_owned())
        && session_columns.contains(&"lifecycle_status".to_owned())
    {
        let mut predicates = Vec::new();
        if session_columns.contains(&"working_slug".to_owned()) {
            predicates.push("working_slug = ?1");
        }
        if session_columns.contains(&"project_path".to_owned())
            && session_columns.contains(&"subdir".to_owned())
        {
            predicates.push("(project_path = ?2 and subdir = ?3)");
        }
        if !predicates.is_empty() {
            let sql = format!(
                "select session_id
                 from sessions
                 where closed_at is null
                   and coalesce(lifecycle_status, 'active') != 'closed'
                   and ({})
                 limit 1",
                predicates.join(" or ")
            );
            let session_id: Option<String> = conn
                .query_row(
                    &sql,
                    rusqlite::params![
                        old_slug.as_str(),
                        cwd.as_ref(),
                        format!("{WORKTREE_DIR}/{}", old_slug.as_str()),
                    ],
                    |row| row.get(0),
                )
                .optional()
                .map_err(daemon_db_error)?;
            if let Some(session_id) = session_id {
                return Err(WorkflowError::TodoRenameSessionBound {
                    slug: old_slug.clone(),
                    session_id,
                });
            }
        }
    }

    Ok(())
}

fn reconcile_post_commit_slug_refs(project_root: &Path, old_slug: &Slug, new_slug: &Slug) {
    if let Err(err) = delete_old_remote_slug_ref(project_root, old_slug) {
        tracing::warn!(error = ?err, old_slug = %old_slug.as_str(), "remote rename cleanup failed");
    }
    if let Err(err) = rewrite_daemon_slug_refs(project_root, old_slug, new_slug) {
        tracing::warn!(error = ?err, old_slug = %old_slug.as_str(), new_slug = %new_slug.as_str(), "daemon rename reconciliation failed");
    }
}

fn rewrite_daemon_slug_refs(
    project_root: &Path,
    old_slug: &Slug,
    new_slug: &Slug,
) -> Result<(), WorkflowError> {
    let Some(mut conn) = open_daemon_db(project_root)? else {
        return Ok(());
    };
    let operations_has_slug = table_has_columns(&conn, "operations", &["slug"])?;
    let operations_has_updated_at = table_has_columns(&conn, "operations", &["updated_at"])?;
    let sessions_has_working_slug = table_has_columns(&conn, "sessions", &["working_slug"])?;
    let sessions_has_subdir = table_has_columns(&conn, "sessions", &["project_path", "subdir"])?;
    let tx = conn.transaction().map_err(daemon_db_error)?;
    if operations_has_slug {
        if operations_has_updated_at {
            tx.execute(
                "update operations set slug = ?1, updated_at = ?2 where slug = ?3",
                rusqlite::params![
                    new_slug.as_str(),
                    Utc::now().to_rfc3339(),
                    old_slug.as_str()
                ],
            )
            .map_err(daemon_db_error)?;
        } else {
            tx.execute(
                "update operations set slug = ?1 where slug = ?2",
                rusqlite::params![new_slug.as_str(), old_slug.as_str()],
            )
            .map_err(daemon_db_error)?;
        }
    }

    if sessions_has_working_slug {
        tx.execute(
            "update sessions set working_slug = ?1 where working_slug = ?2",
            rusqlite::params![new_slug.as_str(), old_slug.as_str()],
        )
        .map_err(daemon_db_error)?;
    }
    if sessions_has_subdir {
        tx.execute(
            "update sessions set subdir = ?1 where project_path = ?2 and subdir = ?3",
            rusqlite::params![
                format!("{WORKTREE_DIR}/{}", new_slug.as_str()),
                project_root.to_string_lossy().as_ref(),
                format!("{WORKTREE_DIR}/{}", old_slug.as_str()),
            ],
        )
        .map_err(daemon_db_error)?;
    }
    tx.commit().map_err(daemon_db_error)?;
    Ok(())
}

fn open_daemon_db(project_root: &Path) -> Result<Option<rusqlite::Connection>, WorkflowError> {
    for path in daemon_db_candidates(project_root) {
        if path.exists() {
            return rusqlite::Connection::open(path)
                .map(Some)
                .map_err(daemon_db_error);
        }
    }
    Ok(None)
}

fn daemon_db_candidates(project_root: &Path) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Ok(path) = std::env::var("TELECLAUDE_DB_PATH") {
        paths.push(PathBuf::from(path));
    }
    paths.push(project_root.join(".teleclaude/teleclaude.db"));
    if let Ok(home) = std::env::var("TELECLAUDE_HOME") {
        paths.push(PathBuf::from(home).join("teleclaude.db"));
    } else if let Ok(home) = std::env::var("HOME") {
        paths.push(PathBuf::from(home).join(".teleclaude/teleclaude.db"));
    }
    paths
}

fn table_has_columns(
    conn: &rusqlite::Connection,
    table: &str,
    required: &[&str],
) -> Result<bool, WorkflowError> {
    let columns = sqlite_columns(conn, table)?;
    Ok(required
        .iter()
        .all(|column| columns.iter().any(|existing| existing == column)))
}

fn sqlite_columns(conn: &rusqlite::Connection, table: &str) -> Result<Vec<String>, WorkflowError> {
    let mut stmt = conn
        .prepare(&format!("pragma table_info({table})"))
        .map_err(daemon_db_error)?;
    let rows = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(daemon_db_error)?;
    let mut columns = Vec::new();
    for row in rows {
        columns.push(row.map_err(daemon_db_error)?);
    }
    Ok(columns)
}

fn daemon_db_error(err: rusqlite::Error) -> WorkflowError {
    WorkflowError::DaemonDb(err.to_string())
}

async fn append_snippet_diff_sections(
    pool: &sqlx::PgPool,
    project_root: &Path,
    slug: &Slug,
    sections: &mut Vec<TodoDiffSection>,
    diagnostics: &mut Vec<String>,
) -> Result<(), WorkflowError> {
    let docs_root = project_root.join("docs");
    if !docs_root.exists() {
        return Ok(());
    }

    let mut paths = Vec::new();
    collect_markdown_files(&docs_root, &mut paths)?;
    for path in paths {
        let current = fs::read_to_string(&path)?;
        let Some((frontmatter, _body)) = split_frontmatter(&current) else {
            continue;
        };
        if !frontmatter_delivered_by_contains(frontmatter, slug) {
            continue;
        }

        let rel_path = match path.strip_prefix(project_root) {
            Ok(rel) => rel.to_string_lossy().replace('\\', "/"),
            Err(_) => path.to_string_lossy().replace('\\', "/"),
        };
        let provenance: Option<String> = sqlx::query_scalar(
            "select head_sha_at_acquisition
             from workflow.snippet_provenance
             where snippet_path = $1 and slug = $2",
        )
        .bind(&rel_path)
        .bind(slug.as_str())
        .fetch_optional(pool)
        .await?;

        let (baseline_ref, baseline_content, prefix) = match provenance {
            Some(sha) => match git_show_file(project_root, &sha, &rel_path)? {
                Some(content) => (sha, content, None),
                None => {
                    diagnostics.push(format!("baseline-absent: {rel_path}"));
                    continue;
                }
            },
            None => match git_show_file(project_root, "main", &rel_path)? {
                Some(content) => (
                    "main".to_owned(),
                    content,
                    Some("baseline-fallback: main".to_owned()),
                ),
                None => {
                    diagnostics.push(format!("baseline-absent: {rel_path}"));
                    continue;
                }
            },
        };

        if baseline_content == current {
            continue;
        }
        sections.push(TodoDiffSection {
            label: rel_path.clone(),
            baseline: baseline_ref.clone(),
            current: "working-tree".to_owned(),
            diff: unified_diff(
                &format!("{rel_path}@{}", short_digest(&baseline_ref)),
                &format!("{rel_path}@working-tree"),
                &baseline_content,
                &current,
            ),
            prefix,
        });
    }

    Ok(())
}

fn git_show_file(
    project_root: &Path,
    rev: &str,
    rel_path: &str,
) -> Result<Option<String>, WorkflowError> {
    let repo = match git2::Repository::discover(project_root) {
        Ok(repo) => repo,
        Err(err) if err.code() == git2::ErrorCode::NotFound => return Ok(None),
        Err(err) => return Err(err.into()),
    };
    let tree = match repo
        .revparse_single(rev)
        .and_then(|object| object.peel_to_tree())
    {
        Ok(tree) => tree,
        Err(err) if err.code() == git2::ErrorCode::NotFound => return Ok(None),
        Err(err) => return Err(err.into()),
    };
    let entry = match tree.get_path(Path::new(rel_path)) {
        Ok(entry) => entry,
        Err(err) if err.code() == git2::ErrorCode::NotFound => return Ok(None),
        Err(err) => return Err(err.into()),
    };
    let blob = repo.find_blob(entry.id())?;
    Ok(Some(String::from_utf8_lossy(blob.content()).into_owned()))
}

fn frontmatter_delivered_by_contains(frontmatter: &str, slug: &Slug) -> bool {
    let mut in_delivered_by = false;
    for line in frontmatter.lines() {
        let trimmed = line.trim_start();
        if in_delivered_by
            && !trimmed.is_empty()
            && !line.starts_with(' ')
            && !line.starts_with('-')
        {
            in_delivered_by = false;
        }
        if trimmed.starts_with("delivered_by:") {
            in_delivered_by = true;
        }
        if in_delivered_by && delivered_by_line_contains_slug(line, slug) {
            return true;
        }
    }
    false
}

fn delivered_by_line_contains_slug(line: &str, slug: &Slug) -> bool {
    let trimmed = line.trim_start().strip_prefix('-').unwrap_or(line).trim();
    trimmed
        .split(['[', ']', ',', ' ', '\t', ':'])
        .any(|part| part.trim_matches(['"', '\'']) == slug.as_str())
}

fn review_key_for_artifact(name: ArtifactName) -> Option<&'static str> {
    match name {
        ArtifactName::Prd => Some("prd_review"),
        ArtifactName::Requirements => Some("requirements_review"),
        ArtifactName::Architecture => Some("architecture_review"),
        ArtifactName::ImplementationPlan => Some("plan_review"),
        _ => None,
    }
}

fn approved_digest(state_extra: &serde_json::Value, review_key: &str) -> Option<String> {
    state_extra
        .get(review_key)
        .and_then(|value| value.get("approved_digest"))
        .and_then(serde_json::Value::as_str)
        .filter(|digest| !digest.is_empty())
        .map(str::to_owned)
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

fn ensure_writable_artifact(name: ArtifactName) -> Result<(), WorkflowError> {
    match name {
        ArtifactName::TestSpecs | ArtifactName::SpecReviewFindings => {
            Err(WorkflowError::RetiredArtifactWrite { name })
        }
        _ => Ok(()),
    }
}

fn is_patch_blob(content: &str) -> bool {
    let trimmed = content.trim_start();
    trimmed.starts_with('{') || trimmed.starts_with('[') || trimmed.starts_with("---")
}

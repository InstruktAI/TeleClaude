//! Ordered todo-list storage operations.
//!
//! Maintains ordering and dependency storage now exposed through `telec todo`.
//! Roadmap order is a per-project monotonically
//! increasing `position` integer; mutations rewrite the affected positions
//! inside a single transaction so a reader never sees a hole or duplicate.
//!
//! ## Status vs. frozen
//!
//! The schema carries both a `status workflow.roadmap_status` enum
//! (`active` / `icebox` / `delivered`) and a `frozen boolean` for v1 fidelity.
//! The service keeps them in lock-step: freeze sets `status = 'icebox'` and
//! `frozen = true`; unfreeze reverses it; deliver sets `status = 'delivered'`
//! and `delivered_at`. The model exposes only `frozen` plus `delivered_at`
//! and `commit_hash`; callers that need the raw status read the schema.

use chrono::{DateTime, Utc};
use identity::Principal;
use shared::{ProjectId, Slug};
use sqlx::types::Json;
use sqlx::Row;
use uuid::Uuid;

use crate::errors::WorkflowError;
use crate::events::{
    RoadmapEntryAdded, RoadmapEntryMoved, RoadmapEntryRemoved, CHANNEL_ROADMAP_ENTRY_ADDED,
    CHANNEL_ROADMAP_ENTRY_MOVED, CHANNEL_ROADMAP_ENTRY_REMOVED,
};
use crate::models::RoadmapEntry;
use crate::service::todos::insert_roadmap_deps;
use crate::service::WorkflowService;

/// Channel for roadmap deliver events. Local constant — the deliver event
/// payload is small enough that exposing it on `crate::events` was deferred
/// to the next wave; the channel name follows the v2 naming convention.
const CHANNEL_ROADMAP_ENTRY_DELIVERED: &str = "workflow.roadmap.entry_delivered";
/// Channel for freeze events.
const CHANNEL_ROADMAP_ENTRY_FROZEN: &str = "workflow.roadmap.entry_frozen";
/// Channel for unfreeze events.
const CHANNEL_ROADMAP_ENTRY_UNFROZEN: &str = "workflow.roadmap.entry_unfrozen";

impl WorkflowService {
    /// List roadmap entries for a project in `position` order.
    ///
    /// `include_icebox` and `include_delivered` widen the result set;
    /// `active` rows are always included.
    pub async fn list_roadmap(
        &self,
        project: ProjectId,
        include_icebox: bool,
        include_delivered: bool,
    ) -> Result<Vec<RoadmapEntry>, WorkflowError> {
        let rows = sqlx::query(
            "select uuid_id, project_id, slug, group_slug, position, frozen, after,
                    description, delivered_at, delivered_commit, status::text as status_text
             from workflow.roadmap_entries
             where project_id = $1
               and (status = 'active'
                    or ($2 and status = 'icebox')
                    or ($3 and status = 'delivered'))
             order by position asc",
        )
        .bind(project)
        .bind(include_icebox)
        .bind(include_delivered)
        .fetch_all(self.pool())
        .await?;

        rows.into_iter().map(row_to_roadmap_entry).collect()
    }

    /// Add a new roadmap entry, optionally inserting before an existing slug.
    ///
    /// Without `before`, the entry is appended at the tail. With `before`,
    /// the new entry takes the target's position and every entry at-or-after
    /// that position is shifted by `+1` in the same transaction. Emits
    /// `workflow.roadmap.entry_added`.
    #[allow(clippy::too_many_arguments)]
    pub async fn add_roadmap_entry(
        &self,
        project: ProjectId,
        slug: Slug,
        group: Option<String>,
        after: Vec<Slug>,
        before: Option<Slug>,
        description: Option<String>,
        principal: &Principal,
    ) -> Result<RoadmapEntry, WorkflowError> {
        let after_strings: Vec<String> = after.iter().map(|s| s.as_str().to_owned()).collect();
        let mut tx = self.pool().begin().await?;

        let target_position: i32 = match &before {
            Some(target) => {
                let position: Option<i32> = sqlx::query_scalar(
                    "select position from workflow.roadmap_entries
                     where project_id = $1 and slug = $2",
                )
                .bind(project)
                .bind(target.as_str())
                .fetch_optional(&mut *tx)
                .await?;
                let Some(position) = position else {
                    return Err(WorkflowError::RoadmapEntryNotFound(target.clone()));
                };
                sqlx::query(
                    "update workflow.roadmap_entries
                     set position = position + 1, updated_at = now()
                     where project_id = $1 and position >= $2",
                )
                .bind(project)
                .bind(position)
                .execute(&mut *tx)
                .await?;
                position
            }
            None => {
                sqlx::query_scalar(
                    "select coalesce(max(position), 0) + 1
                     from workflow.roadmap_entries where project_id = $1",
                )
                .bind(project)
                .fetch_one(&mut *tx)
                .await?
            }
        };

        let row = sqlx::query(
            "insert into workflow.roadmap_entries
                (project_id, slug, position, group_slug, description, after)
             values ($1, $2, $3, $4, $5, $6::jsonb)
             returning uuid_id, project_id, slug, group_slug, position, frozen, after,
                       description, delivered_at, delivered_commit, status::text as status_text",
        )
        .bind(project)
        .bind(slug.as_str())
        .bind(target_position)
        .bind(group.as_deref())
        .bind(description.as_deref())
        .bind(serde_json::to_value(&after_strings)?)
        .fetch_one(&mut *tx)
        .await
        .map_err(|err| classify_roadmap_unique(err, &slug))?;

        insert_roadmap_deps(&mut tx, project, &slug, &after).await?;

        let entry = row_to_roadmap_entry(row)?;

        tx.commit().await?;

        self.publish(
            CHANNEL_ROADMAP_ENTRY_ADDED,
            &RoadmapEntryAdded {
                project_id: entry.project_id,
                slug: entry.slug.clone(),
                position: entry.position,
                added_at: Utc::now(),
            },
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;

        Ok(entry)
    }

    /// Move a roadmap entry to be immediately before or after a target slug.
    ///
    /// Exactly one of `before` / `after` must be set. Emits
    /// `workflow.roadmap.entry_moved` carrying the (from, to) positions.
    /// Returns [`WorkflowError::RoadmapMoveArguments`] when both or neither
    /// pivot is supplied.
    pub async fn move_roadmap_entry(
        &self,
        project: ProjectId,
        slug: &Slug,
        before: Option<Slug>,
        after: Option<Slug>,
        principal: &Principal,
    ) -> Result<RoadmapEntry, WorkflowError> {
        if before.is_some() == after.is_some() {
            return Err(WorkflowError::RoadmapMoveArguments {
                before: before.is_some(),
                after: after.is_some(),
            });
        }

        let mut tx = self.pool().begin().await?;

        let from_position: Option<i32> = sqlx::query_scalar(
            "select position from workflow.roadmap_entries
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .fetch_optional(&mut *tx)
        .await?;
        let Some(from_position) = from_position else {
            return Err(WorkflowError::RoadmapEntryNotFound(slug.clone()));
        };

        // The xor invariant is enforced by `RoadmapMoveArguments` above, but
        // we re-thread the absence as a typed error instead of panicking so
        // future refactors of that guard can't silently regress into a
        // production unwrap.
        let pivot_slug =
            before
                .as_ref()
                .or(after.as_ref())
                .ok_or(WorkflowError::RoadmapMoveArguments {
                    before: false,
                    after: false,
                })?;
        let pivot_position: Option<i32> = sqlx::query_scalar(
            "select position from workflow.roadmap_entries
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(pivot_slug.as_str())
        .fetch_optional(&mut *tx)
        .await?;
        let Some(pivot_position) = pivot_position else {
            return Err(WorkflowError::RoadmapEntryNotFound(pivot_slug.clone()));
        };

        let target_position = match (before.is_some(), pivot_position.cmp(&from_position)) {
            // Inserting before a pivot that sits later: pivot shifts left by 1
            // when we lift `slug`, so the slot just before pivot is pivot-1.
            (true, std::cmp::Ordering::Greater) => pivot_position - 1,
            (true, _) => pivot_position,
            (false, std::cmp::Ordering::Less) => pivot_position + 1,
            (false, _) => pivot_position,
        };

        if target_position == from_position {
            // Nothing to do. Read back and emit a no-op move so consumers
            // still see the event (matches v1 behavior).
            let row = roadmap_row(&mut tx, project, slug).await?;
            let entry = row_to_roadmap_entry(row)?;
            tx.commit().await?;
            self.publish(
                CHANNEL_ROADMAP_ENTRY_MOVED,
                &RoadmapEntryMoved {
                    project_id: entry.project_id,
                    slug: entry.slug.clone(),
                    from_position,
                    to_position: from_position,
                    moved_at: Utc::now(),
                },
                event_bus::EventScope::Cluster,
                principal,
            )
            .await?;
            return Ok(entry);
        }

        // Lift the row out of the order space by parking it at -1 so the
        // unique-position invariant is satisfied while we shift neighbors.
        sqlx::query(
            "update workflow.roadmap_entries
             set position = -1, updated_at = now()
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .execute(&mut *tx)
        .await?;

        if target_position < from_position {
            // Moving up: shift everyone in [target, from-1] down by 1.
            sqlx::query(
                "update workflow.roadmap_entries
                 set position = position + 1, updated_at = now()
                 where project_id = $1
                   and position >= $2 and position <= $3",
            )
            .bind(project)
            .bind(target_position)
            .bind(from_position - 1)
            .execute(&mut *tx)
            .await?;
        } else {
            // Moving down: shift everyone in (from, target] up by 1.
            sqlx::query(
                "update workflow.roadmap_entries
                 set position = position - 1, updated_at = now()
                 where project_id = $1
                   and position > $2 and position <= $3",
            )
            .bind(project)
            .bind(from_position)
            .bind(target_position)
            .execute(&mut *tx)
            .await?;
        }

        sqlx::query(
            "update workflow.roadmap_entries
             set position = $3, updated_at = now()
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .bind(target_position)
        .execute(&mut *tx)
        .await?;

        let row = roadmap_row(&mut tx, project, slug).await?;
        let entry = row_to_roadmap_entry(row)?;

        tx.commit().await?;

        self.publish(
            CHANNEL_ROADMAP_ENTRY_MOVED,
            &RoadmapEntryMoved {
                project_id: entry.project_id,
                slug: entry.slug.clone(),
                from_position,
                to_position: target_position,
                moved_at: Utc::now(),
            },
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;

        Ok(entry)
    }

    /// Move an entry to the icebox.
    ///
    /// Sets both `status = 'icebox'` and `frozen = true`. Emits
    /// `workflow.roadmap.entry_frozen`. Returns [`WorkflowError::RoadmapEntryNotFound`]
    /// if no row matches.
    pub async fn freeze_roadmap_entry(
        &self,
        project: ProjectId,
        slug: &Slug,
        principal: &Principal,
    ) -> Result<RoadmapEntry, WorkflowError> {
        self.set_freeze(project, slug, true, principal).await
    }

    /// Move an entry back from the icebox.
    ///
    /// Sets both `status = 'active'` and `frozen = false`. Emits
    /// `workflow.roadmap.entry_unfrozen`.
    pub async fn unfreeze_roadmap_entry(
        &self,
        project: ProjectId,
        slug: &Slug,
        principal: &Principal,
    ) -> Result<RoadmapEntry, WorkflowError> {
        self.set_freeze(project, slug, false, principal).await
    }

    async fn set_freeze(
        &self,
        project: ProjectId,
        slug: &Slug,
        frozen: bool,
        principal: &Principal,
    ) -> Result<RoadmapEntry, WorkflowError> {
        let new_status = if frozen { "icebox" } else { "active" };
        let mut tx = self.pool().begin().await?;

        let result = sqlx::query(
            "update workflow.roadmap_entries
             set frozen = $3, status = $4::workflow.roadmap_status, updated_at = now()
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .bind(frozen)
        .bind(new_status)
        .execute(&mut *tx)
        .await?;

        if result.rows_affected() == 0 {
            return Err(WorkflowError::RoadmapEntryNotFound(slug.clone()));
        }

        let row = roadmap_row(&mut tx, project, slug).await?;
        let entry = row_to_roadmap_entry(row)?;
        tx.commit().await?;

        let channel = if frozen {
            CHANNEL_ROADMAP_ENTRY_FROZEN
        } else {
            CHANNEL_ROADMAP_ENTRY_UNFROZEN
        };
        self.publish(
            channel,
            &serde_json::json!({
                "project_id": entry.project_id,
                "slug": entry.slug,
                "frozen": frozen,
            }),
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;

        Ok(entry)
    }

    /// Remove a roadmap entry (and, by cascade, the attached todo, its
    /// artifacts, versions, and state transitions). Emits
    /// `workflow.roadmap.entry_removed`.
    pub async fn remove_roadmap_entry(
        &self,
        project: ProjectId,
        slug: &Slug,
        principal: &Principal,
    ) -> Result<(), WorkflowError> {
        let mut tx = self.pool().begin().await?;

        let result =
            sqlx::query("delete from workflow.roadmap_entries where project_id = $1 and slug = $2")
                .bind(project)
                .bind(slug.as_str())
                .execute(&mut *tx)
                .await?;

        if result.rows_affected() == 0 {
            return Err(WorkflowError::RoadmapEntryNotFound(slug.clone()));
        }

        sqlx::query("delete from workflow.roadmap_deps where project_id = $1 and slug = $2")
            .bind(project)
            .bind(slug.as_str())
            .execute(&mut *tx)
            .await?;

        tx.commit().await?;

        self.publish(
            CHANNEL_ROADMAP_ENTRY_REMOVED,
            &RoadmapEntryRemoved {
                project_id: project,
                slug: slug.clone(),
                removed_at: Utc::now(),
            },
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;
        Ok(())
    }

    /// Mark a roadmap entry as delivered, optionally recording the commit
    /// hash that delivered it.
    ///
    /// Sets `status = 'delivered'`, stamps `delivered_at = now()`, and
    /// stores `delivered_commit`. Also updates the linked todo's
    /// `delivered_at` for symmetry. Emits `workflow.roadmap.entry_delivered`.
    pub async fn deliver_roadmap_entry(
        &self,
        project: ProjectId,
        slug: &Slug,
        commit_hash: Option<String>,
        principal: &Principal,
    ) -> Result<RoadmapEntry, WorkflowError> {
        let mut tx = self.pool().begin().await?;

        let result = sqlx::query(
            "update workflow.roadmap_entries
             set status = 'delivered'::workflow.roadmap_status,
                 delivered_at = now(),
                 delivered_commit = $3,
                 updated_at = now()
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .bind(commit_hash.as_deref())
        .execute(&mut *tx)
        .await?;

        if result.rows_affected() == 0 {
            return Err(WorkflowError::RoadmapEntryNotFound(slug.clone()));
        }

        sqlx::query(
            "update workflow.todos
             set delivered_at = now(), updated_at = now()
             where project_id = $1 and slug = $2",
        )
        .bind(project)
        .bind(slug.as_str())
        .execute(&mut *tx)
        .await?;

        let row = roadmap_row(&mut tx, project, slug).await?;
        let entry = row_to_roadmap_entry(row)?;

        tx.commit().await?;

        self.publish(
            CHANNEL_ROADMAP_ENTRY_DELIVERED,
            &serde_json::json!({
                "project_id": entry.project_id,
                "slug": entry.slug,
                "commit_hash": entry.commit_hash,
                "delivered_at": entry.delivered_at,
            }),
            event_bus::EventScope::Cluster,
            principal,
        )
        .await?;

        Ok(entry)
    }
}

async fn roadmap_row(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    project: ProjectId,
    slug: &Slug,
) -> Result<sqlx::postgres::PgRow, WorkflowError> {
    let row = sqlx::query(
        "select uuid_id, project_id, slug, group_slug, position, frozen, after,
                description, delivered_at, delivered_commit, status::text as status_text
         from workflow.roadmap_entries
         where project_id = $1 and slug = $2",
    )
    .bind(project)
    .bind(slug.as_str())
    .fetch_optional(&mut **tx)
    .await?;
    row.ok_or_else(|| WorkflowError::RoadmapEntryNotFound(slug.clone()))
}

fn row_to_roadmap_entry(row: sqlx::postgres::PgRow) -> Result<RoadmapEntry, WorkflowError> {
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
    Ok(RoadmapEntry {
        id: row.try_get::<Uuid, _>("uuid_id")?,
        project_id: row.try_get("project_id")?,
        slug: Slug(row.try_get::<String, _>("slug")?),
        group: row.try_get::<Option<String>, _>("group_slug")?,
        position: row.try_get("position")?,
        frozen: row.try_get("frozen")?,
        after,
        description: row.try_get::<Option<String>, _>("description")?,
        delivered_at: row.try_get::<Option<DateTime<Utc>>, _>("delivered_at")?,
        commit_hash: row.try_get::<Option<String>, _>("delivered_commit")?,
    })
}

fn classify_roadmap_unique(err: sqlx::Error, slug: &Slug) -> WorkflowError {
    if let sqlx::Error::Database(db_err) = &err {
        if db_err.code().as_deref() == Some("23505") {
            return WorkflowError::DuplicateSlug(slug.clone());
        }
    }
    WorkflowError::Db(err)
}

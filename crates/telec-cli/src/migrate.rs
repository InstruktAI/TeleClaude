//! `telec-cli migrate-workflow-v1` — one-shot import of a v1 SQLite
//! `.teleclaude/todos.db` into the v2 Postgres `workflow` schema.
//!
//! ## v1 source schema
//!
//! Defined in `teleclaude/core/todos_db/schema.sql`:
//!
//! * `roadmap(id TEXT PK uuid, slug, position, group_slug, description,
//!   status, delivered_at, delivered_commit, children, created_at,
//!   updated_at)`
//! * `todo_state(id TEXT PK = roadmap.id, slug, state TEXT JSON,
//!   created_at, updated_at)`
//! * `todo_artifacts(id, slug, name, content, digest, updated_by,
//!   updated_at)` PK `(id, name)`
//! * `todo_artifact_versions(version_id AUTO, id, slug, name, content,
//!   digest, updated_by, created_at)`
//! * `roadmap_deps(slug, depends_on)` — no `project_id` because v1 is
//!   one project per SQLite file.
//!
//! ## Mapping to v2
//!
//! * `roadmap` rows → `workflow.roadmap_entries` (1:1, FK to project).
//! * `todo_state` rows → `workflow.todos`. The opaque JSON blob is
//!   parsed; known fields (`kind`, `lifecycle_phase`, `integration_phase`,
//!   `finalize_status`) are promoted to typed columns. Every remaining
//!   key lands in `state_extra` so the migration is lossless.
//! * `todo_artifacts` → `workflow.artifacts` (one current row per
//!   `(todo, name)`).
//! * `todo_artifact_versions` → `workflow.artifact_versions` (append-only
//!   history).
//! * `roadmap_deps` → `workflow.roadmap_deps` with the v2 `project_id`
//!   stamped in.
//! * v1 has no `state_transitions` log; nothing to import.
//!
//! ## Idempotency
//!
//! `workflow.migrations_v1` tracks one row per project with the SHA-256
//! of the SQLite file at migration time:
//!
//! * Re-run against the same SHA — skip with a clear "already migrated"
//!   message (exit 0).
//! * Re-run against a different SHA without `--force` — refuse with an
//!   error.
//! * Re-run with `--force` — delete the project's existing v2 rows
//!   (roadmap entries cascade to todos/artifacts/transitions; roadmap
//!   deps cascade off the project FK) and re-import.
//!
//! ## Transactionality
//!
//! Every Postgres write happens in a single transaction. `--dry-run`
//! rolls the transaction back at the end, leaving v2 untouched while
//! still exercising the full read + insert path.

use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{anyhow, bail, Context, Result};
use chrono::{DateTime, NaiveDateTime, Utc};
use clap::Args;
use rusqlite::Connection;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use sqlx::{Postgres, Transaction};
use uuid::Uuid;
use workflow::WorkflowService;

/// Arguments for `telec-cli migrate-workflow-v1`.
#[derive(Args, Debug, Clone)]
pub struct MigrateArgs {
    /// Project name to use for the migrated rows. Required because the v1
    /// SQLite database does not carry an explicit project name; the
    /// migration must place the rows under a v2 project row.
    pub project: String,

    /// Optional explicit path to the v1 `.teleclaude/todos.db` SQLite file. When
    /// omitted, the migration looks for `.teleclaude/todos.db` under the
    /// current working directory.
    #[arg(long)]
    pub source: Option<String>,

    /// Run the migration in a transaction that is rolled back at the end.
    /// Useful for verifying the read path without touching the destination.
    #[arg(long)]
    pub dry_run: bool,

    /// Re-import even when the source DB has changed since the previous
    /// migration. Deletes the project's existing v2 rows before
    /// re-importing. Without `--force`, a SHA mismatch is an error.
    #[arg(long)]
    pub force: bool,
}

/// Run the migration. Returns the process exit code.
///
/// * `0` on success or "already migrated" short-circuit.
/// * Any error is surfaced via `anyhow::Error` and rendered with exit
///   code `1` by `main`.
pub async fn run(args: MigrateArgs, service: &WorkflowService) -> Result<i32> {
    let pool = service.pool();

    let (db_path, project_root) = resolve_paths(&args)?;
    if !db_path.is_file() {
        bail!(
            "v1 todos.db not found at {} (project '{}')",
            db_path.display(),
            args.project
        );
    }

    let source_sha =
        sha256_hex_of_file(&db_path).with_context(|| format!("hashing {}", db_path.display()))?;

    let existing: Option<String> = sqlx::query_scalar(
        "select source_db_sha256 from workflow.migrations_v1 where project_name = $1",
    )
    .bind(&args.project)
    .fetch_optional(pool)
    .await?;

    let project_name = args.project.as_str();
    let force_overwrite = match existing.as_deref() {
        Some(prev) if prev == source_sha => {
            println!(
                "migrate-workflow-v1: '{project_name}' already migrated from this todos.db \
                 (sha={source_sha}); nothing to do"
            );
            return Ok(0);
        }
        Some(_) if !args.force => {
            bail!(
                "v1 todos.db for '{project_name}' has changed since the last migration; \
                 refuse to re-migrate without --force"
            );
        }
        Some(_) => true,
        None => false,
    };

    let v1 = read_v1_database(&db_path)
        .with_context(|| format!("reading v1 db {}", db_path.display()))?;

    let mut tx = pool.begin().await?;
    let project_id = upsert_project(&mut tx, project_name, &project_root).await?;

    if force_overwrite {
        // Cascades: roadmap_entries → todos → artifacts/versions/transitions.
        // roadmap_deps and migrations_v1 keyed independently.
        sqlx::query("delete from workflow.roadmap_entries where project_id = $1")
            .bind(project_id)
            .execute(&mut *tx)
            .await?;
        sqlx::query("delete from workflow.roadmap_deps where project_id = $1")
            .bind(project_id)
            .execute(&mut *tx)
            .await?;
    }

    let stats = import_rows(&mut tx, &v1, project_id).await?;

    sqlx::query(
        "insert into workflow.migrations_v1
            (project_name, source_db_sha256, rows_migrated)
         values ($1, $2, $3)
         on conflict (project_name) do update set
            migrated_at      = now(),
            source_db_sha256 = excluded.source_db_sha256,
            rows_migrated    = excluded.rows_migrated",
    )
    .bind(project_name)
    .bind(&source_sha)
    .bind(stats.total())
    .execute(&mut *tx)
    .await?;

    if args.dry_run {
        tx.rollback().await?;
        println!(
            "migrate-workflow-v1: dry-run — would have migrated {todos} todos, \
             {roadmap} roadmap entries, {artifacts} artifacts ({versions} versions), \
             {deps} dep edges for '{project_name}'",
            todos = stats.todos,
            roadmap = stats.roadmap_entries,
            artifacts = stats.artifacts,
            versions = stats.artifact_versions,
            deps = stats.roadmap_deps,
        );
        return Ok(0);
    }

    tx.commit().await?;

    println!(
        "migrate-workflow-v1: migrated {todos} todos, {roadmap} roadmap entries, \
         {artifacts} artifacts ({versions} versions), {deps} dep edges for \
         '{project_name}' from {path}",
        todos = stats.todos,
        roadmap = stats.roadmap_entries,
        artifacts = stats.artifacts,
        versions = stats.artifact_versions,
        deps = stats.roadmap_deps,
        path = db_path.display(),
    );

    Ok(0)
}

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

/// Resolve `(db_path, project_root)`.
///
/// * `db_path` — the v1 SQLite file. Explicit `--source` wins; otherwise
///   `<cwd>/.teleclaude/todos.db`.
/// * `project_root` — the directory above `.teleclaude/`. Recorded in
///   `workflow.projects.root_path`.
fn resolve_paths(args: &MigrateArgs) -> Result<(PathBuf, PathBuf)> {
    let db_path = match &args.source {
        Some(s) => PathBuf::from(s),
        None => {
            let cwd = std::env::current_dir().context("read current working directory")?;
            cwd.join(".teleclaude").join("todos.db")
        }
    };

    let project_root = derive_project_root(&db_path)?;
    Ok((db_path, project_root))
}

/// Walk up from a `.teleclaude/todos.db` path to its enclosing project
/// root. Falls back to the file's parent when the layout does not match.
fn derive_project_root(db_path: &Path) -> Result<PathBuf> {
    let parent = db_path
        .parent()
        .ok_or_else(|| anyhow!("db path has no parent: {}", db_path.display()))?;
    if parent.file_name() == Some(OsStr::new(".teleclaude")) {
        if let Some(grand) = parent.parent() {
            return Ok(grand.to_path_buf());
        }
    }
    Ok(parent.to_path_buf())
}

// ---------------------------------------------------------------------------
// SHA-256
// ---------------------------------------------------------------------------

fn sha256_hex_of_file(path: &Path) -> Result<String> {
    let bytes = fs::read(path)?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    Ok(format!("{:x}", hasher.finalize()))
}

// ---------------------------------------------------------------------------
// Project upsert
// ---------------------------------------------------------------------------

async fn upsert_project(
    tx: &mut Transaction<'_, Postgres>,
    name: &str,
    root: &Path,
) -> Result<Uuid> {
    let root_str = root
        .to_str()
        .ok_or_else(|| anyhow!("non-utf8 project root path: {}", root.display()))?;
    let id: Uuid = sqlx::query_scalar(
        "insert into workflow.projects (name, root_path) values ($1, $2)
         on conflict (name) do update set root_path = excluded.root_path
         returning id",
    )
    .bind(name)
    .bind(root_str)
    .fetch_one(&mut **tx)
    .await?;
    Ok(id)
}

// ---------------------------------------------------------------------------
// v1 source reader
// ---------------------------------------------------------------------------

#[derive(Debug)]
struct V1Db {
    roadmap: Vec<RoadmapRow>,
    todo_state: Vec<TodoStateRow>,
    artifacts: Vec<ArtifactRow>,
    artifact_versions: Vec<ArtifactVersionRow>,
    roadmap_deps: Vec<RoadmapDepRow>,
}

#[derive(Debug)]
struct RoadmapRow {
    id: String,
    slug: String,
    position: i32,
    group_slug: Option<String>,
    description: Option<String>,
    status: String,
    delivered_at: Option<DateTime<Utc>>,
    delivered_commit: Option<String>,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug)]
struct TodoStateRow {
    v1_id: String,
    slug: String,
    state_json: Value,
    created_at: DateTime<Utc>,
    updated_at: DateTime<Utc>,
}

#[derive(Debug)]
struct ArtifactRow {
    v1_id: String,
    slug: String,
    name: String,
    content: String,
    digest: String,
    updated_by: Option<String>,
    updated_at: Option<DateTime<Utc>>,
}

#[derive(Debug)]
struct ArtifactVersionRow {
    v1_id: String,
    slug: String,
    name: String,
    content: String,
    digest: String,
    updated_by: Option<String>,
    created_at: DateTime<Utc>,
}

#[derive(Debug)]
struct RoadmapDepRow {
    slug: String,
    depends_on: String,
}

fn read_v1_database(path: &Path) -> Result<V1Db> {
    let conn = Connection::open_with_flags(path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
        .with_context(|| format!("open v1 sqlite {}", path.display()))?;
    Ok(V1Db {
        roadmap: read_roadmap(&conn)?,
        todo_state: read_todo_state(&conn)?,
        artifacts: read_artifacts(&conn)?,
        artifact_versions: read_artifact_versions(&conn)?,
        roadmap_deps: read_roadmap_deps(&conn)?,
    })
}

fn parse_iso(s: &str) -> Result<DateTime<Utc>> {
    if let Ok(dt) = DateTime::parse_from_rfc3339(s) {
        return Ok(dt.with_timezone(&Utc));
    }
    // v1 occasionally writes naive timestamps (no TZ); treat as UTC.
    if let Ok(naive) = NaiveDateTime::parse_from_str(s, "%Y-%m-%dT%H:%M:%S%.f") {
        return Ok(naive.and_utc());
    }
    if let Ok(naive) = NaiveDateTime::parse_from_str(s, "%Y-%m-%d %H:%M:%S%.f") {
        return Ok(naive.and_utc());
    }
    Err(anyhow!("invalid ISO timestamp {s:?}"))
}

fn parse_iso_opt(s: Option<String>) -> Result<Option<DateTime<Utc>>> {
    match s.as_deref() {
        None | Some("") => Ok(None),
        Some(v) => parse_iso(v).map(Some),
    }
}

fn read_roadmap(conn: &Connection) -> Result<Vec<RoadmapRow>> {
    let mut stmt = conn.prepare(
        "select id, slug, position, group_slug, description, status,
                delivered_at, delivered_commit, created_at, updated_at
         from roadmap
         order by position asc",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, i32>(2)?,
            row.get::<_, Option<String>>(3)?,
            row.get::<_, Option<String>>(4)?,
            row.get::<_, String>(5)?,
            row.get::<_, Option<String>>(6)?,
            row.get::<_, Option<String>>(7)?,
            row.get::<_, String>(8)?,
            row.get::<_, String>(9)?,
        ))
    })?;
    let mut out = Vec::new();
    for row in rows {
        let (
            id,
            slug,
            position,
            group_slug,
            description,
            status,
            delivered_at,
            delivered_commit,
            created_at,
            updated_at,
        ) = row?;
        out.push(RoadmapRow {
            id,
            slug,
            position,
            group_slug,
            description,
            status,
            delivered_at: parse_iso_opt(delivered_at)?,
            delivered_commit,
            created_at: parse_iso(&created_at)?,
            updated_at: parse_iso(&updated_at)?,
        });
    }
    Ok(out)
}

fn read_todo_state(conn: &Connection) -> Result<Vec<TodoStateRow>> {
    let mut stmt =
        conn.prepare("select id, slug, state, created_at, updated_at from todo_state")?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
        ))
    })?;
    let mut out = Vec::new();
    for row in rows {
        let (id, slug, state, created_at, updated_at) = row?;
        let state_json: Value = serde_json::from_str(&state)
            .with_context(|| format!("parse state JSON for slug={slug}"))?;
        out.push(TodoStateRow {
            v1_id: id,
            slug,
            state_json,
            created_at: parse_iso(&created_at)?,
            updated_at: parse_iso(&updated_at)?,
        });
    }
    Ok(out)
}

fn read_artifacts(conn: &Connection) -> Result<Vec<ArtifactRow>> {
    let mut stmt = conn.prepare(
        "select id, slug, name, content, digest, updated_by, updated_at
         from todo_artifacts",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, Option<String>>(5)?,
            row.get::<_, Option<String>>(6)?,
        ))
    })?;
    let mut out = Vec::new();
    for row in rows {
        let (id, slug, name, content, digest, updated_by, updated_at) = row?;
        out.push(ArtifactRow {
            v1_id: id,
            slug,
            name,
            content,
            digest,
            updated_by,
            updated_at: parse_iso_opt(updated_at)?,
        });
    }
    Ok(out)
}

fn read_artifact_versions(conn: &Connection) -> Result<Vec<ArtifactVersionRow>> {
    let mut stmt = conn.prepare(
        "select id, slug, name, content, digest, updated_by, created_at
         from todo_artifact_versions
         order by version_id asc",
    )?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
            row.get::<_, Option<String>>(5)?,
            row.get::<_, String>(6)?,
        ))
    })?;
    let mut out = Vec::new();
    for row in rows {
        let (id, slug, name, content, digest, updated_by, created_at) = row?;
        out.push(ArtifactVersionRow {
            v1_id: id,
            slug,
            name,
            content,
            digest,
            updated_by,
            created_at: parse_iso(&created_at)?,
        });
    }
    Ok(out)
}

fn read_roadmap_deps(conn: &Connection) -> Result<Vec<RoadmapDepRow>> {
    let mut stmt = conn.prepare("select slug, depends_on from roadmap_deps")?;
    let rows = stmt.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    let mut out = Vec::new();
    for row in rows {
        let (slug, depends_on) = row?;
        out.push(RoadmapDepRow { slug, depends_on });
    }
    Ok(out)
}

// ---------------------------------------------------------------------------
// v2 sink writer
// ---------------------------------------------------------------------------

/// Allowed values for each enum column, kept here so we can validate v1
/// strings before binding them to a `::workflow.<enum>` cast.
const ARTIFACT_NAMES: &[&str] = &[
    "input",
    "prd",
    "requirements",
    "architecture",
    "test-specs",
    "implementation-plan",
    "bug",
    "quality-checklist",
    "design-spec",
    "deferrals",
    "requirements-review-findings",
    "architecture-review-findings",
    "spec-review-findings",
    "plan-review-findings",
    "review-findings",
];

const TODO_KINDS: &[&str] = &["feature", "change", "bug"];

const LIFECYCLE_PHASES: &[&str] = &[
    "draft",
    "prd_drafting",
    "prd_human_approval",
    "architecture_drafting",
    "architecture_review",
    "test_specs_drafting",
    "test_specs_review",
    "plan_drafting",
    "plan_review",
    "prepared",
    "blocked",
    "build_started",
    "build_complete",
    "review_changes_requested",
    "review_approved",
    "finalize_ready",
    "handed_off",
];

const ROADMAP_STATUSES: &[&str] = &["active", "icebox", "delivered"];

fn normalize_lifecycle_phase(raw: &str) -> Option<String> {
    let normalized = match raw {
        "architecture_human_approval" => "architecture_review".to_owned(),
        "test_specs_human_approval" => "test_specs_review".to_owned(),
        "plan_human_approval" => "plan_review".to_owned(),
        _ if LIFECYCLE_PHASES.contains(&raw) => raw.to_owned(),
        _ => return None,
    };
    Some(normalized)
}

#[derive(Debug, Default)]
struct ImportStats {
    roadmap_entries: usize,
    roadmap_deps: usize,
    todos: usize,
    artifacts: usize,
    artifact_versions: usize,
}

impl ImportStats {
    fn total(&self) -> i32 {
        let total = self.roadmap_entries
            + self.roadmap_deps
            + self.todos
            + self.artifacts
            + self.artifact_versions;
        i32::try_from(total).unwrap_or(i32::MAX)
    }
}

async fn import_rows(
    tx: &mut Transaction<'_, Postgres>,
    v1: &V1Db,
    project_id: Uuid,
) -> Result<ImportStats> {
    let mut stats = ImportStats::default();

    // v1 roadmap.id (uuid string) → v2 roadmap_entries.id (bigserial).
    let mut roadmap_pk_by_v1id: BTreeMap<String, i64> = BTreeMap::new();

    // Group v1 roadmap_deps by slug once so each roadmap_entries row can
    // serialise its dependency list in O(1) after the build.
    let mut deps_by_slug: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
    for dep in &v1.roadmap_deps {
        deps_by_slug
            .entry(dep.slug.as_str())
            .or_default()
            .push(dep.depends_on.as_str());
    }

    for entry in &v1.roadmap {
        let after_for_slug: Vec<&str> = deps_by_slug
            .get(entry.slug.as_str())
            .cloned()
            .unwrap_or_default();
        let after_json: Value = serde_json::to_value(&after_for_slug)?;

        // Reviewer Critical-2: unknown roadmap status aborts instead of
        // silently defaulting.
        if !ROADMAP_STATUSES.contains(&entry.status.as_str()) {
            anyhow::bail!(
                "roadmap entry {slug}: unknown v1 status {status:?}; refusing migration. \
                 Allowed: {allowed:?}",
                slug = entry.slug,
                status = entry.status,
                allowed = ROADMAP_STATUSES,
            );
        }
        let status = entry.status.clone();
        let frozen = status == "icebox";

        let rid: i64 = sqlx::query_scalar(
            "insert into workflow.roadmap_entries
                (project_id, slug, position, group_slug, description, status, frozen,
                 after, delivered_at, delivered_commit, created_at, updated_at)
             values ($1, $2, $3, $4, $5, $6::workflow.roadmap_status, $7, $8::jsonb,
                     $9, $10, $11, $12)
             returning id",
        )
        .bind(project_id)
        .bind(&entry.slug)
        .bind(entry.position)
        .bind(entry.group_slug.as_deref())
        .bind(entry.description.as_deref())
        .bind(&status)
        .bind(frozen)
        .bind(&after_json)
        .bind(entry.delivered_at)
        .bind(entry.delivered_commit.as_deref())
        .bind(entry.created_at)
        .bind(entry.updated_at)
        .fetch_one(&mut **tx)
        .await
        .with_context(|| format!("insert roadmap_entries slug={}", entry.slug))?;

        roadmap_pk_by_v1id.insert(entry.id.clone(), rid);
        stats.roadmap_entries += 1;
    }

    for dep in &v1.roadmap_deps {
        sqlx::query(
            "insert into workflow.roadmap_deps (project_id, slug, depends_on)
             values ($1, $2, $3)
             on conflict do nothing",
        )
        .bind(project_id)
        .bind(&dep.slug)
        .bind(&dep.depends_on)
        .execute(&mut **tx)
        .await?;
        stats.roadmap_deps += 1;
    }

    // v1 roadmap.id (uuid string) → v2 todos.id (bigserial).
    let mut todo_pk_by_v1id: BTreeMap<String, i64> = BTreeMap::new();

    for ts in &v1.todo_state {
        // Reviewer Critical-2: an orphan row (no matching roadmap entry) is
        // corrupt v1 data — fail loudly rather than silently dropping it.
        let Some(&roadmap_pk) = roadmap_pk_by_v1id.get(&ts.v1_id) else {
            anyhow::bail!(
                "todo {slug}: orphan v1 todo_state (no matching roadmap entry id {id:?}); refusing migration",
                slug = ts.slug,
                id = ts.v1_id,
            );
        };
        let promoted = promote_state(&ts.state_json, &ts.slug)?;

        let after_for_slug: Vec<&str> = deps_by_slug
            .get(ts.slug.as_str())
            .cloned()
            .unwrap_or_default();
        let after_json: Value = serde_json::to_value(&after_for_slug)?;

        let roadmap_entry = v1.roadmap.iter().find(|r| r.id == ts.v1_id);
        let description = roadmap_entry.and_then(|r| r.description.clone());
        let group_slug = roadmap_entry.and_then(|r| r.group_slug.clone());
        let delivered_at = roadmap_entry.and_then(|r| r.delivered_at);

        let pk: i64 = sqlx::query_scalar(
            "insert into workflow.todos
                (project_id, roadmap_entry_id, slug, kind, lifecycle_phase,
                 integration_phase, finalize_status, group_slug, description,
                 after, state_extra, created_at, updated_at, delivered_at)
             values ($1, $2, $3, $4::workflow.todo_kind,
                     $5::workflow.lifecycle_phase, $6, $7, $8, $9,
                     $10::jsonb, $11::jsonb, $12, $13, $14)
             returning id",
        )
        .bind(project_id)
        .bind(roadmap_pk)
        .bind(&ts.slug)
        .bind(&promoted.kind)
        .bind(&promoted.lifecycle_phase)
        .bind(promoted.integration_phase.as_deref())
        .bind(promoted.finalize_status.as_deref())
        .bind(group_slug.as_deref())
        .bind(description.as_deref())
        .bind(&after_json)
        .bind(&promoted.state_extra)
        .bind(ts.created_at)
        .bind(ts.updated_at)
        .bind(delivered_at)
        .fetch_one(&mut **tx)
        .await
        .with_context(|| format!("insert todos slug={}", ts.slug))?;

        todo_pk_by_v1id.insert(ts.v1_id.clone(), pk);
        stats.todos += 1;
    }

    for art in &v1.artifacts {
        let Some(&todo_pk) = todo_pk_by_v1id.get(&art.v1_id) else {
            anyhow::bail!(
                "artifact slug={slug} name={name}: orphan (no matching todo for v1 id {id:?}); refusing migration",
                slug = art.slug,
                name = art.name,
                id = art.v1_id,
            );
        };
        if !ARTIFACT_NAMES.contains(&art.name.as_str()) {
            anyhow::bail!(
                "artifact slug={slug} name={name}: unknown v2 artifact name; refusing migration. Allowed: {allowed:?}",
                slug = art.slug,
                name = art.name,
                allowed = ARTIFACT_NAMES,
            );
        }
        let when = art.updated_at.unwrap_or_else(Utc::now);
        sqlx::query(
            "insert into workflow.artifacts
                (todo_id, name, content, digest, updated_by, created_at, updated_at)
             values ($1, $2::workflow.artifact_name, $3, $4, $5, $6, $7)",
        )
        .bind(todo_pk)
        .bind(&art.name)
        .bind(&art.content)
        .bind(&art.digest)
        .bind(art.updated_by.as_deref())
        .bind(when)
        .bind(when)
        .execute(&mut **tx)
        .await
        .with_context(|| format!("insert artifact slug={} name={}", art.slug, art.name))?;
        stats.artifacts += 1;
    }

    for ver in &v1.artifact_versions {
        let Some(&todo_pk) = todo_pk_by_v1id.get(&ver.v1_id) else {
            anyhow::bail!(
                "artifact_version slug={slug} name={name}: orphan (no matching todo for v1 id {id:?}); refusing migration",
                slug = ver.slug,
                name = ver.name,
                id = ver.v1_id,
            );
        };
        if !ARTIFACT_NAMES.contains(&ver.name.as_str()) {
            anyhow::bail!(
                "artifact_version slug={slug} name={name}: unknown v2 artifact name; refusing migration. Allowed: {allowed:?}",
                slug = ver.slug,
                name = ver.name,
                allowed = ARTIFACT_NAMES,
            );
        }
        sqlx::query(
            "insert into workflow.artifact_versions
                (todo_id, name, content, digest, updated_by, created_at)
             values ($1, $2::workflow.artifact_name, $3, $4, $5, $6)",
        )
        .bind(todo_pk)
        .bind(&ver.name)
        .bind(&ver.content)
        .bind(&ver.digest)
        .bind(ver.updated_by.as_deref())
        .bind(ver.created_at)
        .execute(&mut **tx)
        .await?;
        stats.artifact_versions += 1;
    }

    Ok(stats)
}

// ---------------------------------------------------------------------------
// State JSON promotion
// ---------------------------------------------------------------------------

/// Fields lifted out of the v1 state JSON blob into typed v2 columns.
/// Anything we did not lift survives in `state_extra` so the migration
/// is lossless.
#[derive(Debug)]
struct Promoted {
    kind: String,
    lifecycle_phase: String,
    integration_phase: Option<String>,
    finalize_status: Option<String>,
    state_extra: Value,
}

fn promote_state(state: &Value, slug: &str) -> Result<Promoted> {
    let mut remaining: Map<String, Value> = state.as_object().cloned().unwrap_or_default();

    // Reviewer Critical-2: unknown enum values are *bad data*, not a default
    // case. Missing values (v1 row predates the column) still fall back to a
    // sensible default; an *unknown* string aborts the migration so the
    // operator notices and fixes the source.
    let kind = match remaining
        .remove("kind")
        .and_then(|v| v.as_str().map(str::to_owned))
    {
        Some(raw) if TODO_KINDS.contains(&raw.as_str()) => raw,
        Some(raw) => {
            anyhow::bail!(
                "todo {slug}: unknown v1 kind {raw:?}; refusing migration. Fix the source row \
                 (allowed: {TODO_KINDS:?}) and re-run."
            )
        }
        None => "feature".to_owned(),
    };

    let lifecycle_phase = match remaining
        .remove("lifecycle_phase")
        .and_then(|v| v.as_str().map(str::to_owned))
    {
        Some(raw) => match normalize_lifecycle_phase(&raw) {
            Some(normalized) => normalized,
            None => anyhow::bail!(
                "todo {slug}: unknown v1 lifecycle_phase {raw:?}; refusing migration. Allowed: {LIFECYCLE_PHASES:?}",
            ),
        },
        None => "draft".to_owned(),
    };

    let integration_phase = remaining
        .remove("integration_phase")
        .and_then(|v| v.as_str().map(str::to_owned));

    // v1 stored finalize state either as a top-level `finalize_status`
    // string or nested as `finalize.status`. Accept both; top-level wins.
    let finalize_status = remaining
        .remove("finalize_status")
        .and_then(|v| v.as_str().map(str::to_owned))
        .or_else(|| {
            remaining
                .get("finalize")
                .and_then(Value::as_object)
                .and_then(|m| m.get("status"))
                .and_then(Value::as_str)
                .map(str::to_owned)
        });

    // Drop fields that are redundant with v2's relational shape so they
    // do not pollute state_extra.
    remaining.remove("after");
    remaining.remove("slug");

    Ok(Promoted {
        kind,
        lifecycle_phase,
        integration_phase,
        finalize_status,
        state_extra: Value::Object(remaining),
    })
}

// ---------------------------------------------------------------------------
// Unit tests — pure logic only. Integration tests live under
// `tests/migrate_workflow_v1.rs` and require Postgres.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn promote_state_defaults_kind_and_phase_when_missing() {
        let promoted = promote_state(&json!({}), "test-slug").expect("missing fields default");
        assert_eq!(promoted.kind, "feature");
        assert_eq!(promoted.lifecycle_phase, "draft");
        assert!(promoted.integration_phase.is_none());
        assert!(promoted.finalize_status.is_none());
    }

    #[test]
    fn promote_state_errors_on_unknown_kind() {
        // RV2 / Critical-2: an unknown enum value is dirty v1 data; the
        // strict-by-default migration aborts so the operator can fix the
        // source row instead of silently rewriting to `feature`.
        let err = promote_state(&json!({ "kind": "not-a-kind" }), "test-slug")
            .expect_err("unknown kind rejected");
        let message = format!("{err}");
        assert!(message.contains("unknown v1 kind"));
        assert!(message.contains("not-a-kind"));
    }

    #[test]
    fn promote_state_errors_on_unknown_lifecycle_phase() {
        let err = promote_state(&json!({ "lifecycle_phase": "not-a-phase" }), "test-slug")
            .expect_err("unknown phase rejected");
        let message = format!("{err}");
        assert!(message.contains("unknown v1 lifecycle_phase"));
        assert!(message.contains("not-a-phase"));
    }

    #[test]
    fn promote_state_normalizes_legacy_downstream_human_phase() {
        let promoted = promote_state(
            &json!({ "lifecycle_phase": "architecture_human_approval" }),
            "test-slug",
        )
        .expect("legacy phase normalized");
        assert_eq!(promoted.lifecycle_phase, "architecture_review");
    }

    #[test]
    fn promote_state_lifts_known_fields_and_keeps_rest() {
        let promoted = promote_state(
            &json!({
                "kind": "bug",
                "lifecycle_phase": "review_approved",
                "integration_phase": "lease_held",
                "finalize_status": "ready",
                "extra": "preserved",
                "after": ["x"],
                "slug": "ignored",
            }),
            "test-slug",
        )
        .expect("promote known fields");
        assert_eq!(promoted.kind, "bug");
        assert_eq!(promoted.lifecycle_phase, "review_approved");
        assert_eq!(promoted.integration_phase.as_deref(), Some("lease_held"));
        assert_eq!(promoted.finalize_status.as_deref(), Some("ready"));
        let extras = promoted.state_extra.as_object().expect("object");
        assert_eq!(
            extras.get("extra").and_then(Value::as_str),
            Some("preserved")
        );
        assert!(!extras.contains_key("kind"));
        assert!(!extras.contains_key("after"));
        assert!(!extras.contains_key("slug"));
    }

    #[test]
    fn promote_state_reads_nested_finalize_status() {
        let promoted = promote_state(
            &json!({ "finalize": { "status": "handed_off" } }),
            "test-slug",
        )
        .expect("nested finalize");
        assert_eq!(promoted.finalize_status.as_deref(), Some("handed_off"));
    }

    #[test]
    fn derive_project_root_strips_teleclaude_segment() {
        let path = PathBuf::from("/tmp/proj/.teleclaude/todos.db");
        let root = derive_project_root(&path).expect("derive ok");
        assert_eq!(root, PathBuf::from("/tmp/proj"));
    }

    #[test]
    fn derive_project_root_falls_back_to_parent() {
        let path = PathBuf::from("/tmp/proj/todos.db");
        let root = derive_project_root(&path).expect("derive ok");
        assert_eq!(root, PathBuf::from("/tmp/proj"));
    }

    #[test]
    fn parse_iso_accepts_rfc3339_with_offset() {
        let parsed = parse_iso("2024-01-15T10:30:00+00:00").expect("rfc3339");
        assert_eq!(parsed.to_rfc3339(), "2024-01-15T10:30:00+00:00");
    }

    #[test]
    fn parse_iso_accepts_naive_with_fractional() {
        let parsed = parse_iso("2024-01-15T10:30:00.123").expect("naive iso");
        assert_eq!(
            parsed.format("%Y-%m-%d %H:%M:%S%.3f").to_string(),
            "2024-01-15 10:30:00.123",
        );
    }

    #[test]
    fn sha256_hex_of_file_matches_known_value() {
        let tmp = tempfile::NamedTempFile::new().expect("temp file");
        std::fs::write(tmp.path(), b"hello").expect("write");
        let hex = sha256_hex_of_file(tmp.path()).expect("sha");
        // Pre-computed sha256("hello").
        assert_eq!(
            hex,
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        );
    }
}

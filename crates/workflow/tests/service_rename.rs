//! Integration tests for the typed todo rename contract.

mod common;

use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use common::{build_service, human_principal};
use shared::{ProjectId, Slug};
use sqlx::PgPool;
use workflow::{
    errors::WorkflowError,
    events::{TodoRenamed, CHANNEL_TODO_RENAMED},
    models::{CreationMode, TodoKind},
    service::CreateTodoArgs,
    WorkflowService,
};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");
const OLD_SLUG: &str = "rename-source";
const NEW_SLUG: &str = "rename-target";
const DEPENDENT_SLUG: &str = "rename-dependent";

async fn seed_project_at(svc: &WorkflowService, project_root: &Path) -> ProjectId {
    let name = format!("rename-{}", uuid::Uuid::new_v4());
    svc.find_or_create_project(&name, project_root.to_str().expect("utf-8 temp path"))
        .await
        .expect("project upsert succeeds")
}

fn temp_project_root() -> PathBuf {
    let root = std::env::temp_dir().join(format!("workflow-rename-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(root.join("docs/project/spec")).expect("create temp docs");
    fs::create_dir_all(root.join(".teleclaude")).expect("create temp teleclaude state");
    fs::write(root.join(".teleclaude/teleclaude.db"), "").expect("create empty daemon db");
    root
}

async fn create_todo(svc: &WorkflowService, project: ProjectId, slug: &Slug, after: Vec<Slug>) {
    svc.create_todo(
        CreateTodoArgs {
            project,
            slug: slug.clone(),
            kind: TodoKind::Feature,
            description: None,
            after,
            group: None,
            input_content: common::test_input(),
            creation_mode: CreationMode::Pickup,
        },
        &human_principal(),
    )
    .await
    .expect("seed todo");
}

async fn dependency_slugs(pool: &PgPool, slug: &Slug) -> Vec<String> {
    sqlx::query_scalar(
        "select depends_on
         from workflow.roadmap_deps
         where slug = $1
         order by depends_on asc",
    )
    .bind(slug.as_str())
    .fetch_all(pool)
    .await
    .expect("read dependency slugs")
}

fn create_daemon_db(project_root: &Path) -> rusqlite::Connection {
    let db_path = project_root.join(".teleclaude/teleclaude.db");
    let conn = rusqlite::Connection::open(db_path).expect("open daemon db");
    conn.execute_batch(
        "create table operations (
           operation_id text primary key,
           cwd text,
           slug text,
           state text,
           created_at text,
           updated_at text
         );
         create table sessions (
           session_id text primary key,
           project_path text,
           subdir text,
           working_slug text,
           closed_at text,
           lifecycle_status text
         );",
    )
    .expect("create daemon tables");
    conn
}

fn run_git(project_root: &Path, args: &[&str]) {
    let output = Command::new("/usr/bin/git")
        .arg("-C")
        .arg(project_root)
        .args(args)
        .output()
        .expect("run git");
    assert!(
        output.status.success(),
        "git {:?} failed: {}",
        args,
        String::from_utf8_lossy(&output.stderr)
    );
}

fn write_git_identity(project_root: &Path) {
    run_git(
        project_root,
        &["config", "user.email", "workflow-test@example.com"],
    );
    run_git(project_root, &["config", "user.name", "Workflow Test"]);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_collision_refuses(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    let new_slug = Slug::new(NEW_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    create_todo(&svc, project, &new_slug, vec![]).await;

    let err = svc
        .rename_todo(project, &old_slug, new_slug.clone(), &human_principal())
        .await
        .expect_err("collision refuses rename");

    assert!(matches!(
        err,
        WorkflowError::TodoRenameCollision { slug } if slug == new_slug
    ));
    svc.get_todo(project, &old_slug)
        .await
        .expect("old slug still resolves");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_delivered_refuses(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    sqlx::query(
        "update workflow.roadmap_entries
         set status = 'delivered'::workflow.roadmap_status
         where project_id = $1 and slug = $2",
    )
    .bind(project)
    .bind(old_slug.as_str())
    .execute(svc.pool())
    .await
    .expect("mark delivered");

    let err = svc
        .rename_todo(
            project,
            &old_slug,
            Slug::new(NEW_SLUG).expect("slug"),
            &human_principal(),
        )
        .await
        .expect_err("delivered rename refuses");

    assert!(matches!(
        err,
        WorkflowError::TodoRenameDelivered { slug } if slug == old_slug
    ));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_rewrites_all_covered_references_atomically(pool: PgPool) {
    let (svc, sink) = build_service(pool.clone());
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    let new_slug = Slug::new(NEW_SLUG).expect("slug");
    let dependent_slug = Slug::new(DEPENDENT_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    create_todo(&svc, project, &dependent_slug, vec![old_slug.clone()]).await;
    let snippet_path = project_root.join("docs/project/spec/rename.md");
    fs::write(
        &snippet_path,
        format!(
            "---\nstatus: target\ndelivered_by:\n  - {}\n---\n# Rename spec\n",
            old_slug.as_str()
        ),
    )
    .expect("write snippet");
    sink.take();

    let outcome = svc
        .rename_todo(project, &old_slug, new_slug.clone(), &human_principal())
        .await
        .expect("rename succeeds");

    assert_eq!(outcome.old_slug, old_slug);
    assert_eq!(outcome.new_slug, new_slug);
    assert_eq!(outcome.rewritten_reference_count, 1);
    assert!(matches!(
        svc.get_todo(project, &Slug::new(OLD_SLUG).expect("slug"))
            .await,
        Err(WorkflowError::TodoNotFound(_))
    ));
    let renamed = svc
        .get_todo(project, &Slug::new(NEW_SLUG).expect("slug"))
        .await
        .expect("new slug resolves");
    assert_eq!(renamed.slug.as_str(), NEW_SLUG);
    let dependent = svc
        .get_todo(project, &dependent_slug)
        .await
        .expect("dependent resolves");
    assert_eq!(dependent.after, vec![Slug::new(NEW_SLUG).expect("slug")]);
    assert_eq!(
        dependency_slugs(&pool, &dependent_slug).await,
        vec![NEW_SLUG]
    );

    let snippet = fs::read_to_string(snippet_path).expect("read snippet");
    assert!(snippet.contains(NEW_SLUG));
    assert!(!snippet.contains(OLD_SLUG));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_moves_local_worktree_branch_and_workspace(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    let new_slug = Slug::new(NEW_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;

    run_git(&project_root, &["init"]);
    write_git_identity(&project_root);
    fs::write(project_root.join("README.md"), "seed\n").expect("seed file");
    run_git(&project_root, &["add", "README.md"]);
    run_git(&project_root, &["commit", "-m", "seed"]);
    run_git(&project_root, &["branch", old_slug.as_str()]);
    run_git(
        &project_root,
        &["worktree", "add", "trees/rename-source", old_slug.as_str()],
    );
    fs::create_dir_all(project_root.join("workspace").join(old_slug.as_str()))
        .expect("create workspace");
    fs::write(
        project_root
            .join("workspace")
            .join(old_slug.as_str())
            .join("note.txt"),
        "workspace",
    )
    .expect("write workspace");

    svc.rename_todo(project, &old_slug, new_slug.clone(), &human_principal())
        .await
        .expect("rename succeeds");

    assert!(!project_root.join("trees").join(old_slug.as_str()).exists());
    assert!(project_root.join("trees").join(new_slug.as_str()).exists());
    assert!(!project_root
        .join("workspace")
        .join(old_slug.as_str())
        .exists());
    assert!(project_root
        .join("workspace")
        .join(new_slug.as_str())
        .join("note.txt")
        .exists());
    run_git(&project_root, &["rev-parse", "--verify", new_slug.as_str()]);
    let old_branch = Command::new("/usr/bin/git")
        .arg("-C")
        .arg(&project_root)
        .args(["rev-parse", "--verify", old_slug.as_str()])
        .output()
        .expect("query old branch");
    assert!(!old_branch.status.success());
    let branch_output = Command::new("/usr/bin/git")
        .arg("-C")
        .arg(project_root.join("trees").join(new_slug.as_str()))
        .args(["branch", "--show-current"])
        .output()
        .expect("read worktree branch");
    assert!(branch_output.status.success());
    assert_eq!(
        String::from_utf8_lossy(&branch_output.stdout).trim(),
        new_slug.as_str()
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_refuses_when_non_terminal_session_bound(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    let conn = create_daemon_db(&project_root);
    conn.execute(
        "insert into sessions
         (session_id, project_path, subdir, working_slug, closed_at, lifecycle_status)
         values (?1, ?2, ?3, ?4, null, 'active')",
        rusqlite::params![
            "session-bound",
            project_root.to_string_lossy().as_ref(),
            format!("trees/{OLD_SLUG}"),
            OLD_SLUG,
        ],
    )
    .expect("insert open session");

    let err = svc
        .rename_todo(
            project,
            &old_slug,
            Slug::new(NEW_SLUG).expect("slug"),
            &human_principal(),
        )
        .await
        .expect_err("open session refuses rename");

    assert!(matches!(
        err,
        WorkflowError::TodoRenameSessionBound { slug, session_id }
            if slug == old_slug && session_id == "session-bound"
    ));
    svc.get_todo(project, &old_slug)
        .await
        .expect("old slug still resolves");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_refuses_when_non_terminal_operation_bound(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    let conn = create_daemon_db(&project_root);
    conn.execute(
        "insert into operations
         (operation_id, cwd, slug, state, created_at, updated_at)
         values (?1, ?2, ?3, 'running', 'now', 'now')",
        rusqlite::params![
            "operation-bound",
            project_root.to_string_lossy().as_ref(),
            OLD_SLUG,
        ],
    )
    .expect("insert running operation");

    let err = svc
        .rename_todo(
            project,
            &old_slug,
            Slug::new(NEW_SLUG).expect("slug"),
            &human_principal(),
        )
        .await
        .expect_err("running operation refuses rename");

    assert!(matches!(
        err,
        WorkflowError::TodoRenameOperationBound { slug, operation_id }
            if slug == old_slug && operation_id == "operation-bound"
    ));
    svc.get_todo(project, &old_slug)
        .await
        .expect("old slug still resolves");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_rewrites_terminal_daemon_operation_refs_post_commit(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    let new_slug = Slug::new(NEW_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    let conn = create_daemon_db(&project_root);
    conn.execute(
        "insert into operations
         (operation_id, cwd, slug, state, created_at, updated_at)
         values (?1, ?2, ?3, 'completed', 'now', 'now')",
        rusqlite::params![
            "operation-terminal",
            project_root.to_string_lossy().as_ref(),
            OLD_SLUG,
        ],
    )
    .expect("insert terminal operation");

    svc.rename_todo(project, &old_slug, new_slug.clone(), &human_principal())
        .await
        .expect("rename succeeds");

    let slug: String = conn
        .query_row(
            "select slug from operations where operation_id = ?1",
            ["operation-terminal"],
            |row| row.get(0),
        )
        .expect("read operation slug");
    assert_eq!(slug, new_slug.as_str());
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_rewrites_delivered_by_exact_slug_only(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new("feature-x").expect("slug");
    let new_slug = Slug::new("feature-z").expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    let snippet_path = project_root.join("docs/project/spec/exact.md");
    fs::write(
        &snippet_path,
        "---\nstatus: target\ndelivered_by:\n  - feature-x\n  - feature-x-2\n---\n# Exact\n",
    )
    .expect("write snippet");

    svc.rename_todo(project, &old_slug, new_slug.clone(), &human_principal())
        .await
        .expect("rename succeeds");

    let snippet = fs::read_to_string(snippet_path).expect("read snippet");
    assert!(snippet.contains("feature-z"));
    assert!(snippet.contains("feature-x-2"));
    assert!(!snippet.contains("feature-z-2"));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_snippet_write_failure_restores_prior_writes(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    let first_path = project_root.join("docs/project/spec/a-first.md");
    let second_path = project_root.join("docs/project/spec/b-second.md");
    let first_original = format!(
        "---\nstatus: target\ndelivered_by:\n  - {}\n---\n# First\n",
        old_slug.as_str()
    );
    let second_original = format!(
        "---\nstatus: target\ndelivered_by:\n  - {}\n---\n# Second\n",
        old_slug.as_str()
    );
    fs::write(&first_path, &first_original).expect("write first snippet");
    fs::write(&second_path, &second_original).expect("write second snippet");
    let mut permissions = fs::metadata(&second_path)
        .expect("second metadata")
        .permissions();
    permissions.set_mode(0o444);
    fs::set_permissions(&second_path, permissions).expect("make second readonly");

    let result = svc
        .rename_todo(
            project,
            &old_slug,
            Slug::new(NEW_SLUG).expect("slug"),
            &human_principal(),
        )
        .await;

    let mut permissions = fs::metadata(&second_path)
        .expect("second metadata after failure")
        .permissions();
    permissions.set_mode(0o644);
    fs::set_permissions(&second_path, permissions).expect("restore second writable");
    assert!(result.is_err());
    assert_eq!(
        fs::read_to_string(first_path).expect("read first snippet"),
        first_original
    );
    assert_eq!(
        fs::read_to_string(second_path).expect("read second snippet"),
        second_original
    );
    svc.get_todo(project, &old_slug)
        .await
        .expect("old slug still resolves");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_mid_transaction_failure_restores_snippets_and_surfaces(pool: PgPool) {
    let (svc, _sink) = build_service(pool.clone());
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    let new_slug = Slug::new(NEW_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    fs::create_dir_all(project_root.join("trees").join(old_slug.as_str()))
        .expect("create worktree surface");
    fs::create_dir_all(project_root.join("workspace").join(old_slug.as_str()))
        .expect("create workspace surface");
    let snippet_path = project_root.join("docs/project/spec/rollback.md");
    let original = format!(
        "---\nstatus: target\ndelivered_by:\n  - {}\n---\n# Rollback\n",
        old_slug.as_str()
    );
    fs::write(&snippet_path, &original).expect("write snippet");
    sqlx::query(
        "create or replace function workflow.reject_rename_target()
         returns trigger language plpgsql as $$
         begin
           if new.slug = 'rename-target' then
             raise exception 'reject rename target';
           end if;
           return new;
         end;
         $$;
        ",
    )
    .execute(&pool)
    .await
    .expect("install failure function");
    sqlx::query(
        "create trigger reject_rename_target
         before update on workflow.roadmap_entries
         for each row execute function workflow.reject_rename_target();",
    )
    .execute(&pool)
    .await
    .expect("install failure trigger");

    let result = svc
        .rename_todo(project, &old_slug, new_slug.clone(), &human_principal())
        .await;

    assert!(result.is_err());
    svc.get_todo(project, &old_slug)
        .await
        .expect("old slug still resolves");
    assert!(matches!(
        svc.get_todo(project, &new_slug).await,
        Err(WorkflowError::TodoNotFound(_))
    ));
    assert_eq!(
        fs::read_to_string(snippet_path).expect("read snippet"),
        original
    );
    assert!(project_root.join("trees").join(old_slug.as_str()).exists());
    assert!(!project_root.join("trees").join(new_slug.as_str()).exists());
    assert!(project_root
        .join("workspace")
        .join(old_slug.as_str())
        .exists());
    assert!(!project_root
        .join("workspace")
        .join(new_slug.as_str())
        .exists());
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_unsafe_reference_refusal_preserves_state(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    let snippet_path = project_root.join("docs/project/spec/unsafe.md");
    let original = format!(
        "---\nstatus: target\ndelivered_by: [{}]\n---\nBody names {} directly.\n",
        old_slug.as_str(),
        old_slug.as_str()
    );
    fs::write(&snippet_path, &original).expect("write snippet");

    let err = svc
        .rename_todo(
            project,
            &old_slug,
            Slug::new(NEW_SLUG).expect("slug"),
            &human_principal(),
        )
        .await
        .expect_err("unsafe body reference refuses rename");

    assert!(matches!(
        err,
        WorkflowError::TodoRenameUnsafeReference { slug, .. } if slug == old_slug
    ));
    svc.get_todo(project, &old_slug)
        .await
        .expect("old slug still resolves");
    assert!(matches!(
        svc.get_todo(project, &Slug::new(NEW_SLUG).expect("slug"))
            .await,
        Err(WorkflowError::TodoNotFound(_))
    ));
    assert_eq!(
        fs::read_to_string(snippet_path).expect("read snippet"),
        original
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn rename_emits_full_8_field_payload(pool: PgPool) {
    let (svc, sink): (WorkflowService, Arc<common::VecSink>) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let old_slug = Slug::new(OLD_SLUG).expect("slug");
    let new_slug = Slug::new(NEW_SLUG).expect("slug");
    create_todo(&svc, project, &old_slug, vec![]).await;
    sink.take();

    let outcome = svc
        .rename_todo(project, &old_slug, new_slug.clone(), &human_principal())
        .await
        .expect("rename succeeds");

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_TODO_RENAMED);
    let payload: TodoRenamed =
        serde_json::from_value(envelopes[0].payload.clone()).expect("payload decodes");
    assert_eq!(payload.todo_id, outcome.todo_id);
    assert_eq!(payload.old_slug, old_slug);
    assert_eq!(payload.new_slug, new_slug);
    assert_eq!(payload.project_id, project);
    assert_eq!(payload.project_path, project_root.to_string_lossy());
    assert_eq!(payload.renamed_by_principal, common::HUMAN_PRINCIPAL_EMAIL);
    assert_eq!(payload.rewritten_reference_count, 0);
}

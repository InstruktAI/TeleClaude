//! Integration tests for todo-scoped refinement diffs.

mod common;

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use common::{build_service, human_principal};
use serde_json::json;
use shared::{ProjectId, Slug};
use sqlx::PgPool;
use workflow::{
    models::{ArtifactName, CreationMode, TodoKind},
    service::CreateTodoArgs,
    WorkflowService,
};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");
const DIFF_SLUG: &str = "diff-target";

async fn seed_project_at(svc: &WorkflowService, project_root: &Path) -> ProjectId {
    let name = format!("diff-{}", uuid::Uuid::new_v4());
    svc.find_or_create_project(&name, project_root.to_str().expect("utf-8 temp path"))
        .await
        .expect("project upsert succeeds")
}

fn temp_project_root() -> PathBuf {
    let root = std::env::temp_dir().join(format!("workflow-diff-{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(root.join("docs/project/spec")).expect("create temp docs");
    root
}

fn git_bin() -> &'static str {
    if Path::new("/usr/bin/git").exists() {
        "/usr/bin/git"
    } else {
        "git"
    }
}

fn run_git(root: &Path, args: &[&str]) -> String {
    let output = Command::new(git_bin())
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .expect("git command runs");
    assert!(
        output.status.success(),
        "git {:?} failed: {}",
        args,
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8_lossy(&output.stdout).trim().to_owned()
}

fn init_repo(root: &Path) {
    Command::new(git_bin())
        .arg("-C")
        .arg(root)
        .args(["init", "-b", "main"])
        .output()
        .expect("git init runs");
    run_git(root, &["config", "user.email", "test@example.com"]);
    run_git(root, &["config", "user.name", "Workflow Test"]);
}

fn commit_all(root: &Path, message: &str) -> String {
    run_git(root, &["add", "docs"]);
    run_git(root, &["commit", "--no-gpg-sign", "-m", message]);
    run_git(root, &["rev-parse", "HEAD"])
}

async fn create_todo(svc: &WorkflowService, project: ProjectId, slug: &Slug) {
    svc.create_todo(
        CreateTodoArgs {
            project,
            slug: slug.clone(),
            kind: TodoKind::Feature,
            description: None,
            after: vec![],
            group: None,
            input_content: common::test_input(),
            creation_mode: CreationMode::Pickup,
        },
        &human_principal(),
    )
    .await
    .expect("seed todo");
}

async fn approve_requirements_digest(
    svc: &WorkflowService,
    project: ProjectId,
    slug: &Slug,
    digest: &str,
) {
    sqlx::query(
        "update workflow.todos
         set state_extra = $1::jsonb
         where project_id = $2 and slug = $3",
    )
    .bind(json!({"requirements_review": {"approved_digest": digest}}))
    .bind(project)
    .bind(slug.as_str())
    .execute(svc.pool())
    .await
    .expect("approve digest");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn diff_with_both_artifact_and_snippet_deltas(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    init_repo(&project_root);
    let project = seed_project_at(&svc, &project_root).await;
    let slug = Slug::new(DIFF_SLUG).expect("slug");
    create_todo(&svc, project, &slug).await;

    let baseline = svc
        .write_artifact(
            project,
            &slug,
            ArtifactName::Requirements,
            "old requirements\n".to_owned(),
            &human_principal(),
        )
        .await
        .expect("write baseline artifact");
    approve_requirements_digest(&svc, project, &slug, &baseline.digest).await;
    svc.write_artifact(
        project,
        &slug,
        ArtifactName::Requirements,
        "new requirements\n".to_owned(),
        &human_principal(),
    )
    .await
    .expect("write current artifact");

    let snippet_path = project_root.join("docs/project/spec/diff.md");
    fs::write(
        &snippet_path,
        "---\nstatus: target\ndelivered_by: [diff-target]\n---\nold snippet\n",
    )
    .expect("write snippet");
    let baseline_sha = commit_all(&project_root, "baseline snippet");
    fs::write(
        &snippet_path,
        "---\nstatus: target\ndelivered_by: [diff-target]\n---\nnew snippet\n",
    )
    .expect("modify snippet");
    sqlx::query(
        "insert into workflow.snippet_provenance
           (snippet_path, slug, head_sha_at_acquisition)
         values ($1, $2, $3)",
    )
    .bind("docs/project/spec/diff.md")
    .bind(slug.as_str())
    .bind(&baseline_sha)
    .execute(svc.pool())
    .await
    .expect("insert provenance");

    let diff = svc.todo_diff(project, &slug).await.expect("diff succeeds");

    assert!(diff.diagnostics.is_empty());
    assert!(diff
        .sections
        .iter()
        .any(|section| section.label == "requirements"));
    assert!(diff
        .sections
        .iter()
        .any(|section| section.label == "docs/project/spec/diff.md"));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn diff_baseline_absent_diagnostic(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    let project = seed_project_at(&svc, &project_root).await;
    let slug = Slug::new(DIFF_SLUG).expect("slug");
    create_todo(&svc, project, &slug).await;
    fs::write(
        project_root.join("docs/project/spec/missing.md"),
        "---\nstatus: target\ndelivered_by: [diff-target]\n---\ncontent\n",
    )
    .expect("write snippet");

    let diff = svc.todo_diff(project, &slug).await.expect("diff succeeds");

    assert!(diff
        .diagnostics
        .contains(&"baseline-absent: docs/project/spec/missing.md".to_owned()));
    assert!(diff.sections.is_empty());
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn diff_with_provenance_anchor_uses_recorded_sha(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    init_repo(&project_root);
    let project = seed_project_at(&svc, &project_root).await;
    let slug = Slug::new(DIFF_SLUG).expect("slug");
    create_todo(&svc, project, &slug).await;
    let snippet_path = project_root.join("docs/project/spec/provenance.md");
    fs::write(
        &snippet_path,
        "---\nstatus: target\ndelivered_by: [diff-target]\n---\nbaseline\n",
    )
    .expect("write snippet");
    let baseline_sha = commit_all(&project_root, "baseline provenance");
    fs::write(
        &snippet_path,
        "---\nstatus: target\ndelivered_by: [diff-target]\n---\ncurrent\n",
    )
    .expect("modify snippet");
    sqlx::query(
        "insert into workflow.snippet_provenance
           (snippet_path, slug, head_sha_at_acquisition)
         values ($1, $2, $3)",
    )
    .bind("docs/project/spec/provenance.md")
    .bind(slug.as_str())
    .bind(&baseline_sha)
    .execute(svc.pool())
    .await
    .expect("insert provenance");

    let diff = svc.todo_diff(project, &slug).await.expect("diff succeeds");

    let section = diff
        .sections
        .iter()
        .find(|section| section.label == "docs/project/spec/provenance.md")
        .expect("snippet section");
    assert_eq!(section.baseline, baseline_sha);
    assert!(section.prefix.is_none());
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn diff_legacy_snippet_falls_back_to_main_head(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_root = temp_project_root();
    init_repo(&project_root);
    let project = seed_project_at(&svc, &project_root).await;
    let slug = Slug::new(DIFF_SLUG).expect("slug");
    create_todo(&svc, project, &slug).await;
    let snippet_path = project_root.join("docs/project/spec/legacy.md");
    fs::write(
        &snippet_path,
        "---\nstatus: target\ndelivered_by: [diff-target]\n---\nmain version\n",
    )
    .expect("write snippet");
    commit_all(&project_root, "legacy baseline");
    fs::write(
        &snippet_path,
        "---\nstatus: target\ndelivered_by: [diff-target]\n---\nworking version\n",
    )
    .expect("modify snippet");

    let diff = svc.todo_diff(project, &slug).await.expect("diff succeeds");

    let section = diff
        .sections
        .iter()
        .find(|section| section.label == "docs/project/spec/legacy.md")
        .expect("snippet section");
    assert_eq!(section.baseline, "main");
    assert_eq!(section.prefix.as_deref(), Some("baseline-fallback: main"));
}

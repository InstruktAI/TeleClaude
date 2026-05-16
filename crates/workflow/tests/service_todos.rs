//! Integration tests for [`WorkflowService`] todo CRUD.
//!
//! Each test gets a fresh Postgres database via `sqlx::test`, with the
//! workflow migrations applied. The shared [`common::VecSink`] captures
//! emitted envelopes so assertions don't need a live Redis.

mod common;

use common::{build_service, human_principal, seed_project};
use shared::Slug;
use sqlx::PgPool;
use workflow::{
    errors::WorkflowError,
    events::{CHANNEL_ARTIFACT_WRITTEN, CHANNEL_TODO_CREATED},
    models::TodoKind,
    service::TodoPatch,
};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[sqlx::test(migrator = "MIGRATOR")]
async fn create_todo_inserts_row_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("alpha").expect("slug");

    let todo = svc
        .create_todo(
            project,
            slug.clone(),
            TodoKind::Feature,
            Some("first todo".to_owned()),
            vec![],
            None,
            common::test_input(),
            &human_principal(),
        )
        .await
        .expect("create_todo succeeds");

    assert_eq!(todo.slug, slug);
    assert_eq!(todo.project_id, project);
    assert_eq!(todo.kind, TodoKind::Feature);
    assert_eq!(todo.description.as_deref(), Some("first todo"));

    // RV2: create_todo emits TodoCreated then ArtifactWritten (for the
    // required `input` artifact). Two envelopes per creation, in order.
    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 2);
    assert_eq!(envelopes[0].channel, CHANNEL_TODO_CREATED);
    assert_eq!(envelopes[1].channel, CHANNEL_ARTIFACT_WRITTEN);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn create_todo_rejects_duplicate_slug_in_same_project(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("dup").expect("slug");
    let principal = human_principal();

    svc.create_todo(
        project,
        slug.clone(),
        TodoKind::Feature,
        None,
        vec![],
        None,
        common::test_input(),
        &principal,
    )
    .await
    .expect("first create succeeds");

    let err = svc
        .create_todo(
            project,
            slug.clone(),
            TodoKind::Bug,
            None,
            vec![],
            None,
            common::test_input(),
            &principal,
        )
        .await
        .expect_err("second create rejected");

    assert!(matches!(err, WorkflowError::DuplicateSlug(s) if s == slug));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn list_todos_returns_only_target_project_rows(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project_a = seed_project(&svc).await;
    let project_b = seed_project(&svc).await;
    let principal = human_principal();

    svc.create_todo(
        project_a,
        Slug::new("a-only").expect("slug"),
        TodoKind::Feature,
        None,
        vec![],
        None,
        common::test_input(),
        &principal,
    )
    .await
    .expect("seed project_a");

    svc.create_todo(
        project_b,
        Slug::new("b-only").expect("slug"),
        TodoKind::Feature,
        None,
        vec![],
        None,
        common::test_input(),
        &principal,
    )
    .await
    .expect("seed project_b");

    let only_b = svc
        .list_todos(project_b)
        .await
        .expect("list_todos succeeds");
    assert_eq!(only_b.len(), 1);
    assert_eq!(only_b[0].slug.as_str(), "b-only");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn get_todo_returns_todo_not_found_for_missing_slug(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("ghost").expect("slug");

    let err = svc
        .get_todo(project, &slug)
        .await
        .expect_err("missing slug is an error");

    assert!(matches!(err, WorkflowError::TodoNotFound(s) if s == slug));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_todo_mutates_description_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("to-update").expect("slug");
    let principal = human_principal();

    svc.create_todo(
        project,
        slug.clone(),
        TodoKind::Feature,
        Some("before".to_owned()),
        vec![],
        None,
        common::test_input(),
        &principal,
    )
    .await
    .expect("seed");
    sink.take(); // drop the create envelope

    let patch = TodoPatch {
        description: Some(Some("after".to_owned())),
        ..TodoPatch::default()
    };
    let updated = svc
        .update_todo(project, &slug, patch, &principal)
        .await
        .expect("update_todo succeeds");

    assert_eq!(updated.description.as_deref(), Some("after"));

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, "workflow.todo.updated");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_todo_returns_not_found_for_missing_slug(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("ghost").expect("slug");

    let err = svc
        .update_todo(project, &slug, TodoPatch::default(), &human_principal())
        .await
        .expect_err("missing slug rejected");

    assert!(matches!(err, WorkflowError::TodoNotFound(s) if s == slug));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn delete_todo_removes_row_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("to-delete").expect("slug");
    let principal = human_principal();

    svc.create_todo(
        project,
        slug.clone(),
        TodoKind::Feature,
        None,
        vec![],
        None,
        common::test_input(),
        &principal,
    )
    .await
    .expect("seed");
    sink.take();

    svc.delete_todo(project, &slug, &principal)
        .await
        .expect("delete_todo succeeds");

    let err = svc
        .get_todo(project, &slug)
        .await
        .expect_err("deleted slug is gone");
    assert!(matches!(err, WorkflowError::TodoNotFound(_)));

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, "workflow.todo.deleted");
}

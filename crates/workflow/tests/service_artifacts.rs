//! Integration tests for [`WorkflowService`] artifact operations.

mod common;

use common::{build_service, human_principal, seed_project};
use shared::Slug;
use sqlx::PgPool;
use workflow::{
    errors::WorkflowError,
    events::{CHANNEL_ARTIFACT_DELETED, CHANNEL_ARTIFACT_WRITTEN},
    models::{ArtifactName, CreationMode, TodoKind},
    service::CreateTodoArgs,
};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

async fn seed_todo(svc: &workflow::WorkflowService, project: shared::ProjectId, slug: &Slug) {
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

#[sqlx::test(migrator = "MIGRATOR")]
async fn write_artifact_inserts_initial_version_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("with-prd").expect("slug");
    seed_todo(&svc, project, &slug).await;
    sink.take();

    let principal = human_principal();
    let artifact = svc
        .write_artifact(
            project,
            &slug,
            ArtifactName::Prd,
            "# PRD\n\nfirst draft".to_owned(),
            &principal,
        )
        .await
        .expect("write_artifact succeeds");

    assert_eq!(artifact.name, ArtifactName::Prd);
    assert_eq!(artifact.content, "# PRD\n\nfirst draft");
    assert!(!artifact.digest.is_empty());

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_ARTIFACT_WRITTEN);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn write_artifact_twice_appends_to_version_history(pool: PgPool) {
    let (svc, _sink) = build_service(pool.clone());
    let project = seed_project(&svc).await;
    let slug = Slug::new("two-writes").expect("slug");
    seed_todo(&svc, project, &slug).await;
    let principal = human_principal();

    svc.write_artifact(
        project,
        &slug,
        ArtifactName::Prd,
        "v1".to_owned(),
        &principal,
    )
    .await
    .expect("first write");
    svc.write_artifact(
        project,
        &slug,
        ArtifactName::Prd,
        "v2".to_owned(),
        &principal,
    )
    .await
    .expect("second write");

    let count: i64 = sqlx::query_scalar(
        "select count(*)::bigint
         from workflow.artifact_versions v
         join workflow.todos t on t.id = v.todo_id
         where t.project_id = $1 and t.slug = $2 and v.name = 'prd'",
    )
    .bind(project)
    .bind(slug.as_str())
    .fetch_one(&pool)
    .await
    .expect("version count succeeds");
    assert_eq!(count, 2);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn read_artifact_returns_latest_content(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("readable").expect("slug");
    seed_todo(&svc, project, &slug).await;
    let principal = human_principal();

    svc.write_artifact(
        project,
        &slug,
        ArtifactName::Prd,
        "old".to_owned(),
        &principal,
    )
    .await
    .expect("first write");
    svc.write_artifact(
        project,
        &slug,
        ArtifactName::Prd,
        "new".to_owned(),
        &principal,
    )
    .await
    .expect("second write");

    let artifact = svc
        .read_artifact(project, &slug, ArtifactName::Prd)
        .await
        .expect("read succeeds");
    assert_eq!(artifact.content, "new");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn list_artifacts_returns_all_artifacts_for_the_todo(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("multi").expect("slug");
    seed_todo(&svc, project, &slug).await;
    let principal = human_principal();

    svc.write_artifact(project, &slug, ArtifactName::Prd, "p".into(), &principal)
        .await
        .expect("write prd");
    svc.write_artifact(
        project,
        &slug,
        ArtifactName::Architecture,
        "a".into(),
        &principal,
    )
    .await
    .expect("write architecture");

    let listing = svc
        .list_artifacts(project, &slug)
        .await
        .expect("list_artifacts succeeds");
    // RV2: every todo seeds an `input` artifact on creation, so the listing
    // is the two explicit writes above plus that one.
    assert_eq!(listing.len(), 3);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn remove_artifact_deletes_current_and_versions_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool.clone());
    let project = seed_project(&svc).await;
    let slug = Slug::new("removable").expect("slug");
    seed_todo(&svc, project, &slug).await;
    let principal = human_principal();

    svc.write_artifact(project, &slug, ArtifactName::Prd, "v1".into(), &principal)
        .await
        .expect("write v1");
    svc.write_artifact(project, &slug, ArtifactName::Prd, "v2".into(), &principal)
        .await
        .expect("write v2");
    sink.take();

    svc.remove_artifact(project, &slug, ArtifactName::Prd, &principal)
        .await
        .expect("remove succeeds");

    let count: i64 = sqlx::query_scalar(
        "select count(*)::bigint
         from workflow.artifact_versions v
         join workflow.todos t on t.id = v.todo_id
         where t.project_id = $1 and t.slug = $2 and v.name = 'prd'",
    )
    .bind(project)
    .bind(slug.as_str())
    .fetch_one(&pool)
    .await
    .expect("count succeeds");
    assert_eq!(count, 0);

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_ARTIFACT_DELETED);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn read_artifact_for_missing_name_returns_artifact_not_found(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let slug = Slug::new("empty").expect("slug");
    seed_todo(&svc, project, &slug).await;

    let err = svc
        .read_artifact(project, &slug, ArtifactName::Prd)
        .await
        .expect_err("missing artifact errors");

    assert!(matches!(
        err,
        WorkflowError::ArtifactNotFound { todo, name }
            if todo == slug && name == ArtifactName::Prd
    ));
}

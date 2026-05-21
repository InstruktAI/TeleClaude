//! Integration tests for the typed todo update contract.

mod common;

use std::sync::Arc;

use common::{build_service, human_principal, seed_project};
use shared::Slug;
use sqlx::PgPool;
use workflow::{
    errors::WorkflowError,
    events::{
        TodoUpdated, CHANNEL_TODO_UPDATED, TODO_UPDATE_CHANGE_DESCRIPTION, TODO_UPDATE_CHANGE_GROUP,
    },
    models::{ArtifactName, CreationMode, LifecyclePhase, TodoKind},
    service::{CreateTodoArgs, UpdateTodoArgs},
};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");
const UPDATED_DESCRIPTION: &str = "updated description";
const UPDATED_GROUP: &str = "updated-group";
const PLAN_CONTENT: &str = "## Implementation Plan\n\nBuild from this reviewed plan.\n";
const ROLLBACK_DESCRIPTION: &str = "rollback candidate";

async fn create_seed_todo(
    pool: &PgPool,
    slug: &Slug,
) -> (
    workflow::WorkflowService,
    Arc<common::VecSink>,
    shared::ProjectId,
) {
    let (svc, sink) = build_service(pool.clone());
    let project = seed_project(&svc).await;
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
    sink.take();
    (svc, sink, project)
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

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_metadata_atomic(pool: PgPool) {
    let slug = Slug::new("update-metadata").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;

    let updated = svc
        .update_todo(
            UpdateTodoArgs {
                project,
                slug: slug.clone(),
                description: Some(Some(UPDATED_DESCRIPTION.to_owned())),
                group: Some(Some(UPDATED_GROUP.to_owned())),
                ..UpdateTodoArgs::default()
            },
            &human_principal(),
        )
        .await
        .expect("update succeeds");

    assert_eq!(updated.description.as_deref(), Some(UPDATED_DESCRIPTION));
    assert_eq!(updated.group.as_deref(), Some(UPDATED_GROUP));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_dependency_replace_not_patch(pool: PgPool) {
    let slug = Slug::new("replace-deps").expect("slug");
    let old_dep = Slug::new("old-dep").expect("slug");
    let new_dep = Slug::new("new-dep").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;
    svc.patch_todo(
        project,
        &slug,
        workflow::TodoPatch {
            after: Some(vec![old_dep]),
            ..workflow::TodoPatch::default()
        },
        &human_principal(),
    )
    .await
    .expect("seed dependency");

    let updated = svc
        .update_todo(
            UpdateTodoArgs {
                project,
                slug: slug.clone(),
                after: Some(vec![new_dep.clone()]),
                ..UpdateTodoArgs::default()
            },
            &human_principal(),
        )
        .await
        .expect("replace dependencies");

    assert_eq!(updated.after, vec![new_dep]);
    assert_eq!(
        dependency_slugs(&pool, &slug).await,
        vec!["new-dep".to_owned()]
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_prepped_routes_to_implementation_plan(pool: PgPool) {
    let slug = Slug::new("prepped-plan").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;

    svc.update_todo(
        UpdateTodoArgs {
            project,
            slug: slug.clone(),
            content: Some(PLAN_CONTENT.to_owned()),
            prepped: true,
            ..UpdateTodoArgs::default()
        },
        &human_principal(),
    )
    .await
    .expect("prepped update succeeds");

    let artifact = svc
        .read_artifact(project, &slug, ArtifactName::ImplementationPlan)
        .await
        .expect("implementation-plan was written");
    assert_eq!(artifact.content, PLAN_CONTENT);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_writable_allowlist_refuses_retired_kinds(pool: PgPool) {
    let slug = Slug::new("retired-artifact").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;

    let err = svc
        .update_todo(
            UpdateTodoArgs {
                project,
                slug: slug.clone(),
                content: Some(PLAN_CONTENT.to_owned()),
                artifact: Some(ArtifactName::TestSpecs),
                ..UpdateTodoArgs::default()
            },
            &human_principal(),
        )
        .await
        .expect_err("retired artifact write is refused");

    assert!(matches!(
        err,
        WorkflowError::RetiredArtifactWrite {
            name: ArtifactName::TestSpecs
        }
    ));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_kind_phase_compatibility_refusal(pool: PgPool) {
    let slug = Slug::new("kind-phase").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;
    sqlx::query(
        "update workflow.todos
         set lifecycle_phase = 'build_started'::workflow.lifecycle_phase
         where project_id = $1 and slug = $2",
    )
    .bind(project)
    .bind(slug.as_str())
    .execute(&pool)
    .await
    .expect("set work phase");

    let err = svc
        .update_todo(
            UpdateTodoArgs {
                project,
                slug,
                kind: Some(TodoKind::Prepped),
                ..UpdateTodoArgs::default()
            },
            &human_principal(),
        )
        .await
        .expect_err("work-phase kind update is refused");

    assert!(matches!(err, WorkflowError::KindUpdatePhaseMismatch { .. }));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_cannot_move_lifecycle_phase(pool: PgPool) {
    let slug = Slug::new("phase-stable").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;

    let updated = svc
        .update_todo(
            UpdateTodoArgs {
                project,
                slug,
                kind: Some(TodoKind::Bug),
                ..UpdateTodoArgs::default()
            },
            &human_principal(),
        )
        .await
        .expect("kind update succeeds in prepare");

    assert_eq!(updated.lifecycle_phase, LifecyclePhase::PrdDrafting);
    assert_eq!(updated.kind, TodoKind::Bug);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_emits_change_summary_listing_mutated_fields(pool: PgPool) {
    let slug = Slug::new("summary-fields").expect("slug");
    let (svc, sink, project) = create_seed_todo(&pool, &slug).await;

    svc.update_todo(
        UpdateTodoArgs {
            project,
            slug,
            description: Some(Some(UPDATED_DESCRIPTION.to_owned())),
            group: Some(Some(UPDATED_GROUP.to_owned())),
            ..UpdateTodoArgs::default()
        },
        &human_principal(),
    )
    .await
    .expect("update succeeds");

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_TODO_UPDATED);
    let payload: TodoUpdated =
        serde_json::from_value(envelopes[0].payload.clone()).expect("payload decodes");
    assert_eq!(
        payload.change_summary,
        format!("{TODO_UPDATE_CHANGE_DESCRIPTION},{TODO_UPDATE_CHANGE_GROUP}")
    );
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_refuses_retired_artifact_without_writing(pool: PgPool) {
    let slug = Slug::new("retired-write-refusal").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;

    let err = svc
        .update_todo(
            UpdateTodoArgs {
                project,
                slug: slug.clone(),
                description: Some(Some(ROLLBACK_DESCRIPTION.to_owned())),
                content: Some(PLAN_CONTENT.to_owned()),
                artifact: Some(ArtifactName::SpecReviewFindings),
                ..UpdateTodoArgs::default()
            },
            &human_principal(),
        )
        .await
        .expect_err("retired artifact write is refused");
    assert!(matches!(err, WorkflowError::RetiredArtifactWrite { .. }));

    let todo = svc
        .get_todo(project, &slug)
        .await
        .expect("todo still exists");
    assert_eq!(todo.description, None);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn update_mid_transaction_failure_rolls_back(pool: PgPool) {
    let slug = Slug::new("rollback-update").expect("slug");
    let (svc, _sink, project) = create_seed_todo(&pool, &slug).await;
    sqlx::query(
        "create or replace function workflow.reject_rollback_group()
         returns trigger language plpgsql as $$
         begin
           if new.group_slug = 'updated-group' then
             raise exception 'reject rollback group';
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
        "create trigger reject_rollback_group
         before update on workflow.roadmap_entries
         for each row execute function workflow.reject_rollback_group();",
    )
    .execute(&pool)
    .await
    .expect("install failure trigger");

    let result = svc
        .update_todo(
            UpdateTodoArgs {
                project,
                slug: slug.clone(),
                description: Some(Some(ROLLBACK_DESCRIPTION.to_owned())),
                group: Some(Some(UPDATED_GROUP.to_owned())),
                ..UpdateTodoArgs::default()
            },
            &human_principal(),
        )
        .await;

    assert!(result.is_err());
    let todo = svc
        .get_todo(project, &slug)
        .await
        .expect("todo still exists");
    assert_eq!(todo.description, None);
    assert_eq!(todo.group, None);
}

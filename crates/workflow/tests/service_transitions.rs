//! Integration tests for [`WorkflowService::advance_phase`].

mod common;

use common::{build_service, human_principal, seed_project};
use shared::Slug;
use sqlx::PgPool;
use workflow::{
    errors::WorkflowError,
    events::CHANNEL_TODO_PHASE_ADVANCED,
    models::{CreationMode, LifecyclePhase, TodoKind},
    service::CreateTodoArgs,
    state_machine::LifecycleSignal,
};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

async fn seed_todo(svc: &workflow::WorkflowService, project: shared::ProjectId, slug: &Slug) {
    svc.create_todo(
        CreateTodoArgs {
            project,
            slug: slug.clone(),
            kind: Some(TodoKind::Feature),
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
async fn advance_phase_on_legal_signal_advances_and_records_transition(pool: PgPool) {
    let (svc, sink) = build_service(pool.clone());
    let project = seed_project(&svc).await;
    let slug = Slug::new("happy-path").expect("slug");
    seed_todo(&svc, project, &slug).await;
    let principal = human_principal();
    sink.take();

    // RV2: every new todo starts at PrdDrafting (the create call requires
    // and persists an input artifact). The next legal signal in the table
    // is PrdApproved → PrdHumanApproval.
    let todo = svc
        .advance_phase(project, &slug, LifecycleSignal::PrdApproved, &principal)
        .await
        .expect("advance_phase succeeds");

    assert_eq!(todo.lifecycle_phase, LifecyclePhase::PrdHumanApproval);

    let row_count: i64 = sqlx::query_scalar(
        "select count(*)::bigint
         from workflow.state_transitions s
         join workflow.todos t on t.id = s.todo_id
         where t.project_id = $1 and t.slug = $2",
    )
    .bind(project)
    .bind(slug.as_str())
    .fetch_one(&pool)
    .await
    .expect("count transitions");
    assert_eq!(row_count, 1);

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_TODO_PHASE_ADVANCED);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn advance_phase_on_illegal_signal_returns_invalid_transition(pool: PgPool) {
    let (svc, _sink) = build_service(pool.clone());
    let project = seed_project(&svc).await;
    let slug = Slug::new("stuck").expect("slug");
    seed_todo(&svc, project, &slug).await;
    let principal = human_principal();

    let err = svc
        .advance_phase(project, &slug, LifecycleSignal::ReviewApproved, &principal)
        .await
        .expect_err("illegal signal rejected");
    assert!(matches!(err, WorkflowError::InvalidTransition { .. }));

    // The row must not have advanced — it stays at the v2 initial phase.
    let todo = svc.get_todo(project, &slug).await.expect("read back todo");
    assert_eq!(todo.lifecycle_phase, LifecyclePhase::PrdDrafting);

    let row_count: i64 = sqlx::query_scalar(
        "select count(*)::bigint
         from workflow.state_transitions s
         join workflow.todos t on t.id = s.todo_id
         where t.project_id = $1 and t.slug = $2",
    )
    .bind(project)
    .bind(slug.as_str())
    .fetch_one(&pool)
    .await
    .expect("count transitions");
    assert_eq!(row_count, 0);
}

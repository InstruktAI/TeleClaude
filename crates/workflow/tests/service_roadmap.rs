//! Integration tests for [`WorkflowService`] roadmap operations.

mod common;

use common::{build_service, human_principal, seed_project};
use shared::Slug;
use sqlx::PgPool;
use workflow::{
    errors::WorkflowError,
    events::{
        CHANNEL_ROADMAP_ENTRY_ADDED, CHANNEL_ROADMAP_ENTRY_MOVED, CHANNEL_ROADMAP_ENTRY_REMOVED,
    },
    models::{CreationMode, TodoKind},
    service::CreateTodoArgs,
};

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[sqlx::test(migrator = "MIGRATOR")]
async fn add_roadmap_entry_appends_at_tail_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    let entry = svc
        .add_roadmap_entry(
            project,
            Slug::new("first").expect("slug"),
            None,
            vec![],
            None,
            Some("first entry".to_owned()),
            &principal,
        )
        .await
        .expect("add_roadmap_entry succeeds");

    assert_eq!(entry.position, 1);
    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_ROADMAP_ENTRY_ADDED);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn move_roadmap_entry_reorders_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    for slug in ["a", "b", "c", "d"] {
        svc.add_roadmap_entry(
            project,
            Slug::new(slug).expect("slug"),
            None,
            vec![],
            None,
            None,
            &principal,
        )
        .await
        .expect("seed entry");
    }
    sink.take();

    // Move `a` (position 1) to be just after `c` (position 3).
    let pivot = Slug::new("c").expect("slug");
    let moved = svc
        .move_roadmap_entry(
            project,
            &Slug::new("a").expect("slug"),
            None,
            Some(pivot),
            &principal,
        )
        .await
        .expect("move succeeds");

    assert_eq!(moved.position, 3);

    let listing = svc
        .list_roadmap(project, false, false)
        .await
        .expect("list_roadmap succeeds");
    let order: Vec<&str> = listing.iter().map(|e| e.slug.as_str()).collect();
    assert_eq!(order, vec!["b", "c", "a", "d"]);

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_ROADMAP_ENTRY_MOVED);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn freeze_roadmap_entry_hides_entry_from_default_listing(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    let slug = Slug::new("freezable").expect("slug");
    svc.add_roadmap_entry(project, slug.clone(), None, vec![], None, None, &principal)
        .await
        .expect("seed");

    let frozen = svc
        .freeze_roadmap_entry(project, &slug, &principal)
        .await
        .expect("freeze succeeds");
    assert!(frozen.frozen);

    let active = svc
        .list_roadmap(project, false, false)
        .await
        .expect("list active");
    assert!(
        active.is_empty(),
        "frozen entry must not appear in active list"
    );

    let with_icebox = svc
        .list_roadmap(project, true, false)
        .await
        .expect("list including icebox");
    assert_eq!(with_icebox.len(), 1);
    assert!(with_icebox[0].frozen);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn unfreeze_roadmap_entry_restores_active_status(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    let slug = Slug::new("revivable").expect("slug");
    svc.add_roadmap_entry(project, slug.clone(), None, vec![], None, None, &principal)
        .await
        .expect("seed");
    svc.freeze_roadmap_entry(project, &slug, &principal)
        .await
        .expect("freeze");

    let restored = svc
        .unfreeze_roadmap_entry(project, &slug, &principal)
        .await
        .expect("unfreeze succeeds");
    assert!(!restored.frozen);

    let active = svc
        .list_roadmap(project, false, false)
        .await
        .expect("list active");
    assert_eq!(active.len(), 1);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn remove_roadmap_entry_deletes_row_and_emits_event(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    let slug = Slug::new("removable").expect("slug");
    svc.add_roadmap_entry(project, slug.clone(), None, vec![], None, None, &principal)
        .await
        .expect("seed");
    sink.take();

    svc.remove_roadmap_entry(project, &slug, &principal)
        .await
        .expect("remove succeeds");

    let listing = svc
        .list_roadmap(project, true, true)
        .await
        .expect("list everything");
    assert!(listing.is_empty());

    let envelopes = sink.snapshot();
    assert_eq!(envelopes.len(), 1);
    assert_eq!(envelopes[0].channel, CHANNEL_ROADMAP_ENTRY_REMOVED);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn deliver_roadmap_entry_marks_delivered_with_commit_hash(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    // Use create_todo so the linked todo's delivered_at also flips.
    let slug = Slug::new("deliverable").expect("slug");
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
        &principal,
    )
    .await
    .expect("seed todo+entry");

    let delivered = svc
        .deliver_roadmap_entry(project, &slug, Some("deadbeef".to_owned()), &principal)
        .await
        .expect("deliver succeeds");

    assert!(delivered.delivered_at.is_some());
    assert_eq!(delivered.commit_hash.as_deref(), Some("deadbeef"));

    let todo = svc
        .get_todo(project, &slug)
        .await
        .expect("todo still readable");
    assert!(todo.delivered_at.is_some());
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn add_roadmap_entry_with_before_shifts_neighbors(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    for slug in ["one", "two", "three"] {
        svc.add_roadmap_entry(
            project,
            Slug::new(slug).expect("slug"),
            None,
            vec![],
            None,
            None,
            &principal,
        )
        .await
        .expect("seed entry");
    }

    let inserted = svc
        .add_roadmap_entry(
            project,
            Slug::new("inserted").expect("slug"),
            None,
            vec![],
            Some(Slug::new("two").expect("pivot")),
            None,
            &principal,
        )
        .await
        .expect("add before pivot");
    assert_eq!(inserted.position, 2);

    let listing = svc.list_roadmap(project, false, false).await.expect("list");
    let order: Vec<&str> = listing
        .iter()
        .map(|e| e.slug.as_str())
        .collect::<Vec<_>>()
        .clone()
        .into_iter()
        .collect();
    assert_eq!(order, vec!["one", "inserted", "two", "three"]);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn move_roadmap_entry_with_both_pivots_returns_arguments_error(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let project = seed_project(&svc).await;
    let principal = human_principal();

    let slug = Slug::new("alone").expect("slug");
    svc.add_roadmap_entry(project, slug.clone(), None, vec![], None, None, &principal)
        .await
        .expect("seed");

    let err = svc
        .move_roadmap_entry(
            project,
            &slug,
            Some(slug.clone()),
            Some(slug.clone()),
            &principal,
        )
        .await
        .expect_err("both pivots rejected");

    assert!(matches!(err, WorkflowError::RoadmapMoveArguments { .. }));
}

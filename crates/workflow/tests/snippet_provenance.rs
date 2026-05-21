//! Integration tests for snippet provenance storage.
//!
//! Provenance rows anchor doc-snippet diffs to the first commit at which a
//! delivery slug acquired a snippet's `delivered_by` membership.

use sqlx::PgPool;

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[sqlx::test(migrator = "MIGRATOR")]
async fn snippet_provenance_primary_key_preserves_first_anchor(pool: PgPool) {
    let inserted = sqlx::query(
        "insert into workflow.snippet_provenance
            (snippet_path, slug, head_sha_at_acquisition)
         values ($1, $2, $3)
         on conflict (snippet_path, slug) do nothing",
    )
    .bind("docs/project/spec/domain/workflow.md")
    .bind("delivery-a")
    .bind("aaaaaaaa")
    .execute(&pool)
    .await
    .expect("initial provenance insert succeeds");

    let ignored = sqlx::query(
        "insert into workflow.snippet_provenance
            (snippet_path, slug, head_sha_at_acquisition)
         values ($1, $2, $3)
         on conflict (snippet_path, slug) do nothing",
    )
    .bind("docs/project/spec/domain/workflow.md")
    .bind("delivery-a")
    .bind("bbbbbbbb")
    .execute(&pool)
    .await
    .expect("duplicate provenance insert is ignored");

    let rows: i64 = sqlx::query_scalar("select count(*) from workflow.snippet_provenance")
        .fetch_one(&pool)
        .await
        .expect("count provenance rows");
    let stored_sha: String =
        sqlx::query_scalar("select head_sha_at_acquisition from workflow.snippet_provenance")
            .fetch_one(&pool)
            .await
            .expect("read stored sha");

    assert_eq!(inserted.rows_affected(), 1);
    assert_eq!(ignored.rows_affected(), 0);
    assert_eq!(rows, 1);
    assert_eq!(stored_sha, "aaaaaaaa");
}

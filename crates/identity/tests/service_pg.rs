//! Integration tests for [`IdentityService`].
//!
//! Each test spins up a fresh Postgres via `sqlx::test`, applies the
//! identity migrator, and exercises the public service API. A `VecSink`
//! captures emitted events so assertions don't need a live Redis. A
//! `FailingSink` exercises the commit-then-emit loud-fail posture.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use identity::events::{PrincipalCreated, TokenIssued, TokenRevoked};
use identity::{
    errors::IdentityError, IdentityEventSink, IdentityService, Principal, PrincipalKind, Role,
};
use shared::SessionId;
use sqlx::PgPool;

const MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");

#[derive(Default)]
struct VecSink {
    principals: Mutex<Vec<PrincipalCreated>>,
    issued: Mutex<Vec<TokenIssued>>,
    revoked: Mutex<Vec<TokenRevoked>>,
}

#[async_trait]
impl IdentityEventSink for VecSink {
    async fn emit_principal_created(&self, event: PrincipalCreated) -> Result<(), IdentityError> {
        self.principals.lock().unwrap().push(event);
        Ok(())
    }
    async fn emit_token_issued(&self, event: TokenIssued) -> Result<(), IdentityError> {
        self.issued.lock().unwrap().push(event);
        Ok(())
    }
    async fn emit_token_revoked(&self, event: TokenRevoked) -> Result<(), IdentityError> {
        self.revoked.lock().unwrap().push(event);
        Ok(())
    }
}

struct FailingSink;

#[async_trait]
impl IdentityEventSink for FailingSink {
    async fn emit_principal_created(&self, _event: PrincipalCreated) -> Result<(), IdentityError> {
        Err(IdentityError::EmitFailed {
            message: "bus down".into(),
            state_committed: true,
        })
    }
    async fn emit_token_issued(&self, _e: TokenIssued) -> Result<(), IdentityError> {
        Err(IdentityError::EmitFailed {
            message: "bus down".into(),
            state_committed: true,
        })
    }
    async fn emit_token_revoked(&self, _e: TokenRevoked) -> Result<(), IdentityError> {
        Err(IdentityError::EmitFailed {
            message: "bus down".into(),
            state_committed: true,
        })
    }
}

/// Sink that fails the first `fail_n` emits and succeeds afterward.
/// Drives the retry-after-emit-failure tests: the first call returns
/// `EmitFailed` with state already committed; the retry observes the
/// same row, re-emits via this sink, and now succeeds.
struct FlakySink {
    fail_n: AtomicUsize,
    principals: Mutex<Vec<PrincipalCreated>>,
    issued: Mutex<Vec<TokenIssued>>,
}

impl FlakySink {
    fn new(fail_n: usize) -> Self {
        Self {
            fail_n: AtomicUsize::new(fail_n),
            principals: Mutex::default(),
            issued: Mutex::default(),
        }
    }

    fn step(&self) -> bool {
        // Returns true while we're still in the "fail" window.
        loop {
            let current = self.fail_n.load(Ordering::SeqCst);
            if current == 0 {
                return false;
            }
            if self
                .fail_n
                .compare_exchange(current, current - 1, Ordering::SeqCst, Ordering::SeqCst)
                .is_ok()
            {
                return true;
            }
        }
    }
}

#[async_trait]
impl IdentityEventSink for FlakySink {
    async fn emit_principal_created(&self, event: PrincipalCreated) -> Result<(), IdentityError> {
        if self.step() {
            return Err(IdentityError::EmitFailed {
                message: "bus down".into(),
                state_committed: true,
            });
        }
        self.principals.lock().unwrap().push(event);
        Ok(())
    }
    async fn emit_token_issued(&self, event: TokenIssued) -> Result<(), IdentityError> {
        if self.step() {
            return Err(IdentityError::EmitFailed {
                message: "bus down".into(),
                state_committed: true,
            });
        }
        self.issued.lock().unwrap().push(event);
        Ok(())
    }
    async fn emit_token_revoked(&self, _: TokenRevoked) -> Result<(), IdentityError> {
        Ok(())
    }
}

fn build_service(pool: PgPool) -> (IdentityService, Arc<VecSink>) {
    let sink: Arc<VecSink> = Arc::new(VecSink::default());
    (IdentityService::new(pool, sink.clone()), sink)
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn ensure_principal_human_inserts_and_emits(pool: PgPool) {
    let (svc, sink) = build_service(pool);

    let uuid = svc
        .ensure_principal(&Principal::Human {
            email: "owner@example.com".into(),
            role: Role::Owner,
        })
        .await
        .expect("ensure human");

    assert!(!uuid.is_nil());
    let events = sink.principals.lock().unwrap();
    assert_eq!(events.len(), 1);
    let event = &events[0];
    assert_eq!(event.principal_uuid, uuid);
    assert_eq!(event.kind, PrincipalKind::Human);
    assert_eq!(event.email.as_deref(), Some("owner@example.com"));
    assert_eq!(event.role, Some(Role::Owner));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn ensure_principal_is_idempotent_and_emits_each_call(pool: PgPool) {
    // RV-1: every call emits with a stable idempotency_key (the uuid_id)
    // so subscribers dedupe. The DB row is created once; the envelope is
    // re-emitted on every call so retries after an emit failure recover.
    let (svc, sink) = build_service(pool);
    let principal = Principal::Human {
        email: "owner@example.com".into(),
        role: Role::Owner,
    };

    let first = svc.ensure_principal(&principal).await.expect("first call");
    let second = svc
        .ensure_principal(&principal)
        .await
        .expect("second call returns same uuid");

    assert_eq!(first, second, "uuid must be stable across calls");
    let events = sink.principals.lock().unwrap();
    assert_eq!(events.len(), 2, "every call must emit; subscribers dedupe");
    assert_eq!(events[0].principal_uuid, first);
    assert_eq!(events[1].principal_uuid, first);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn ensure_principal_agent_session_and_system(pool: PgPool) {
    let (svc, sink) = build_service(pool);

    svc.ensure_principal(&Principal::AgentSession {
        session_id: SessionId::new(),
        role: Role::Member,
    })
    .await
    .expect("agent session");
    svc.ensure_principal(&Principal::System {
        service: "agent_runtime".into(),
    })
    .await
    .expect("system");

    let events = sink.principals.lock().unwrap();
    assert_eq!(events.len(), 2);
    let kinds: Vec<_> = events.iter().map(|e| e.kind).collect();
    assert!(kinds.contains(&PrincipalKind::AgentSession));
    assert!(kinds.contains(&PrincipalKind::System));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn ensure_principal_rejects_anonymous(pool: PgPool) {
    let (svc, _sink) = build_service(pool);
    let err = svc
        .ensure_principal(&Principal::resolve_anonymous())
        .await
        .expect_err("anonymous must not persist");
    assert!(matches!(err, IdentityError::AuthMalformed(_)));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn issue_token_emits_token_issued(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let session_id = SessionId::new();
    let principal_uuid = svc
        .ensure_principal(&Principal::AgentSession {
            session_id,
            role: Role::Member,
        })
        .await
        .expect("ensure agent session");

    let token = svc
        .issue_session_token(principal_uuid, session_id, Role::Member)
        .await
        .expect("issue token");

    {
        let issued = sink.issued.lock().unwrap();
        assert_eq!(issued.len(), 1);
        assert_eq!(issued[0].principal_uuid, principal_uuid);
        assert_eq!(issued[0].session_id, session_id);
    }

    // Validate the token resolves to the agent session principal.
    let resolved = svc
        .validate_session_token(token)
        .await
        .expect("validate live");
    assert!(matches!(resolved, Principal::AgentSession { .. }));
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn revoke_emits_only_when_tokens_transitioned(pool: PgPool) {
    let (svc, sink) = build_service(pool);
    let session_id = SessionId::new();
    let principal_uuid = svc
        .ensure_principal(&Principal::AgentSession {
            session_id,
            role: Role::Member,
        })
        .await
        .expect("ensure");
    let _ = svc
        .issue_session_token(principal_uuid, session_id, Role::Member)
        .await
        .expect("issue");

    let revoked = svc.revoke_session_tokens(session_id).await.expect("revoke");
    assert_eq!(revoked, 1);

    let no_op = svc
        .revoke_session_tokens(session_id)
        .await
        .expect("second revoke is idempotent");
    assert_eq!(no_op, 0);

    let events = sink.revoked.lock().unwrap();
    assert_eq!(events.len(), 1, "second revoke must not emit");
    assert_eq!(events[0].tokens_revoked, 1);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn emit_failure_after_commit_returns_emit_failed_with_durable_state(pool: PgPool) {
    let svc = IdentityService::new(pool.clone(), Arc::new(FailingSink));

    let err = svc
        .ensure_principal(&Principal::Human {
            email: "owner@example.com".into(),
            role: Role::Owner,
        })
        .await
        .expect_err("expected EmitFailed");

    match err {
        IdentityError::EmitFailed {
            state_committed, ..
        } => {
            assert!(state_committed, "state must be durable after emit failure");
        }
        other => panic!("expected EmitFailed, got {other:?}"),
    }

    // The row IS in Postgres despite the emit failure — that is the whole
    // point of commit-then-emit. A retry observes the existing row and
    // re-emits the same envelope (idempotency_key derived from uuid_id);
    // the next test exercises that recovery path with a FlakySink.
    let count: i64 = sqlx::query_scalar(
        "select count(*) from identity.principals where kind = 'human' and email = 'owner@example.com'",
    )
    .fetch_one(&pool)
    .await
    .expect("count rows");
    assert_eq!(count, 1, "principal row must persist despite emit failure");
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn ensure_principal_retry_after_emit_failure_reemits_same_logical_event(pool: PgPool) {
    // RV-1: After the first call commits and the emit fails, the second
    // call must NOT mutate state again and must re-emit the same envelope
    // (so subscriber-side dedup is the safety net, not the service).
    let sink: Arc<FlakySink> = Arc::new(FlakySink::new(1));
    let svc = IdentityService::new(pool.clone(), sink.clone());
    let principal = Principal::Human {
        email: "owner@example.com".into(),
        role: Role::Owner,
    };

    let err = svc
        .ensure_principal(&principal)
        .await
        .expect_err("first call: emit fails");
    assert!(matches!(err, IdentityError::EmitFailed { .. }));

    let uuid = svc
        .ensure_principal(&principal)
        .await
        .expect("retry succeeds");

    // Exactly one row in Postgres — retry observed the existing principal.
    let count: i64 = sqlx::query_scalar(
        "select count(*) from identity.principals where kind = 'human' and email = 'owner@example.com'",
    )
    .fetch_one(&pool)
    .await
    .expect("count");
    assert_eq!(count, 1, "retry must not insert a duplicate row");

    // The successful retry emitted, carrying the same principal_uuid.
    let events = sink.principals.lock().unwrap();
    assert_eq!(events.len(), 1, "only the successful retry emit lands");
    assert_eq!(events[0].principal_uuid, uuid);
}

#[sqlx::test(migrator = "MIGRATOR")]
async fn issue_session_token_retry_after_emit_failure_reuses_token(pool: PgPool) {
    // RV-1: a second call with the same (principal_uuid, session_id)
    // returns the existing live token rather than minting a fresh one,
    // and re-emits TokenIssued so subscribers dedupe.

    // Phase 1: seed the agent session principal with a reliable sink so
    // the test isolates the token-retry contract from the principal-emit
    // path (which is already covered by the previous test).
    let (seed_svc, _seed_sink) = build_service(pool.clone());
    let session_id = SessionId::new();
    let principal_uuid = seed_svc
        .ensure_principal(&Principal::AgentSession {
            session_id,
            role: Role::Member,
        })
        .await
        .expect("seed agent session");

    // Phase 2: token issuance with a FlakySink that fails the first emit.
    let sink: Arc<FlakySink> = Arc::new(FlakySink::new(1));
    let svc = IdentityService::new(pool.clone(), sink.clone());

    let err = svc
        .issue_session_token(principal_uuid, session_id, Role::Member)
        .await
        .expect_err("emit fails on first attempt");
    assert!(matches!(err, IdentityError::EmitFailed { .. }));

    // Token IS in Postgres despite the failed emit.
    let live_count: i64 = sqlx::query_scalar(
        "select count(*) from identity.session_tokens where session_id = $1 and revoked_at is null",
    )
    .bind(session_id.0)
    .fetch_one(&pool)
    .await
    .expect("count tokens");
    assert_eq!(live_count, 1);

    // Retry returns the same token; this time emit succeeds.
    let second_token = svc
        .issue_session_token(principal_uuid, session_id, Role::Member)
        .await
        .expect("retry succeeds");

    let live_count_after: i64 = sqlx::query_scalar(
        "select count(*) from identity.session_tokens where session_id = $1 and revoked_at is null",
    )
    .bind(session_id.0)
    .fetch_one(&pool)
    .await
    .expect("count tokens after retry");
    assert_eq!(live_count_after, 1, "retry must not mint a second token");

    {
        let issued = sink.issued.lock().unwrap();
        assert_eq!(issued.len(), 1, "only the successful retry emit lands");
        assert_eq!(issued[0].principal_uuid, principal_uuid);
        assert_eq!(issued[0].session_id, session_id);
    }

    // The recovered token matches the row in Postgres.
    let stored: uuid::Uuid = sqlx::query_scalar(
        "select token from identity.session_tokens where session_id = $1 and revoked_at is null",
    )
    .bind(session_id.0)
    .fetch_one(&pool)
    .await
    .expect("fetch stored token");
    assert_eq!(stored, second_token.0);
}

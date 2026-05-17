//! `telec-cli migrate-identity-v1` — one-shot import of the v1 people
//! roster and any v1 session-token rows into the v2 `identity` schema.
//!
//! ## v1 source surface
//!
//! - `~/.teleclaude/teleclaude.yml` (`people:` block) — the canonical
//!   roster.
//! - Optional `teleclaude.db` (`session_tokens` table) — copied verbatim
//!   when supplied (token uuid, session id, role). The v1 schema is:
//!
//!   ```sql
//!   create table session_tokens (
//!     token text primary key,
//!     session_id text not null,  -- not necessarily a UUID
//!     principal text not null,   -- email
//!     role text not null
//!   );
//!   ```
//!
//!   v1 stores `session_id` as opaque text. Non-UUID v1 ids are mapped
//!   onto a deterministic UUIDv5 inside the [`V1_SESSION_NAMESPACE`]
//!   namespace so the v2 `identity.session_tokens.session_id uuid`
//!   column can hold them without losing identity. The chosen namespace
//!   is stable so re-running migration yields the same v2 uuid.
//!
//! ## Mapping
//!
//! Roster role strings map onto [`identity::Role`] via
//! [`IdentityError::parse_role`]. Unknown role strings surface
//! [`IdentityError::InvalidRole`] and the migration aborts — no silent
//! coercion to Member.
//!
//! The first person in the roster (without an explicit role override) is
//! treated as the workspace owner so the migrated `identity.principals`
//! has a clear authoritative human.
//!
//! ## Idempotency
//!
//! - Principals: funnelled through [`IdentityService::ensure_principal`],
//!   which upserts on the natural key and re-emits on every call.
//! - Tokens: imported via [`identity::import_session_token`] which uses
//!   `INSERT ... ON CONFLICT (token) DO NOTHING`. Existing rows are
//!   skipped; newly-imported rows trigger a `TokenIssued` emit via the
//!   real event sink.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context, Result};
use async_trait::async_trait;
use chrono::Utc;
use clap::Args;
use config::load_global;
use identity::events::{PrincipalCreated, TokenIssued, TokenRevoked};
use identity::{
    import_session_token, IdentityError, IdentityEventSink, IdentityService, Principal, Role, Token,
};
use rusqlite::Connection;
use shared::SessionId;
use tracing::{info, warn};
use uuid::Uuid;

/// Stable UUIDv5 namespace under which non-UUID v1 session ids are mapped
/// onto deterministic v2 uuids. The byte sequence is frozen so re-runs
/// produce identical mappings; do not change the bytes without coordinating
/// a migration of the resulting v2 session ids.
pub const V1_SESSION_NAMESPACE: Uuid = Uuid::from_bytes([
    0x6f, 0x7a, 0x53, 0xa4, 0x4f, 0x96, 0x4a, 0xd5, 0x91, 0xf2, 0x3c, 0x1d, 0x5a, 0x8b, 0x2e, 0xef,
]);

/// Arguments for `telec-cli migrate-identity-v1`.
#[derive(Args, Debug, Clone)]
pub struct MigrateIdentityArgs {
    /// Path to the v1 global config (`~/.teleclaude/teleclaude.yml`).
    /// Defaults to `$HOME/.teleclaude/teleclaude.yml`.
    #[arg(long)]
    pub config_file: Option<PathBuf>,

    /// Optional path to a v1 `teleclaude.db` SQLite file containing
    /// `session_tokens`. When omitted, token import is skipped.
    #[arg(long)]
    pub tokens_db: Option<PathBuf>,

    /// Roll back any DB writes at the end (useful for verifying the
    /// migration plan without touching v2 state).
    #[arg(long)]
    pub dry_run: bool,
}

/// Summary returned by [`migrate_identity_v1`] for CLI reporting.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MigrationSummary {
    pub humans_inserted: u32,
    pub humans_skipped_existing: u32,
    pub tokens_inserted: u32,
    pub tokens_skipped_existing: u32,
    pub dry_run: bool,
}

/// Run the v1 → v2 identity migration through an existing
/// [`IdentityService`].
///
/// Non-dry-run migration writes flow through the service's real event
/// sink, so `identity.*` envelopes reach Redis and the v1 daemon's
/// `IdentityBridge` subscribes to them. Dry-run writes flow through an
/// internal no-op sink and then revert every row this invocation
/// inserted, so `--dry-run` has neither durable rows nor emitted
/// `identity.*` side effects.
pub async fn migrate_identity_v1(
    service: &IdentityService,
    args: &MigrateIdentityArgs,
) -> Result<MigrationSummary> {
    let config_path = resolve_config_path(args.config_file.as_deref())?;
    let global = load_global(&config_path)
        .with_context(|| format!("read v1 global config at {}", config_path.display()))?;

    let mut summary = MigrationSummary {
        dry_run: args.dry_run,
        ..MigrationSummary::default()
    };

    let mut inserted_emails: Vec<String> = Vec::new();
    let mut inserted_token_uuids: Vec<Uuid> = Vec::new();
    let dry_run_service;
    let migration_service = if args.dry_run {
        dry_run_service = IdentityService::new(service.pool().clone(), Arc::new(NoopIdentitySink));
        &dry_run_service
    } else {
        service
    };

    // Owner is the first roster entry whose role isn't explicitly
    // 'newcomer' (catches accidental ordering hazards in v1 configs).
    let mut owner_assigned = false;
    for (idx, person) in global.people.iter().enumerate() {
        let role = if !owner_assigned && idx == 0 && person.role != "newcomer" {
            owner_assigned = true;
            Role::Owner
        } else {
            IdentityError::parse_role(&person.role)
                .with_context(|| format!("parse role for {}", person.email))?
        };

        let principal = Principal::Human {
            email: person.email.clone(),
            role,
        };
        let was_present = principal_exists(migration_service, &person.email).await?;
        migration_service
            .ensure_principal(&principal)
            .await
            .with_context(|| format!("ensure principal for {}", person.email))?;
        if !was_present {
            summary.humans_inserted += 1;
            inserted_emails.push(person.email.clone());
        } else {
            summary.humans_skipped_existing += 1;
        }
    }

    if let Some(tokens_db) = args.tokens_db.as_deref() {
        let imported =
            import_v1_session_tokens(migration_service, tokens_db, &mut inserted_token_uuids)
                .await?;
        summary.tokens_inserted = imported.inserted;
        summary.tokens_skipped_existing = imported.skipped;
    }

    if args.dry_run {
        // Migration helpers don't open an explicit transaction — every
        // upsert commits immediately. Honour --dry-run by deleting the
        // rows we wrote during this invocation. The dry-run service above
        // uses a no-op sink, so there are no emitted events to roll back.
        revert_inserted_humans(service.pool(), &inserted_emails).await?;
        revert_inserted_tokens(service.pool(), &inserted_token_uuids).await?;
        info!(
            ?summary,
            "migrate-identity-v1 dry-run complete; v2 state restored"
        );
    } else {
        info!(?summary, "migrate-identity-v1 complete");
    }

    Ok(summary)
}

fn resolve_config_path(explicit: Option<&Path>) -> Result<PathBuf> {
    if let Some(path) = explicit {
        return Ok(path.to_path_buf());
    }
    let home = std::env::var("HOME").context("HOME env var must be set")?;
    Ok(PathBuf::from(home).join(".teleclaude/teleclaude.yml"))
}

async fn principal_exists(service: &IdentityService, email: &str) -> Result<bool> {
    let exists: bool = sqlx::query_scalar(
        "select exists (select 1 from identity.principals where kind = 'human' and email = $1)",
    )
    .bind(email)
    .fetch_one(service.pool())
    .await
    .context("check existing principal")?;
    Ok(exists)
}

#[derive(Default)]
struct TokenImportResult {
    inserted: u32,
    skipped: u32,
}

async fn import_v1_session_tokens(
    service: &IdentityService,
    sqlite_path: &Path,
    inserted_token_uuids: &mut Vec<Uuid>,
) -> Result<TokenImportResult> {
    if !sqlite_path.exists() {
        info!(path = %sqlite_path.display(), "tokens-db absent; skipping session-token import");
        return Ok(TokenImportResult::default());
    }
    let conn = Connection::open(sqlite_path)
        .with_context(|| format!("open v1 tokens db at {}", sqlite_path.display()))?;
    let mut stmt = conn
        .prepare("select token, session_id, principal, role from session_tokens")
        .context("prepare v1 session_tokens query")?;
    let rows = stmt
        .query_map([], |row| {
            Ok(V1TokenRow {
                token: row.get::<_, String>(0)?,
                session_id: row.get::<_, String>(1)?,
                principal_email: row.get::<_, String>(2)?,
                role: row.get::<_, String>(3)?,
            })
        })
        .context("query v1 session_tokens")?;

    let mut result = TokenImportResult::default();
    for row in rows {
        let row = row.context("decode v1 session token row")?;
        let token = match Token::parse(&row.token) {
            Ok(t) => t,
            Err(_) => {
                warn!(token = %row.token, "skipping non-UUID v1 token");
                result.skipped += 1;
                continue;
            }
        };
        let session_id = map_v1_session_id(&row.session_id);
        let role = IdentityError::parse_role(&row.role)
            .with_context(|| format!("v1 token role for session {}", row.session_id))?;

        let principal = Principal::Human {
            email: row.principal_email.clone(),
            role,
        };
        let principal_uuid = service
            .ensure_principal(&principal)
            .await
            .context("ensure principal during token import")?;
        let inserted =
            import_session_token(service.pool(), principal_uuid, token, session_id, role)
                .await
                .with_context(|| format!("import v1 token {}", row.token))?;
        if inserted {
            result.inserted += 1;
            inserted_token_uuids.push(token.0);
            // Re-emit TokenIssued through the real event sink so the v1
            // daemon's IdentityBridge sees the import. We construct the
            // envelope here because the service `issue_session_token`
            // path would generate a fresh token; `import_session_token`
            // preserves the v1 uuid.
            let event = TokenIssued {
                principal_uuid,
                session_id,
                role,
                issued_at: Utc::now(),
            };
            service
                .events()
                .emit_token_issued(event)
                .await
                .context("emit identity.token.issued for imported v1 row")?;
        } else {
            result.skipped += 1;
        }
    }
    Ok(result)
}

struct NoopIdentitySink;

#[async_trait]
impl IdentityEventSink for NoopIdentitySink {
    async fn emit_principal_created(&self, _event: PrincipalCreated) -> Result<(), IdentityError> {
        Ok(())
    }

    async fn emit_token_issued(&self, _event: TokenIssued) -> Result<(), IdentityError> {
        Ok(())
    }

    async fn emit_token_revoked(&self, _event: TokenRevoked) -> Result<(), IdentityError> {
        Ok(())
    }
}

struct V1TokenRow {
    token: String,
    session_id: String,
    principal_email: String,
    role: String,
}

/// Map a v1 session id (opaque text) onto a deterministic v2 [`SessionId`]
/// uuid.
///
/// When the v1 string already parses as a UUID it is used verbatim.
/// Otherwise the value is hashed into a UUIDv5 inside
/// [`V1_SESSION_NAMESPACE`] so the v1→v2 mapping is stable and reversible
/// via the namespace.
pub fn map_v1_session_id(raw: &str) -> SessionId {
    if let Ok(uuid) = raw.parse::<Uuid>() {
        return SessionId(uuid);
    }
    SessionId(Uuid::new_v5(&V1_SESSION_NAMESPACE, raw.as_bytes()))
}

async fn revert_inserted_humans(pool: &sqlx::PgPool, emails: &[String]) -> Result<()> {
    if emails.is_empty() {
        return Ok(());
    }
    sqlx::query("delete from identity.principals where kind = 'human' and email = any($1)")
        .bind(emails)
        .execute(pool)
        .await
        .context("dry-run revert of inserted humans")?;
    Ok(())
}

async fn revert_inserted_tokens(pool: &sqlx::PgPool, tokens: &[Uuid]) -> Result<()> {
    if tokens.is_empty() {
        return Ok(());
    }
    sqlx::query("delete from identity.session_tokens where token = any($1)")
        .bind(tokens)
        .execute(pool)
        .await
        .context("dry-run revert of inserted tokens")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn map_v1_session_id_passes_uuid_through() {
        let raw = "12345678-1234-1234-1234-123456789012";
        let mapped = map_v1_session_id(raw);
        assert_eq!(mapped.0.to_string(), raw);
    }

    #[test]
    fn map_v1_session_id_hashes_non_uuid_inputs_deterministically() {
        let raw = "legacy-session-name";
        let first = map_v1_session_id(raw);
        let second = map_v1_session_id(raw);
        assert_eq!(first, second);
        // Different inputs → different uuids.
        assert_ne!(first, map_v1_session_id("other-legacy-name"));
    }
}

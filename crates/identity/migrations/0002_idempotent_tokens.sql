-- 0002_idempotent_tokens.sql — pin one live session token per (principal,
-- session) pair so issuance is retry-safe under the commit-then-emit posture.
--
-- After this migration, `issue_session_token` on the Rust side uses
-- `insert ... on conflict do nothing` and falls back to selecting the
-- existing live token row when a (principal_id, session_id) pair is
-- already populated. The combination + the LRU idempotency-key cache on
-- subscribers means a retry after an emit failure re-emits the same
-- envelope without minting a fresh token.
--
-- Revoked tokens are excluded from the index so historical revocations
-- never collide with new issuance for the same session id.

create unique index if not exists session_tokens_active_per_session_uq
  on identity.session_tokens(principal_id, session_id)
  where revoked_at is null;

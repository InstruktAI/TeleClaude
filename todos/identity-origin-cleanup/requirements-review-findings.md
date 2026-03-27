# Requirements Review Findings: identity-origin-cleanup

## Auto-remediated (resolved in this pass)

1. **Missing `[inferred]` markers** — Added to out-of-scope database column item (line 29) and backward compatibility constraint (line 96), both inferred from codebase rather than stated in input.

2. **R2 implementation leakage** — Replaced private function name `_prepare_run_session` with behavioral description "No session creation code path" in success criterion. The requirement should constrain behavior, not name internal functions.

## Open Findings

### RRF-1: R3 title-scope mismatch (Suggestion)

**Location:** R3 title and success criteria

**Finding:** R3 is titled "Promote actor context and target_computer to named fields in Redis transport" but the success criteria only address `target_computer`. The input also mentions "Promote actor context and target_computer in Redis transport to named fields."

**Analysis:** The Redis transport does not inject actor context into `channel_metadata` — it reads existing actor fields placed there by edge adapters. Only `target_computer` is injected by the transport itself (line 250 of `_messaging.py`). Actor context in Redis-relayed messages is a legitimate edge signal being relayed, not an internal routing field being smuggled.

**Recommendation:** Either rename R3 to "Promote target_computer to a named field in Redis transport" to match the actual scope, or add a note explaining why actor context promotion is not needed. No behavioral change required.

**Severity:** Suggestion

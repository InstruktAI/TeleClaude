# Requirements: fallback-fail-fast-hardening

## Intent

Enforce fail-fast contract handling in fallback-heavy code paths so missing/invalid inputs are surfaced explicitly and runtime behavior remains deterministic.

## In Scope

1. Session creation boundary contracts (`project_path`, role-based jailing rules).
2. Session data retrieval response contract clarity (`transcript` vs fallback vs pending).
3. Telegram delivery hardening for parse-entities + footer consistency.
4. Invalid-topic cleanup suppression guards to prevent repeated noisy retries.
5. Fallback observability and policy alignment for the above paths.

## Out of Scope

1. Re-architecture of adapter model.
2. Full redesign of identity/authorization model.
3. Global rewrite of all fallbacks across unrelated subsystems.

## Functional Requirements

### FR1: Boundary Contract Enforcement

1. Required input contracts MUST fail at ingress; missing required values MUST not be coerced to sentinel values.
2. Existing explicit non-admin role routing to `help-desk` MUST be preserved as-is.
3. Non-role-based `help-desk` reroutes (for example missing `project_path`) MUST be removed; missing required path MUST produce explicit failure.

### FR2: Session Data Contract Clarity

1. `get_session_data` MUST not return ambiguous empty-success payloads when transcript is unavailable.
2. Response shape MUST clearly distinguish:
   - transcript available
   - tmux fallback content returned
   - transcript pending/unavailable
3. Callers MUST be able to branch on explicit state, not on `messages == ""`.

### FR3: Telegram Parse/Footer Consistency

1. Parse-entities failure handling MUST preserve deterministic outbound behavior and not create duplicate footer artifacts.
2. Footer emission/editing MUST remain single-path and stateful; no legacy parallel footer route may survive.
3. Parse fallback behavior MUST be explicit and logged with reason codes.

### FR4: Cleanup Guarding

1. Invalid-topic cleanup attempts MUST be bounded/suppressed per topic within a cooldown window.
2. Repeated non-retryable invalid-topic failures MUST not spam logs or hammer cleanup calls.

### FR5: Observability and Governance

1. Fallback paths touched in this todo MUST emit structured reason codes in logs.
2. Hidden fail-open fallback behavior (`silent drop`, `sentinel success`) is disallowed in this scope.

## Success Criteria

- [ ] Session creation no longer accepts missing required path via sentinel coercion.
- [ ] Non-role-based `help-desk` reroute is removed while explicit non-admin routing remains intact.
- [ ] Session data contract exposes explicit availability states.
- [ ] Telegram parse-entities regressions do not produce duplicate footer outcomes.
- [ ] Invalid-topic cleanup retries are bounded and observable.
- [ ] All touched paths verified by targeted tests and pass `make lint` + `make test`.

## Risks

1. Tightening contracts can expose latent caller bugs currently hidden by fallback behavior.
2. Existing consumers may depend on ambiguous legacy responses.
3. Telegram behavior changes may alter operator-visible message cadence.

# Requirements: Person Identity Auth — Phase 1: Identity Model & Config

## Goal

Build the identity model foundation: PersonEntry config consumption, IdentityResolver service, IdentityContext dataclass, and human role constants. This is the dependency for all subsequent auth phases.

## Scope

### In scope

1. **Consume PersonEntry schema** from `teleclaude/config/schema.py` (created by config-schema-validation). No model redefinition.
2. **Identity bootstrap** in `teleclaude/core/identity.py` consuming `load_global_config()` from config loaders.
3. **IdentityResolver class** with multi-signal lookup (email primary, username secondary).
4. **IdentityContext dataclass** — normalized identity result with resolution source.
5. **Human role constants** in `teleclaude/constants.py`.
6. **Unit tests** in `tests/unit/test_identity.py`.

### Out of scope

- Session binding (phase 2).
- Auth middleware (phase 2).
- Token signing (phase 2).
- Role-based tool gating (phase 3).
- Adapter integration (phase 3).

## Functional Requirements

### FR1: PersonEntry consumption

- Reuse `PersonEntry` from `teleclaude/config/schema.py` (name, email, username, role).
- People loaded from `~/.teleclaude/teleclaude.yml` via `load_global_config()`.
- No new YAML parsing logic.

### FR2: IdentityResolver

- Constructor takes `list[PersonEntry]`.
- `resolve_by_email(email: str) -> IdentityContext | None` — exact match, primary signal.
- `resolve_by_username(username: str) -> IdentityContext | None` — exact match, secondary signal.
- Unknown signals return None.
- Resolver initialized at daemon startup; no runtime config reload.

### FR3: IdentityContext

- Dataclass with fields: `email`, `role`, `username` (optional), `resolution_source`.
- `resolution_source` tracks how identity was resolved ("email", "username", "header", "token").

### FR4: Human role constants

- `HUMAN_ROLE_ADMIN`, `HUMAN_ROLE_MEMBER`, `HUMAN_ROLE_CONTRIBUTOR`, `HUMAN_ROLE_NEWCOMER`.
- `HUMAN_ROLES` set for validation.

## Acceptance Criteria

1. PersonEntry parses correctly from sample config dict with email + role.
2. IdentityResolver maps email to correct person.
3. IdentityResolver maps username to correct person.
4. Unknown email/username returns None.
5. Invalid roles raise ValueError during config validation.
6. IdentityContext dataclass constructs with all fields.
7. Human role constants are defined and importable.
8. `get_identity_resolver()` module-level function returns configured resolver.

## Dependencies

- **config-schema-validation** must be complete (provides PersonEntry model and load_global_config).

# Requirements: Person Identity Auth — Phase 1: Identity Model & Config

## Goal

Build the identity model foundation: PersonEntry config consumption, IdentityResolver service, IdentityContext dataclass, and human role constants. This is the dependency for all subsequent auth phases.

## Scope

### In scope

1. **Consume PersonEntry schema** from `teleclaude/config/schema.py` (created by config-schema-validation). No model redefinition.
2. **Identity bootstrap** in `teleclaude/core/identity.py` consuming `load_global_config()` from config loaders.
3. **IdentityResolver class** with multi-signal lookup (email primary, username secondary).
4. **Platform credential lookup bridge** from per-person config (Telegram user_id now).
5. **IdentityContext dataclass** — normalized identity result with resolution source and platform metadata.
6. **Human role constants** in `teleclaude/constants.py`.
7. **Unit tests** in `tests/unit/test_identity.py`.

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
- `resolve_by_telegram_user_id(user_id: int) -> IdentityContext | None` — map platform credential to trusted person.
- Unknown signals return None.
- Resolver initialized at daemon startup; no runtime config reload.
- Resolver can read per-person creds mappings from `~/.teleclaude/people/*/teleclaude.yml`.

### FR3: IdentityContext

- Dataclass includes person and platform identity fields plus trust metadata.
- Minimum fields: person email/role/username + platform/platform_user_id/platform_username + auth source + trust level.

### FR4: Human role constants

- `HUMAN_ROLE_ADMIN`, `HUMAN_ROLE_MEMBER`, `HUMAN_ROLE_CONTRIBUTOR`, `HUMAN_ROLE_NEWCOMER`.
- `HUMAN_ROLES` set for validation.

## Acceptance Criteria

1. PersonEntry parses correctly from sample config dict with email + role.
2. IdentityResolver maps email to correct person.
3. IdentityResolver maps username to correct person.
4. IdentityResolver maps known telegram user_id to correct person.
5. Unknown email/username/platform user_id returns None.
6. Invalid roles raise ValueError during config validation.
7. IdentityContext dataclass constructs with all fields.
8. Human role constants are defined and importable.
9. `get_identity_resolver()` module-level function returns configured resolver.

## Dependencies

- **config-schema-validation** must be complete (provides PersonEntry model and load_global_config).

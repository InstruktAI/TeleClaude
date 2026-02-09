# Person Identity Auth — Phase 1: Identity Model & Config

## Context

This is phase 1 of the person-identity-auth breakdown. See the parent todo's
`implementation-plan.md` for full architectural context.

## Intended Outcome

Build the PersonEntry config model, global teleclaude.yml people loader, identity
resolver service, and human role constants. This is the foundation that all
subsequent auth work depends on.

## What to Build

1. **Reuse PersonEntry schema** from `config-schema-validation` (no redefinition in this todo).
2. **Identity bootstrap** in `teleclaude/core/identity.py` that consumes `load_global_config()` from `teleclaude/config/loader.py`.
3. **IdentityResolver class** in same file — multi-signal lookup (email primary, username secondary -> person).
4. **IdentityContext dataclass** — normalized identity result with resolution source.
5. **Human role constants** in `teleclaude/constants.py`.
6. **Unit tests** in `tests/unit/test_identity.py`.

## Key Architectural Notes

- People config lives in `~/.teleclaude/teleclaude.yml` (global level), NOT in `config.yml` (daemon config). These are separate config files loaded separately.
- Do not implement a second people parser in daemon `config.yml`; keep one identity source of truth.
- Do not add raw YAML parsing here; consume typed config loaders from `config-schema-validation`.
- Email is the stable identity key for auth and session metadata.
- Username is optional and internal-only.

## Verification

- Unit tests pass for all resolver paths.
- PersonEntry parses correctly from sample config dict.
- Invalid roles raise ValueError.
- Unknown lookup signals return None.

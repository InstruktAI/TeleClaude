# Repo Cleanup

## Intended Outcome
A focused cleanup pass that removes dead code, resolves known inconsistencies, and consolidates type/contract boundaries to reduce noise and maintenance overhead without changing product behavior.

## Scope Hints
- Remove obsolete/unused paths and tests that no longer reflect current behavior.
- Consolidate and document “boundary exceptions” (where loose data is allowed) and tighten internal typing/contracts elsewhere.
- Normalize logging and error handling on critical paths to reduce defensive clutter.
- Keep behavior stable; avoid feature changes.

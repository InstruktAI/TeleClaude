# Requirements: refactor-large-files

## Goal

Decompose the oversized source files identified by the todo input into focused,
cohesive modules. The refactoring is purely structural — no behavioral changes.
After completion, each refactored module stays within the size ceiling and all
existing imports resolve correctly.

## Scope

### In scope

- Structural decomposition of all 20 target files listed in the input.
- Updating all import statements across the codebase to reflect new module
  locations.
- Compatibility shims to preserve backward-compatible import paths where
  external consumers exist.
- [inferred] Lint and type-check compliance after each decomposition.
- Runtime smoke verification (daemon starts, TUI renders, CLI responds).

### Out of scope

- Behavioral changes, API changes, or feature additions.
- Writing or modifying tests (test suite rebuild is sequenced after this todo via
  `test-suite-overhaul` and its children in the roadmap).
- Refactoring files outside the target inventory captured in `input.md`.
- Changing function signatures, class interfaces, or public APIs.

## Success Criteria

- [ ] Every target file is decomposed such that no resulting module exceeds ~500
      lines (soft target), with a hard ceiling of 800 lines.
- [ ] All codebase imports resolve correctly — no `ImportError` at module load
      time.
- [ ] `make lint` passes with zero violations.
- [ ] [inferred] Type checking passes at the project's configured strictness
      level.
- [ ] Runtime smoke test passes: daemon starts successfully, TUI renders, CLI
      responds to commands.
- [ ] No behavioral regressions — decomposition is structure-only.
- [ ] Each decomposition is committed atomically (per file or per tightly-coupled
      group).

## Constraints

1. **No behavior changes.** Only structural decomposition. Function bodies,
   class logic, and public interfaces remain identical.
2. **Import continuity.** All downstream imports must continue to resolve. For
   widely used modules, compatibility shims are required where needed to keep
   existing import paths working.
3. **[inferred] No circular dependencies introduced.** Decomposition must
   respect the existing dependency graph direction.
4. **Follow established codebase patterns.** [inferred] Use the project's
   existing package-splitting and facade patterns rather than inventing a new
   module organization style for this refactor.
5. **No test changes.** The test suite has been intentionally deleted and will
   be rebuilt from scratch in a dependent todo. Zero test files are created or
   modified as part of this work.
6. **Atomic commits.** Each file (or tightly-coupled group) is committed as a
   self-contained, non-breaking change.
7. **Size ceiling is per-file, not per-package.** Splitting a 4,000-line file
   into a package is valid as long as each module within the package stays
   under the ceiling.

## Risks

1. **High-fanout modules.** Modules with many downstream importers are more
   likely to cause broad runtime breakage if compatibility is missed.
2. **[inferred] Circular dependency introduction.** Extracting closely-coupled
   logic can create import cycles that were not present in the original file.
3. **[inferred] Decomposition shape varies by file archetype.** Files dominated
   by one large class may need a different split approach than files dominated
   by top-level helpers.
4. **Session capacity.** [inferred] 20 files totaling ~41,000 lines exceeds
   single-session capacity. The draft phase should assess splitting this todo
   into independent, parallelizable children — one per file or per logical
   group — given that the input explicitly notes files can be refactored
   independently.

## Verification

For each decomposed file:

1. All imports across the codebase resolve (no `ImportError` on load).
2. `make lint` passes.
3. [inferred] Type checking passes.

After all decompositions complete:

4. Full runtime smoke test: daemon starts, TUI renders, CLI responds.
5. No refactored module exceeds 800 lines (hard ceiling).
6. [inferred] `git log` shows atomic, task-scoped commits with no mixed-scope
   changes.

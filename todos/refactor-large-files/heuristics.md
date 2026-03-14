# Refactoring Heuristics

Required reading for all rlf-* builders. This is your playbook.

## Objective

Decompose oversized files into focused, DRY modules that pass strict lint.
You are touching every line — improve what you touch.

## How to Work

1. Read the target files in your input.md. Understand the internal structure —
   concern groups, repeated patterns, duplicated helpers.
2. Read project policies via `telec docs index` — code quality, linting,
   commits. These are your acceptance criteria.
3. DRY first, split second. Extract duplicated logic into shared utilities
   before creating submodules. The split should produce cleaner code, not
   just shorter files.
4. Follow existing precedent. If the codebase already has a decomposition
   pattern for similar modules (packages with mixins, `__init__.py`
   re-exports), follow it. Do not invent new patterns.
5. Preserve public API. Use `__init__.py` re-exports so all external imports
   continue to work.
6. Commit atomically. One logical decomposition per commit.
7. Verify after every commit: `make lint`, `make test`, no import errors.

## Improve While You Touch

You are already reading and moving every line. Do these improvements
immediately as you decompose — not as a second pass. Fix them in place
during the split so you only touch each line once.

- **All imports at module top level.** No inline imports inside functions
  or methods. Move them to the top of the new submodule as you create it.
- **Add type hints** where missing — parameters, return types, variables
  where inference is ambiguous.
- **Add docstrings** where missing — modules, classes, public functions.
- **Add logging** at key boundaries for observability.
- **Modernize syntax** — use `X | Y` instead of `Union[X, Y]`, use
  modern isinstance syntax (no tuples where `|` works). The linter
  enforces UP038 (non-pep604-isinstance).
- **Remove commented-out code.** Dead code is noise. Git has the history.
- **Simplify control flow** — collapse nested ifs (SIM102), replace
  if/else with ternary where clearer (SIM108), use `contextlib.suppress`
  instead of bare try/except/pass, remove superfluous else after return.
- **Use pathlib** over os.path where the code is being restructured anyway.
- **Reduce McCabe complexity.** Max allowed is 20. Extract helper functions
  from deeply nested or long conditional chains. This naturally produces
  smaller, more testable units.

## Do NOT

- **No defensive programming.** Trust every existing contract. If a function
  accepts `str`, do not add `isinstance` checks. If a parameter is not
  Optional, do not add None guards. Do not wrap calls in try/except that
  didn't have them. Do not add fallback values. Do not doubt any contract.
  Fail fast on violations — never swallow or guard against them.
- **No signature changes.** When extracting shared utilities, match the
  existing calling convention. Do not redesign interfaces.
- **No abstraction invention.** Extract common code into simple shared
  functions. Do not create abstract base classes, factories, strategy
  patterns, or design-pattern scaffolding.
- **No behavior changes.** Public API and observable runtime behavior must
  not change. Internal consolidation is the point, not feature work.
- **No new tests.** Existing tests must pass. The test suite rebuild is
  sequenced after this.
- **No lint config changes.** Do not touch pyproject.toml, pyrightconfig,
  or any linter/type-checker configuration. No `# noqa` suppressions.

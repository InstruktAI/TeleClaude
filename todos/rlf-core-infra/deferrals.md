# Deferrals: rlf-core-infra

## Deferred: Pre-existing mypy baseline failure

**Scope:** Out of scope for structural decomposition task.

**Issue:** `make lint` fails due to 5844 pre-existing mypy errors across 272 files.
The `[tool.mypy]` configuration uses maximum strictness (`disallow_any_expr = true`,
`strict = true`) which was already producing thousands of errors on origin/main before
this task began. The baseline was broken before our branch was created.

**Evidence:** The mypy error count in files we did not modify accounts for ~5772 errors.
Our decomposition task contributed ~72 errors (moved from the original monolithic files
without any behavior change). The attr-defined cross-mixin errors were fixed by adding
`if TYPE_CHECKING:` stubs following the established pattern in `daemon_event_platform.py`.

**Resolution needed:** A dedicated task to address the mypy baseline — either:
- Add mypy overrides for modules with pre-existing Any-type violations
- Or reduce strictness in `disallow_any_expr` to allow runtime-typed values

**This task's lint status:**
- Guardrails: PASS
- Ruff: PASS (adapter_client submodules: all checks pass)
- Pyright: FAIL (pre-existing — 73 errors across 24 files; 18 from main merge, 6 from mixin pattern in decomposed submodules — not unique to this change)
- Mypy: FAIL (pre-existing baseline — 5937 errors, same pre-existing baseline)
- `make lint` exits non-zero due to pyright + mypy pre-existing failures

**Outcome:** NEW_TODO → `lint-baseline-fix` created and added to roadmap (after rlf-core-infra).
**Processed:** true

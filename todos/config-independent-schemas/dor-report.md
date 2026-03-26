# DOR Gate Report: config-independent-schemas

**Assessed:** 2026-03-26T20:30:00Z
**Verdict:** PASS
**Score:** 9 / 10

---

## Gate Verdict

All eight DOR gates pass. The artifact set is coherent, grounded in the codebase, and
sufficient for a builder to execute without guessing. One minor gap (no explicit spec for
`git.checkout_root` migration on a GlobalConfig YAML) keeps the score from 10 but does not
block implementation — the risk is documented in requirements and the migration validator
is specified in the plan.

---

## Cross-Artifact Validation

### Plan-to-requirement fidelity

| Requirement                          | Plan task(s)                                       | Status |
| ------------------------------------ | -------------------------------------------------- | ------ |
| Req 1 — independent config schemas   | Task 1 (break inheritance, reject_disallowed_keys) | ✓      |
| Req 2 — composed AppConfig           | Task 2                                             | ✓      |
| Req 3 — entry-point config loading   | Task 4 (load_app_config)                           | ✓      |
| Req 4 — eliminate interior loading   | Tasks 5 (context_selector), 6 (docs CLI wiring)    | ✓      |
| Req 5 — relocate checkout_root       | Tasks 1 (GlobalConfig), 7 (git_repo_helper)        | ✓      |
| Req 6 — atomic project config writes | Task 3 (save_project_config)                       | ✓      |
| Req 7 — test updates                 | Task 8                                             | ✓      |

No orphan tasks. No orphan requirements. No plan task contradicts a requirement.

### Verification chain

Every task references specific xfail tests it makes GREEN. Task 6 (docs CLI wiring) has no
dedicated spec test — this is acknowledged in the plan. Coverage flows through
`TestPersonWorkspaceDocs` end-to-end, which is acceptable for pure wiring. The cross-cutting
verification section specifies the full-suite run after all tasks.

---

## DOR Gate Results

### Gate 1: Intent & Success — PASS

Problem statement is explicit: crashes when `telec docs index` runs from a person workspace
(`~/.teleclaude/people/`) because `load_project_config()` is called on a PersonConfig YAML
containing `creds`/`notifications`, which `ProjectConfig.reject_disallowed_keys` rejects.
Ten concrete, testable success criteria are listed (lines 65–78 of requirements.md).

### Gate 2: Scope & Size — PASS

Plan assessed as ATOMIC. ~190 lines across 7 production files. All pieces are tightly
coupled (schema → loader → consumers → wiring → tests). Splitting heuristics were applied:
one coherent behavior change, independently unshippable parts, detail level (exact paths and
before/after code) reduces discovery overhead. Dependencies are intra-task (sequential), not
inter-todo.

### Gate 3: Verification — PASS

Xfail test specifications exist in `tests/unit/config/test_config_independent_schemas.py`.
All 7 spec review findings from the prior review round are addressed in the current spec:

- Critical 1 (`except Exception: pass`): Fixed — I/O helpers mocked, function runs to completion.
- Important 1 (unrecognized path): Fixed — `test_load_app_config_unrecognized_path_has_no_project` added.
- Important 2 (atomic write test fragility): Fixed — patches `os.replace` (the rename step) rather than `builtins.open`.
- Important 3 (tautological backward-compat assertion): Fixed — asserts on `GitConfig.model_fields` and `model_extra`.
- Minor 1 (`hasattr` check): Fixed — uses `"git" not in GlobalConfig.model_fields`.
- Minor 2 (global config setup): Fixed — mocks `load_global_config` in all `TestPersonWorkspaceDocs` tests.
- Minor 3 (key-rejection runtime behavior): Fixed — three runtime `ValidationError` tests added to `TestSchemaIndependence`.

One remaining minor gap: no xfail test for the migration of `git.checkout_root` in a
GlobalConfig YAML (only ProjectConfig backward compat is tested). The risk is noted in
requirements. The migration validator is specified in Task 1. Acceptable — does not block.

### Gate 4: Approach Known — PASS

All 8 tasks provide specific code, exact file paths, and rationale. The plan references the
existing `_atomic_yaml_write` pattern in `config_handlers.py` for Task 3. The `AppConfig`
frozen dataclass, the `model_validator(mode="before")` migration, the `Path.is_relative_to`
person-workspace detection — all are concrete, verifiable approaches with no unknowns.

### Gate 5: Research Complete — PASS (auto-satisfied)

No new third-party tools or integrations introduced. Existing Pydantic v2 and PyYAML are
already in use. The `dataclasses.dataclass` import is standard library.

### Gate 6: Dependencies & Preconditions — PASS

No prerequisite todos. No new config surface introduced (explicitly called out in
out-of-scope). No external systems required.

### Gate 7: Integration Safety — PASS

The `config` parameter on `build_context_output` is optional — callers outside the docs
pipeline continue working without changes. Backward compat for existing YAML files is
preserved via the migration validator and `extra="allow"`. The acknowledged risk (callers
that read project-level fields from a GlobalConfig instance will break) is documented in
requirements and the builder is directed to audit all GlobalConfig consumers.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

No scaffolding procedures modified. The change is confined to runtime config logic.

---

## Review-Readiness Preview

The plan survives each DoD review lane without gaps:

- **Testing lane**: xfail specs cover all behavioral requirements. Task 8 handles existing
  test updates. Pre-commit verification is specified after all tasks.
- **Code quality lane**: Tasks include rationale annotations. The immutability requirement
  (`frozen=True`) is specified. No new abstractions beyond requirements.
- **Linting lane**: No new imports beyond `os` (stdlib) and `dataclass` (stdlib).
  `AppConfig` import from schema to loader is explicit.
- **Security lane**: Not applicable — no auth, credentials, or injection surfaces.
- **Documentation lane**: No new public CLI surface. No config wizard changes needed
  (no new config keys). The `AppConfig` type is internal.
- **Backward compat lane**: `config` parameter is optional. YAML file structure unchanged.
  Migration validator handles `git.checkout_root` transition.

---

## Minor Gap (non-blocking)

**No xfail test for GlobalConfig YAML with `git.checkout_root`.**

The backward-compat constraint requires that existing GlobalConfig files containing
`git.checkout_root` continue to work after the field moves to top-level. The plan specifies
a `model_validator(mode="before")` that migrates the old YAML path. Only the ProjectConfig
backward compat is covered by `test_backward_compat_checkout_root_on_project_config`.
The builder should add a GlobalConfig migration test in Task 1 (or include it in Task 8).
This is non-blocking — the spec test for `test_global_config_has_checkout_root_as_declared_field`
confirms the final shape, and the risk is documented.

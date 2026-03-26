# Spec Review Findings: config-independent-schemas

Verdict: **NEEDS_WORK**

The spec suite (`tests/unit/config/test_config_independent_schemas.py`) now exists and covers
most requirements. Several findings require fixes before the suite can be trusted as a behavioral
contract for the builder.

---

## Critical 1: `TestInteriorLoadingElimination` — `except Exception: pass` creates false confidence

**Scope:** Req #4 — `test_build_context_output_does_not_call_load_project_config`,
`test_get_project_name_not_called_internally`

Both tests share the pattern:

```python
with patch("...load_project_config") as mock_load:
    try:
        build_context_output(...)
    except Exception:
        pass  # Pipeline may fail for other reasons
    mock_load.assert_not_called()
```

A broken implementation that raises immediately (e.g., `raise NotImplementedError`) satisfies
`mock_load.assert_not_called()` because the function never runs far enough to call anything. The
assertion passes trivially regardless of whether interior loading was actually eliminated.

**Required fix:** Either (a) set up the minimal fixtures needed for `build_context_output` to run
to completion without error, making the mock assertion meaningful, or (b) restructure the test so
it directly verifies that the function's signature requires `config` and that the function body
does not import or alias `load_project_config` as a local call site — but structural inspection is
inferior to a behavioral test with working fixtures.

The test for `test_build_context_output_accepts_config_parameter` (signature inspection) is
solid; the mock-call tests need the same rigor.

---

## Important 1: Req #3 — "no fallback for unrecognized paths" has no spec

**Scope:** Req #3 — entry-point config loading

The requirement explicitly states: "No fallback for unrecognized paths — the loader must not
guess." There is no test verifying that `load_app_config` behaves deterministically (raises, or
returns only the global layer) for a directory that is neither a person workspace nor a recognized
project workspace.

Without this test, the builder may implement a silently-wrong fallback path (e.g., attempting
ProjectConfig validation on an arbitrary directory) that goes undetected.

**Required:** Add a test that calls `load_app_config` on a plain temp directory (no
`teleclaude.yml`) and asserts that either (a) it raises a clear error, or (b) it returns
`AppConfig(global_=GlobalConfig(), project=None)` — whichever is the contract.

---

## Important 2: `test_save_project_config_atomic_no_partial_write` — mock is implementation-coupled

**Scope:** Req #6

Patching `builtins.open` with a blanket `side_effect=OSError` is fragile. If the implementation
writes via `pathlib.Path.write_text`, `pathlib.Path.write_bytes`, or `tempfile.NamedTemporaryFile`,
the mock may not intercept the write, allowing the actual write to succeed and the assertion to
fail as a false negative. The test also cannot verify the rename step of the atomic pattern.

A more robust approach: verify that the implementation delegates to the same atomic write utility
already used for global/person configs (inspect the function, or run it over a real filesystem and
verify no partial-write file is left behind on an injected filesystem error). At minimum the test
should document its assumption about the write mechanism.

The round-trip test (`test_save_project_config_writes_valid_yaml`) is solid; the atomicity test
needs to be strengthened or the fragility explicitly acknowledged.

---

## Important 3: `test_backward_compat_checkout_root_on_project_config` — tautological assertion

**Scope:** Req #5 / Constraint "checkout_root backward compat"

```python
config = ProjectConfig.model_validate({"git": {"checkout_root": "/old/path"}})
assert config is not None
```

`assert config is not None` is always true for a successful `model_validate` call — any
non-crashing implementation satisfies this. The backward-compat contract requires that the old
YAML path does not crash AND that the value is either forwarded or explicitly ignored. The test
should assert on the specific contract: e.g., that the field survives in `model_extra` or that
the load does not raise, and confirm that `config.git` does not expose `checkout_root` as an
authoritative attribute.

---

## Minor 1: `test_global_config_does_not_have_project_field_git` — `hasattr` is incorrect check

**Scope:** Req #1

```python
config = GlobalConfig()
assert not hasattr(config, "git"), ...
```

If `GlobalConfig` declares `git: GitConfig | None = None`, then `hasattr(config, "git")` returns
`True` even though the field has a `None` default. This test would incorrectly pass a schema
where `git` is an optional field on `GlobalConfig`. The structural check should use
`"git" not in GlobalConfig.model_fields` (already done correctly in
`test_global_config_fields_exclude_project_only_fields`). Remove this test or rewrite it using
`model_fields`.

---

## Minor 2: Test helpers lack global config setup

**Scope:** `TestPersonWorkspaceDocs`

`_person_workspace` and `_project_workspace` create workspace-level configs but do not create a
global config file at any discoverable path. The assertions `config.global_ is not None` and
`config.global_` references assume that `load_app_config` either defaults to an empty
`GlobalConfig` when no global config file is found, or that the tests must mock global config
loading. This assumption is not documented and may produce fragile tests on machines with a real
`~/.teleclaude/teleclaude.yml`. Add a global config fixture (even a minimal empty one) or
explicitly mock global config loading.

---

## Minor 3: Key-rejection behavior not specced

**Scope:** Req #1 — "rejects keys belonging to other levels"

The structural tests (inheritance checks, field set checks) do not verify the runtime validation
behavior: that loading a YAML with alien keys raises a `ValidationError`. This was the root cause
of the original bug (`creds` key in a ProjectConfig-validated file). The spec should include at
least one test per schema confirming that the `reject_disallowed_keys` validator still fires:

```python
with pytest.raises(ValidationError):
    ProjectConfig.model_validate({"creds": {...}})
```

Without this, the builder can break the key-rejection behavior while still passing all structural
checks.

---

## Summary

| Finding                                              | Severity  | Requirement |
| ---------------------------------------------------- | --------- | ----------- |
| `except Exception: pass` allows trivial false passes | Critical  | Req #4      |
| Unrecognized workspace path has no spec              | Important | Req #3      |
| Atomic write test is implementation-coupled          | Important | Req #6      |
| Backward-compat assertion is tautological            | Important | Req #5      |
| `hasattr` check is wrong structural predicate        | Minor     | Req #1      |
| Helpers lack global config setup                     | Minor     | Req #3      |
| Key-rejection runtime behavior unspecced             | Minor     | Req #1      |

# Spec Review Findings — agent-cli-context-preservation

**Verdict:** needs_work
**Reviewed at:** 2026-03-28 (round 2)
**Findings count:** 3 (1 Critical, 2 Important)

---

## Summary

Specs now exist in two files:

- `tests/unit/install/test_configure_agent_cli.py` — covers R1, R2, R3, R4, R6
- `tests/unit/scripts/test_distribute.py` — covers R5

Coverage is substantially improved from round 1 (where no specs existed). R2, R3, R5 are fully
covered. R6 regression guards are correctly implemented as non-xfail tests (the .codex/ prototype
files are already absent). R4 is mostly covered but has a weak content assertion. R1 has a
critical gap: the success criterion requiring old module paths be absent from disk is untested.

---

## Findings

### F1 — [Critical] R1: No test verifies old module paths are removed from disk

**Location:** `tests/unit/install/test_configure_agent_cli.py`
**Requirement:** R1 success criteria — "The old module paths no longer exist on disk after the change."

`teleclaude/install/install_hooks.py` currently exists in the repo. `bin/init/install_hooks.py`
also currently exists. The specs verify the new module IS importable and that references are
updated, but no spec catches the inverse: the old paths surviving the rename. A builder could
create `configure_agent_cli.py` while leaving `install_hooks.py` in place, and all current
tests would pass — including the new importability tests. The old path becoming an orphan is
exactly the failure mode this success criterion guards against.

**Required additions** (xfail, strict=True):

```python
def test_install_hooks_module_no_longer_exists_on_disk() -> None:
    assert not (_REPO_ROOT / "teleclaude" / "install" / "install_hooks.py").exists()

def test_bin_init_entry_point_no_longer_exists_at_old_path() -> None:
    assert not (_REPO_ROOT / "bin" / "init" / "install_hooks.py").exists()
```

Both must be `@pytest.mark.xfail(strict=True)` since the old paths currently exist.

---

### F2 — [Important] R4: Compaction prompt deployment uses a truthy content assertion

**Location:** `tests/unit/install/test_configure_agent_cli.py` — `test_configure_codex_writes_compaction_prompt_to_codex_dir`

```python
assert prompt_file.read_text(encoding="utf-8").strip(), "Compaction prompt file must not be empty"
```

Policy: "Truthy-check assertions — `assert value` passes for any non-empty value. If a trivially
wrong implementation satisfies the assertion, the assertion is worthless." A broken implementation
writing any non-empty placeholder ("TODO", "x") would pass this test.

The deployed file should contain the content from the repo-owned source
(`teleclaude/install/settings/CODEX.compaction.md`). Strengthen to verify the deployed content
matches the source:

```python
source = (_REPO_ROOT / "teleclaude" / "install" / "settings" / COMPACTION_PROMPT_FILENAME).read_text(encoding="utf-8")
assert prompt_file.read_text(encoding="utf-8") == source
```

This would also make F2 in test_configure_codex_sets_compact_prompt_toml_key (value truthy check)
less critical — though that assertion (`isinstance(value, str) and value.strip()`) is acceptable
for a filename: the filename's content-significance makes any valid string acceptable there.

---

### F3 — [Important] R4: Settings override mechanism not end-to-end verified

**Location:** `tests/unit/install/test_configure_agent_cli.py` — `test_compact_prompt_key_sourced_from_settings_override`

The test verifies `settings/codex.json` contains `experimental_compact_prompt_file` as a key.
This is necessary but not sufficient. An implementation could hardcode the key directly in the
configurator logic AND also add it to codex.json; the test would pass in both the correct and
broken case.

The requirement is that the key is _delivered via_ the existing override mechanism — not
merely that codex.json has the key. To close this gap, the test should also assert that the
value in the deployed `config.toml` matches what's in `settings/codex.json`:

```python
settings = json.loads(settings_path.read_text(encoding="utf-8"))
# ... after configure_codex runs with tmp_path ...
config = tomllib.loads(config_path.read_text(encoding="utf-8"))
assert config[COMPACT_PROMPT_TOML_KEY] == settings[COMPACT_PROMPT_TOML_KEY]
```

This check would fail if the value is hardcoded differently from the settings file, confirming
the override mechanism is actually the delivery path.

---

## Per-requirement coverage matrix

| Req | Description                         | Spec coverage                                                | Status                        |
| --- | ----------------------------------- | ------------------------------------------------------------ | ----------------------------- |
| R1  | Rename module                       | New path importable, functions callable, refs updated        | **Gap: old paths not tested** |
| R2  | Inline shell wrapper                | Removed script, init.sh updated, entry point invoked         | Complete                      |
| R3  | Repo-owned compaction prompt source | File exists, preservation markers in content                 | Complete                      |
| R4  | Deploy compaction prompt            | Write, TOML key, idempotency, settings override              | Weak assertions (F2, F3)      |
| R5  | Markdown marker wrapping            | Helper contract, position ordering, TOML exclusion, pipeline | Complete                      |
| R6  | Remove prototype files              | Non-xfail regression guards for both files                   | Complete                      |
| R7  | Test coverage requirement           | Covered by these spec files                                  | Complete                      |

---

## What needs_work means here

F1 (Critical) must be resolved before the suite is ready for a builder. F2 and F3 should be
fixed alongside F1. No new spec files are required — all fixes are additions or strengthening
of assertions within the existing two spec files.

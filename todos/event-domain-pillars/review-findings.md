# Review Findings: event-domain-pillars

## Verdict: APPROVE

---

## Important

### 1. `deploy.*` vs pre-existing `deployment.*` naming ambiguity

**Location:** `teleclaude_events/schemas/software_development.py:112-192`

The new `deploy.*` events (`deploy.triggered`, `deploy.succeeded`, `deploy.failed`) coexist
with pre-existing `deployment.*` events (`deployment.started`, `deployment.completed`,
`deployment.failed`) in the same domain. Both categories model deployment-adjacent lifecycle
stages with overlapping language:

- `deploy.failed` (new, line 136) = environment deployment failure
- `deployment.failed` (pre-existing, line 228) = integration merge failure

The concepts are distinct (environment release vs integration merge-to-main) but the naming
creates confusion for cartridge authors and guardian prompts. The guardian evaluation prompt
references "deployment anomalies" — ambiguous between the two categories.

**Recommendation:** Either rename the new category to `release.*` or `env-deploy.*` to
disambiguate, or add a clear comment block in the module docstring explaining the distinction.
Since both categories are new (nothing emits either yet), this is the right time to fix the
naming. Not blocking delivery since the catalog enforces uniqueness and no runtime collision
occurs.

---

### 2. Broad `except Exception` catches in config seeding deviate from codebase pattern

**Location:** `teleclaude/project_setup/domain_seeds.py:34` and `:65`

Two broad `except Exception` catches log-and-return on YAML read/write failures. The codebase
pattern in `teleclaude/config/loader.py` re-raises config errors rather than swallowing them.

**Read path (line 34):** Catches all exceptions including programming bugs (`TypeError`,
`AttributeError`). Should narrow to `(OSError, yaml.YAMLError)`.

**Write path (line 65):** If `yaml.safe_dump` fails after opening the file with `"w"`, the
config file may be truncated. The function logs and returns, leaving a potentially corrupted
file. Should narrow exception types and ideally write to a temp file then rename atomically.

**Recommendation:** Narrow both catches to `(OSError, yaml.YAMLError)`. For the write path,
consider atomic write (write to `.tmp`, then rename).

---

### 3. Non-dict YAML not validated after parse

**Location:** `teleclaude/project_setup/domain_seeds.py:31-33`

```python
raw: dict[str, Any] = yaml.safe_load(f) or {}
```

If the YAML file contains valid non-dict content (a string, list, or scalar), `yaml.safe_load`
returns a truthy non-dict value. The `or {}` handles `None` but not non-dict. The subsequent
`raw.get("event_domains")` at line 38 (outside the try block) would raise an unhandled
`AttributeError`.

**Recommendation:** Add `if not isinstance(raw, dict): return` after the parse.

---

## Suggestions

### 4. `DEFAULT_EVENT_DOMAINS` mutation risk

**Location:** `teleclaude_events/domain_seeds.py` (module-level dict),
`teleclaude/project_setup/domain_seeds.py:54`

The merge loop uses `raw["event_domains"]["domains"].update(value)` where `value` references
the nested dict from `DEFAULT_EVENT_DOMAINS`. While no current code mutates the seed data, a
`copy.deepcopy` before merging would prevent future latent mutation bugs.

### 5. Unused `_project_root` parameter

**Location:** `teleclaude/project_setup/domain_seeds.py:19`

The function accepts `_project_root` but operates on the hardcoded `_GLOBAL_CONFIG_PATH`.
Either the parameter should be removed or the function should derive the config path from it.

### 6. Test monkeypatching of module-level private

**Location:** `tests/unit/test_teleclaude_events/test_domain_cartridges.py:147`

Tests directly mutate `seeds_mod._GLOBAL_CONFIG_PATH` in a try/finally block. Using
`monkeypatch.setattr` would be more idiomatic and xdist-safe.

### 7. Missing software-development domain consistency test

**Location:** `tests/unit/test_teleclaude_events/test_domain_schemas.py`

Marketing, creative-production, and customer-relations all have
`test_all_events_have_{domain}_domain` tests. Software-development does not. Minor asymmetry.

---

## Paradigm-Fit Assessment

1. **Data flow:** Schema registration follows the established `EventCatalog.register(EventSchema(...))`
   pattern exactly. Config seeding uses raw YAML I/O (no typed save mechanism exists in the
   config loader), which is pragmatic and appropriate.

2. **Component reuse:** All new code reuses existing types (`EventSchema`, `NotificationLifecycle`,
   `CartridgeManifest`, `DomainsConfig`). No copy-paste duplication.

3. **Pattern consistency:** All four schema modules follow identical structure: same imports,
   same `TYPE_CHECKING` guard, same `register_*` signature, same registration style. Module-level
   docstrings are present. The `init_flow.py` integration uses lazy import consistent with the
   existing `help_desk_bootstrap` pattern.

## Principle Violation Hunt

- **Fallback/silent degradation:** The broad `except Exception` catches are the primary finding
  (see Important #2). The `return` on config-not-found (line 25) at `debug` level is acceptable —
  seeding is non-critical to init and missing config is a valid state during first-time setup.
- **Fail Fast:** Schema registration uses `EventCatalog.register()` which raises `ValueError`
  on duplicates. Correct.
- **DIP:** Clean separation — data in `teleclaude_events/domain_seeds.py`, seeding logic in
  `teleclaude/project_setup/domain_seeds.py`, no adapter imports in domain code.
- **Coupling/Demeter:** No deep chains. Dict navigation in seeding is stable YAML structure.
- **SRP:** Each module has single responsibility. Clean.
- **YAGNI/KISS:** No premature abstractions. Straightforward data registration.
- **Encapsulation:** Uses catalog's public API throughout.
- **Immutability:** `DEFAULT_EVENT_DOMAINS` is module-level mutable dict but only read at runtime.
  Noted as Suggestion #4.

## Demo Review

- 6 executable blocks verified against actual implementation.
- Block 1-4: Use `build_default_catalog()`, `catalog.get()`, `list_all()`, `.domain`,
  `.actionable` — all real API, assertions match actual event registrations.
- Block 5: `cat` on manifest.yaml — file confirmed to exist on disk.
- Block 6: `telec config get event_domains` — valid CLI command.
- No fabricated output. No stubs. Exercises actual implemented features.

## Requirements Tracing

All 14 success criteria from `requirements.md` map to implemented and tested functionality:

- Schema registration for all 4 pillars: verified via tests and catalog audit (37 domain events)
- Existing 9 events preserved: `test_original_nine_events_preserved`
- Starter cartridges with valid manifests: all 12 cartridge dirs exist with `manifest.yaml` + `cartridge.py`
- Domain config with guardian: `test_domains_config_validates` confirms `DomainsConfig` validation
- Marketing feed-monitor `depends_on`: confirmed in manifest YAML
- Customer-relations `trust_threshold: strict`: confirmed in seed data and manifest `trust_required`
- `telec init` seeding: `seed_event_domains()` called in `init_flow.py`, idempotency tested
- No wildcard subscriptions: all manifests declare explicit `event_types`
- `make lint` and `make test` pass per build checklist

## Test Coverage Assessment

- 38 new tests, all passing.
- Schema registration completeness, actionable flags, domain consistency, naming convention,
  config seeding idempotency, and cartridge manifest validation all covered.
- Gaps: error paths in `domain_seeds.py` untested, no negative actionable tests,
  `skipif` guards on cartridge tests create silent CI skips. These are Suggestions,
  not blockers.
- Note: 4 pre-existing integration lifecycle events (`review.approved`, `deployment.*`) at
  `software_development.py:196-236` are untested, but these are out of scope for this review
  (pre-existing on main, not added by this branch).

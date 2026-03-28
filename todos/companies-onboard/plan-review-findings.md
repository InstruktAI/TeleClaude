# Plan Review Findings: companies-onboard

**Final verdict: APPROVE** — All findings resolved through fixer collaboration.

## Resolved During Review

The following findings were auto-remediated inline during the initial review pass:

- **Task 9 config access** — Added explicit config-reading pattern to Task 9 rationale:
  use `resolve_project_config_path(project_root)` + `load_project_config()` following
  the `_load_project_domains()` pattern. Add a `_load_project_company()` helper that
  returns `str | None` and pass the result to `_load_selected_snippets()`.

- **Review Lane Anticipation table** — Added "Demo" row (pre-existing `demo.md` confirmed
  complete with 7 executable blocks) and clarified Config surface row to include
  `config.sample.yml` update requirement.

## Resolved by Fixer (commit 68d320536)

### C1 — `requirements.md` populated ✓

`requirements.md` was an empty stub template. The fixer populated it from `input.md`
with a complete goal, in-scope/out-of-scope definition, testable success criteria,
constraints, and risks. Requirements review precondition now satisfied.

### I1 — Task 10 `write_index_yaml` project_root specified ✓

Task 10 now specifies `write_index_yaml(company_dir, company_dir / COMPANY_DOCS_SUBDIR)`
— using the company directory as `project_root` for company-scoped index builds.
This resolves the path ambiguity for company docs outside any project tree.

### I2 — xfail test specifications created ✓

10 xfail test spec files created:

- `tests/unit/config/test_project_config_company_field.py`
- `tests/unit/company_setup/test_bootstrap.py`
- `tests/unit/company_setup/test_enrichment.py`
- `tests/unit/company_setup/test_inbox.py`
- `tests/unit/cli/telec/handlers/test_companies.py`
- `tests/unit/test_enrichment_core.py`
- `tests/unit/test_context_selector_company.py`
- `tests/unit/test_docs_index_company.py`
- `tests/unit/test_sync_company.py`

All files use `# guard: no-companion` at line 1 and `pytestmark = pytest.mark.xfail(strict=True)`.
Plan tasks updated to reference specific xfail spec names.

### I3 — `config.sample.yml` update task added ✓

Task 1 extended with a verification step to add `company: <slug>` example to
`teleclaude.sample.yml`. `teleclaude.sample.yml` added to `state.yaml.grounding.referenced_paths`.

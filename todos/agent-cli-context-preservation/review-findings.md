# REVIEW COMPLETE: agent-cli-context-preservation

Plan completeness: all implementation-plan tasks are checked `[x]`.
Deferrals: none (`todos/agent-cli-context-preservation/deferrals.md` says "No active deferrals.").

## Summary

### Critical

- `teleclaude/install/configure_agent_cli.py:511` logs a missing `CODEX.compaction.md` source and continues, while `teleclaude/install/configure_agent_cli.py:519` and `teleclaude/install/configure_agent_cli.py:520` still write `experimental_compact_prompt_file` into `~/.codex/config.toml`. I reproduced this by patching `SETTINGS_DIR` to a directory that contained `codex.json` but not `CODEX.compaction.md`: the resulting config still contained `experimental_compact_prompt_file = "CODEX.compaction.md"` while the deployed prompt file was absent. This is an unjustified log-and-continue fallback on a required asset; the configurator must fail fast or omit the setting when the prompt copy cannot be completed.

### Important

- `scripts/distribute.py:82` uses `content.rstrip()` before wrapping markdown with the preservation markers. That mutates the document body instead of adding a pure outer wrapper. With `'# Title\n\nBody\n\n'`, the trailing blank line is removed, so requirement R5's "preserve existing file structure and formatting" criterion is not met.
- `tests/unit/scripts/test_distribute.py:74` only asserts `content.strip() in result`, so it does not enforce exact body preservation and does not catch the `rstrip()` regression above. The explicit R5 formatting-preservation requirement is therefore unguarded.
- `todos/agent-cli-context-preservation/demo.md:93` says it verifies that markdown outputs are wrapped, but the bash block only greps `scripts/distribute.py` for marker constants and helper presence. It never runs the serializer/distribution path or inspects emitted markdown, so the demo can pass while the generated artifacts are wrong.
- The rename to "configure agent CLI" did not propagate through adjacent prose surfaces: `bin/init.sh:4`, `teleclaude/project_setup/init_flow.py:182`, and `docs/project/design/architecture/help-desk-platform.md:123` still describe the init flow as installing "agent hooks". R1 explicitly called for comment/log text updates, and the docs lane requires user-facing docs to reflect the new behavior.

### Suggestions

- `todos/agent-cli-context-preservation/quality-checklist.md:21` is checked even though `todos/agent-cli-context-preservation/quality-checklist.md:31` says Playwright smoke testing is not applicable. Leave that gate unchecked or mark it explicitly `N/A` to avoid overstating build verification.

## Lane Results

### Scope

- Finding: `scripts/distribute.py:82` violates R5 by mutating markdown payload before wrapping it. The delivery does not fully meet the requirement that the markers be added as an outer layer while preserving existing formatting.

### Code

- Finding: `teleclaude/install/configure_agent_cli.py:511` / `teleclaude/install/configure_agent_cli.py:519` / `teleclaude/install/configure_agent_cli.py:520` silently produce a broken Codex configuration when the prompt source is missing.
- Finding: `scripts/distribute.py:82` strips trailing content before wrapping.

### Paradigm

- No findings. The rename preserves the existing install/configuration seam and keeps transport-specific behavior at the edge.

### Principles

- Finding: `teleclaude/install/configure_agent_cli.py:511` introduces an unjustified log-and-continue fallback for a required asset. This is a fail-fast violation and a silent-degradation path.

### Security

- No findings. I did not find new secrets, injection risks, auth regressions, or end-user error leaks in the changed code.

### Tests

- Finding: `tests/unit/scripts/test_distribute.py:74` weakens the preservation contract enough that the formatting regression in `scripts/distribute.py:82` ships undetected.
- Verification run: `.venv/bin/python -m pytest tests/unit/install/test_configure_agent_cli.py tests/unit/scripts/test_distribute.py tests/unit/project_setup/test_init_flow.py -q` passed (`39 passed`).

### Errors

- Finding: `teleclaude/install/configure_agent_cli.py:511` logs a missing prompt file and continues to write a config that points at a file that was never deployed.

### Types

- No findings. `./tools/lint.sh` completed successfully, including `pyright` and `mypy`.

### Comments

- Finding: `bin/init.sh:4` and `teleclaude/project_setup/init_flow.py:182` still describe the init flow in the old "agent hooks" terms instead of the broader agent CLI configuration role.

### Logging

- No findings. I did not see ad-hoc debug probes or logging changes that violate current patterns.

### Demo

- Finding: `todos/agent-cli-context-preservation/demo.md:93` does not actually exercise the generated markdown outputs it claims to validate.
- Verification run: `telec todo demo validate agent-cli-context-preservation` passed structurally (`8 executable block(s) found`), but the substantive marker-validation step is too shallow.

### Docs

- Finding: `docs/project/design/architecture/help-desk-platform.md:123` still documents `telec init` as installing "agent hooks", which is stale after the rename and scope clarification.

### Simplify

- Not run. The simplify lane is deferred because unresolved Critical/Important findings remain.

## Fixes Applied

- Critical: `teleclaude/install/configure_agent_cli.py:511` wrote `experimental_compact_prompt_file` even when `CODEX.compaction.md` could not be deployed. Fix: skip that override and remove any stale top-level key when the prompt asset is unavailable, with a regression test covering the missing-source case. Commit: `06a4e139d`
- Important: `scripts/distribute.py:82` stripped trailing markdown content before wrapping. Fix: preserve the original body exactly and only add the outer marker lines. Commit: `0ac0b291a`
- Important: `tests/unit/scripts/test_distribute.py:74` only checked `content.strip()`. Fix: strengthen the regression test to assert exact wrapped output, including trailing blank lines. Commit: `0ac0b291a`
- Important: `todos/agent-cli-context-preservation/demo.md:93` only grepped the source file instead of validating emitted markdown. Fix: replace the demo check with a real serializer invocation that asserts both preservation markers in the generated output, and sync the published demo artifact. Commit: `c84d760cd`
- Important: `bin/init.sh:4`, `teleclaude/project_setup/init_flow.py:182`, and `docs/project/design/architecture/help-desk-platform.md:123` still used the old "agent hooks" wording. Fix: align those user-facing text surfaces to "agent CLI configuration"/"configures agent CLIs". Commit: `b013fe51f`

## Verdict

Verdict: REQUEST CHANGES

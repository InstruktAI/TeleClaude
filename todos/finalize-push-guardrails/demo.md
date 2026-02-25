# Demo: finalize-push-guardrails

## Validation

```bash
# Worker finalize command must stop at FINALIZE_READY
rg -n "FINALIZE_READY: \\{slug\\}" agents/commands/next-finalize.md
```

```bash
# Orchestrator post-completion must gate on FINALIZE_READY and run canonical apply
rg -n "FINALIZE_READY: \\{args\\}|telec roadmap deliver \\{args\\}|git -C \"\\$MAIN_REPO\" merge \\{args\\} --no-edit|git -C \"\\$MAIN_REPO\" push origin main" teleclaude/core/next_machine/core.py
```

```bash
# Pre-push hook guardrail is installed and includes audit markers
test -x .githooks/pre-push
rg -n "TELECLAUDE_PRE_PUSH_MAIN_GUARD_BLOCK|GUARDRAIL_MARKER|MAIN_GUARDRAIL_BLOCKED" .githooks/pre-push
```

```bash
# Git and GH wrapper templates include canonical-main guardrails and stop/report guidance
rg -n "TELECLAUDE_GIT_PUSH_MAIN_GUARD_BLOCK|GUARDRAIL_MARKER|MAIN_GUARDRAIL_BLOCKED|FINALIZE_READY" teleclaude/install/wrappers/git
rg -n "TELECLAUDE_GH_MAIN_MERGE_GUARD_BLOCK|GUARDRAIL_MARKER|MAIN_GUARDRAIL_BLOCKED|FINALIZE_READY" teleclaude/install/wrappers/gh
```

```bash
# Guardrail behavior tests (includes feature-branch non-regression assertions)
pytest -q -n0 tests/unit/test_git_wrapper_guardrails.py tests/unit/test_gh_wrapper_guardrails.py tests/unit/test_pre_push_guardrails.py
```

## Guided Presentation

1. Show `agents/commands/next-finalize.md` and point out that worker finalize ends with `FINALIZE_READY` only.
2. Show `teleclaude/core/next_machine/core.py` post-completion block and walk through canonical apply (`merge`, `roadmap deliver`, `push`).
3. Show `.githooks/pre-push` and both wrapper templates, highlighting marker strings and the identical remediation text.
4. Run the wrapper tests to demonstrate:
   - worktree push/merge to `main` is blocked,
   - `--no-verify` bypass is still blocked,
   - feature-branch operations still pass.

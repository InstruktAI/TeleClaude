# Review Findings: default-agent-resolution

## Paradigm-Fit Assessment

1. **Data flow**: The implementation follows the established config-driven data layer. Config validation at parse time (`_build_config`), single resolver in `core/agents.py`, and call sites in adapters/hooks/API all route through the core function. No inline hacks or bypass paths.
2. **Component reuse**: `get_default_agent()` is a thin composition of existing `assert_agent_enabled()` and `config.default_agent` — no copy-paste, no duplication.
3. **Pattern consistency**: All call sites follow the identical `f"agent {get_default_agent()}"` pattern. The adapter duck-typing style for Discord `is_pinned`/`edit` uses the same `getattr` + `callable` + `_require_async_callable` pattern established elsewhere in `discord_adapter.py`.

## Why No Critical Issues

- **Paradigm-fit verified**: All 14 call sites route through the single core resolver. The old `_default_agent` property, `_default_agent_name()` function, and `enabled_agents[0]` patterns are deleted. No copy-paste duplication found.
- **Requirements verified**: All 8 success criteria traced to implementation — config validation (3 tests), single resolver (code + 2 tests), zero hardcoded strings (grep verified), zero index patterns (grep verified), zero enum defaults (grep verified), launcher pinning (code + 2 tests), all-forums posting (code change verified), lint/test pass (builder-attested).
- **Deferred items verified**: 3 items in `deferrals.md` all reference non-default-resolution paths (Telegram callback payloads for explicit user selection, transcript parser fallbacks). Each has a documented reason and follow-up action. Deferrals processed: two new todos created (`telegram-callback-payload-migration`, `transcript-parser-fallback-policy`).
- **Remaining `AgentName.CLAUDE` usages verified**: 4 remaining sites (`api_server.py:1100`, `api/streaming.py:125,136`, `utils/transcript.py:1363`, `helpers/agent_cli.py:355`) are parser-selection comparisons and fallbacks, not default-resolution paths. Consistent with deferrals.

## Critical

None.

## Important

1. **Demo block #1 is a non-executable stub** (`demos/default-agent-resolution/demo.md:6-12`): The Python block that should demonstrate config validation failure only contains imports and comments (`# Write a config without agents.default`). It does not actually load a config or trigger the ValueError. This block could pass `demo validate` while exercising nothing. The other 5 demo blocks are valid. Fix: either implement the block with actual config loading and error capture, or replace with a grep/test command that exercises the same validation path.

## Suggestions

1. **Add happy-path assertion for `config.default_agent` propagation** (`tests/unit/test_agent_config_loading.py`): The config validation tests assert rejections but none of the happy-path tests assert `config.default_agent == "test_agent"` after a successful build. Add the assertion to `test_agent_config_loading_defaults` or `test_agent_config_loading_overrides` to prove the value is stored correctly.

2. **Add test for non-string `agents.default` type** (`tests/unit/test_agent_config_loading.py`): The `_build_config` function validates `isinstance(default_agent_raw, str)` at `config/__init__.py:732`. No test exercises the non-string branch (e.g., `agents: { default: 42 }`). Low risk but covers a concrete validation branch.

3. **Replace generator-throw lambda with named function** (`tests/unit/test_command_mapper.py:94`): The `lambda: (_ for _ in ()).throw(ValueError(...))` pattern is clever but obscure. A simple `def _raise(): raise ValueError(...)` is clearer and achieves the same result.

## Verdict: APPROVE

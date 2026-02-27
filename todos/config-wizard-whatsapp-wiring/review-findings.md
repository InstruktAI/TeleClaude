# Review Findings: config-wizard-whatsapp-wiring

**Reviewer:** Claude (automated)
**Review round:** 1
**Date:** 2026-02-26

## Verdict: APPROVE

## Critical

(none)

## Important

(none)

## Suggestions

### S1: `WHATSAPP_BUSINESS_NUMBER` mixes optional and credential env vars in one group

`config_handlers.py:186-191` — `WHATSAPP_BUSINESS_NUMBER` is registered alongside 6 startup credential vars, but is only consumed as an optional invite-link helper in `config_cli.py:256,580`. The config loader (`config/__init__.py:825-830`) does not read it. This matches the pre-existing pattern (`OPENAI_API_KEY` in the `ai` group is similarly optional), so it is not a regression — but future work could benefit from separating informational vars from startup-required credentials.

### S2: Guidance entries cover 4 of 7 env vars — gap is undocumented

`guidance.py` registers `FieldGuidance` for `phone_number_id`, `access_token`, `webhook_secret`, and `verify_token`. The remaining 3 (`template_name`, `template_language`, `business_number`) have no step-by-step guidance. This matches the established pattern (Telegram has 1 of 3, Discord has 1 of 2), and the TUI still renders description/example from `EnvVarInfo` for all 7. The gap is intentional but undocumented — a future test could assert `is None` for the 3 gaps to prevent accidental breakage.

### S3: Discord test timeout markers are out of scope

`test_discord_adapter.py` — Two `@pytest.mark.timeout(5)` decorators were added to pre-existing async tests. These are appropriate (preventing hangs from `asyncio.Event` waits) but technically outside the whatsapp-wiring scope. No negative impact.

### S4: `discover_config_areas` test doesn't assert `adapters.whatsapp` specifically

`test_config_handlers.py:93` — The existing assertion `any(n.startswith("adapters.") for n in names)` would pass even if `whatsapp` were removed from `CredsConfig`. A targeted `assert "adapters.whatsapp" in names` would catch that regression. Low severity since the contract test already covers the spec alignment.

## Paradigm-Fit Assessment

1. **Data flow:** All changes use the established data layer — `EnvVarInfo` in `_ADAPTER_ENV_VARS`, `FieldGuidance` in `GuidanceRegistry`, `AdapterConfigComponent` base class. No inline hacks, no filesystem bypasses.
2. **Component reuse:** `WhatsAppConfigComponent` extends `AdapterConfigComponent` identically to `TelegramConfigComponent` and `DiscordConfigComponent`. No copy-paste duplication.
3. **Pattern consistency:** Env var registration, guidance entries, sample config, and spec updates all follow the exact patterns established by Telegram, Discord, and Redis. Naming conventions and structure are consistent throughout.

## Requirements Tracing

| Requirement                              | Evidence                                                                            |
| ---------------------------------------- | ----------------------------------------------------------------------------------- |
| Env var registry with 7 WhatsApp vars    | `config_handlers.py:148-191` — all 7 match `config/__init__.py` and `config_cli.py` |
| Component wiring passes `["whatsapp"]`   | `adapters.py:148` — changed from `[]` to `["whatsapp"]`                             |
| Guidance entries for setup fields        | `guidance.py:62-117` — 4 entries matching plan                                      |
| `config.sample.yml` whatsapp section     | Lines 66-75 — `${VAR}` interpolation matching Discord/Redis                         |
| Config spec updated                      | `teleclaude-config.md` — 8 config keys + 7 env vars added                           |
| `telec config validate` reports WhatsApp | Builder verified in build notes; confirmed by test suite (2286 passed)              |
| No regressions                           | `make test`: 2286 passed, 106 skipped, 0 failures                                   |

## Why No Issues

1. **Paradigm-fit verified:** Checked all 5 changed source files against their adjacent adapter patterns (Telegram, Discord, Redis). Every registration follows the identical structure — same dataclass, same constructor pattern, same guidance format.
2. **Env var names verified:** Cross-referenced all 7 env var names against `teleclaude/config/__init__.py:825-830` (6 vars) and `teleclaude/cli/config_cli.py:256,580` (1 var). All names match exactly.
3. **Copy-paste duplication checked:** `WhatsAppConfigComponent` is a 3-line class extending `AdapterConfigComponent` — no duplication. Guidance entries use the same `FieldGuidance` dataclass. No parallel structures created.
4. **Contract test alignment:** `test_contracts.py` updated to include `"whatsapp"` in the required config keys set, matching the spec update. Exact-set assertion catches both missing and extra keys.
5. **Build evidence:** 2286 tests pass, lint passes, all implementation-plan tasks checked.

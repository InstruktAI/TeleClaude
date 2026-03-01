# Implementation Plan: config-wizrd-enrichment

## Overview

Two-phase approach: (1) complete the guidance data layer, (2) wire it into the TUI rendering.
The GuidanceRegistry already has the right structure — we fill the gaps and connect it to the view.

## Phase 1: Guidance Data Completeness

### Task 1.1: Add `_ENV_TO_FIELD` mapping to guidance.py

**File(s):** `teleclaude/cli/tui/config_components/guidance.py`

- [ ] Add `_ENV_TO_FIELD: dict[str, str]` mapping every env var name to its field path
- [ ] Add `get_guidance_for_env(env_var_name: str) -> FieldGuidance | None` convenience function
- [ ] Covers all entries from `_ADAPTER_ENV_VARS` in config_handlers.py

### Task 1.2: Complete GuidanceRegistry entries for all missing env vars

**File(s):** `teleclaude/cli/tui/config_components/guidance.py`

- [ ] TELEGRAM_SUPERGROUP_ID — steps for creating/finding supergroup, getting chat ID
- [ ] TELEGRAM_USER_IDS — steps for finding Telegram user IDs
- [ ] DISCORD_GUILD_ID — steps for enabling developer mode, copying server ID
- [ ] ANTHROPIC_API_KEY — steps for Anthropic console, API key creation
- [ ] OPENAI_API_KEY — steps for OpenAI platform, API key creation
- [ ] ELEVENLABS_API_KEY — steps for ElevenLabs dashboard, API key
- [ ] REDIS_PASSWORD — steps for Redis setup (local or hosted)
- [ ] WHATSAPP_TEMPLATE_NAME — steps for Meta template setup
- [ ] WHATSAPP_TEMPLATE_LANGUAGE — format guidance
- [ ] WHATSAPP_BUSINESS_NUMBER — steps for getting business phone number

---

## Phase 2: TUI Integration

### Task 2.1: Render inline guidance in ConfigView

**File(s):** `teleclaude/cli/tui/views/config.py`

- [ ] Import guidance lookup function
- [ ] In `_render_adapters` and `_render_environment`: when a var is selected (cursor on it), render expanded guidance block below it
- [ ] Guidance block shows: numbered steps, URL (as OSC 8 link), format example, validation hint
- [ ] Use Rich `Text` with `Style` for visual hierarchy (steps dimmed, URL in info color, example in code style)
- [ ] Guidance collapses when cursor moves to different var

### Task 2.2: OSC 8 hyperlink rendering

**File(s):** `teleclaude/cli/tui/views/config.py`

- [ ] Render URLs using Rich's `[link=URL]text[/link]` markup or `Text.append` with `Style(link=url)`
- [ ] Verify fallback behavior in terminals without OSC 8 support

### Task 2.3: Guided mode auto-expand integration

**File(s):** `teleclaude/cli/tui/views/config.py`

- [ ] When guided mode lands on an adapter step, find the first unset var and position cursor on it
- [ ] This naturally triggers guidance expansion from Task 2.1
- [ ] Existing `_auto_advance_completed_steps` logic remains unchanged

---

## Phase 3: Validation

### Task 3.1: Tests

- [ ] Test `_ENV_TO_FIELD` mapping covers all `_ADAPTER_ENV_VARS` entries
- [ ] Test `get_guidance_for_env` returns correct guidance for known vars, None for unknown
- [ ] Test guidance rendering output contains expected elements (steps, URL, format)
- [ ] Run `make test`

### Task 3.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Manual TUI verification: navigate adapters tab, verify guidance expands/collapses

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

---

## Appendix: Verified Guidance Content (from peer research)

| Env Var | Field Path | Steps | URL | Format |
|---|---|---|---|---|
| `TELEGRAM_SUPERGROUP_ID` | `adapters.telegram.supergroup_id` | Add bot to group → message @RawDataBot or call getUpdates → grab `chat.id` | `https://api.telegram.org/bot<TOKEN>/getUpdates` | `-1001234567890` |
| `TELEGRAM_USER_IDS` | `adapters.telegram.user_ids` | Message @userinfobot from each account → copy numeric ID | `https://t.me/userinfobot` | `123456789,987654321` |
| `DISCORD_GUILD_ID` | `adapters.discord.guild_id` | Settings → Advanced → Developer Mode → right-click server → Copy Server ID | `https://discord.com/settings` | `123456789012345678` |
| `ANTHROPIC_API_KEY` | `adapters.ai.anthropic_api_key` | Console → API Keys → Create Key | `https://console.anthropic.com/settings/keys` | `sk-ant-api03-...` |
| `OPENAI_API_KEY` | `adapters.ai.openai_api_key` | Platform → API keys → Create new secret key | `https://platform.openai.com/api-keys` | `sk-proj-...` |
| `ELEVENLABS_API_KEY` | `adapters.voice.elevenlabs_api_key` | Profile → API Keys → copy or generate | `https://elevenlabs.io/app/profile-settings` | `sk_...` |
| `REDIS_PASSWORD` | `adapters.redis.password` | Redis Cloud: database → Security → copy password. Self-hosted: `requirepass` in redis.conf | `https://app.redislabs.com/` | password string |
| `WHATSAPP_TEMPLATE_NAME` | `adapters.whatsapp.template_name` | Business Manager → WhatsApp → Message Templates → approved template name | `https://business.facebook.com/wa/manage/message-templates/` | `hello_world` |
| `WHATSAPP_TEMPLATE_LANGUAGE` | `adapters.whatsapp.template_language` | Same templates view → Language column | (same as above) | `en_US` |
| `WHATSAPP_BUSINESS_NUMBER` | `adapters.whatsapp.business_number` | Your WhatsApp Business phone number in E.164 format | (Meta dashboard) | `+1234567890` |

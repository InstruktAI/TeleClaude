# Implementation Plan: config-wizard-whatsapp-wiring

## Overview

Pure wiring task: register WhatsApp env vars in the adapter registry, fix the component constructor, add guidance entries, update sample config, and update the config spec. All changes follow existing patterns with zero novel logic.

## Phase 1: Core Wiring

### Task 1.1: Add WhatsApp env vars to the adapter registry

**File(s):** `teleclaude/cli/config_handlers.py`

- [x] Add `"whatsapp"` key to `_ADAPTER_ENV_VARS` dict (after the `"redis"` entry, line ~148)
- [x] Register these `EnvVarInfo` entries:
  - `WHATSAPP_PHONE_NUMBER_ID` / `"whatsapp"` / `"Business phone number ID from Meta"` / `"123456789012345"`
  - `WHATSAPP_ACCESS_TOKEN` / `"whatsapp"` / `"System user token (long-lived)"` / `"EAAx..."`
  - `WHATSAPP_WEBHOOK_SECRET` / `"whatsapp"` / `"App secret for webhook signature verification"` / `"abc123..."`
  - `WHATSAPP_VERIFY_TOKEN` / `"whatsapp"` / `"Random string for webhook challenge-response"` / `"my-verify-token"`
  - `WHATSAPP_TEMPLATE_NAME` / `"whatsapp"` / `"Template name for 24h window boundary messages"` / `"hello_world"`
  - `WHATSAPP_TEMPLATE_LANGUAGE` / `"whatsapp"` / `"Template language code"` / `"en_US"`
  - `WHATSAPP_BUSINESS_NUMBER` / `"whatsapp"` / `"Business phone number for invite deep links"` / `"+1234567890"`

### Task 1.2: Fix WhatsAppConfigComponent wiring

**File(s):** `teleclaude/cli/tui/config_components/adapters.py`

- [x] Change line 148: `super().__init__(callback, "adapters.whatsapp", "WhatsApp", [])` → `super().__init__(callback, "adapters.whatsapp", "WhatsApp", ["whatsapp"])`

### Task 1.3: Add WhatsApp setup guidance

**File(s):** `teleclaude/cli/tui/config_components/guidance.py`

- [ ] Add guidance entries in `_populate_defaults()` after the Discord entries (line ~62), following the same `FieldGuidance` pattern:
  - `adapters.whatsapp.phone_number_id` — steps: create Meta Business app, add WhatsApp product, get phone number ID from dashboard
  - `adapters.whatsapp.access_token` — steps: create system user in Business Manager, generate token with whatsapp_business_messaging permission
  - `adapters.whatsapp.webhook_secret` — steps: find App Secret in Meta App Dashboard > Settings > Basic
  - `adapters.whatsapp.verify_token` — steps: generate random string, use same value in Meta webhook config

## Phase 2: Config & Docs

### Task 2.1: Add WhatsApp section to config.sample.yml

**File(s):** `config.sample.yml`

- [ ] Add `whatsapp:` section after the `discord:` block (before `redis:`), containing:
  ```yaml
  whatsapp:
    enabled: false
    phone_number_id: ${WHATSAPP_PHONE_NUMBER_ID}
    access_token: ${WHATSAPP_ACCESS_TOKEN}
    webhook_secret: ${WHATSAPP_WEBHOOK_SECRET}
    verify_token: ${WHATSAPP_VERIFY_TOKEN}
    api_version: v21.0
    template_name: ${WHATSAPP_TEMPLATE_NAME}
    template_language: en_US
  ```

### Task 2.2: Update teleclaude-config spec

**File(s):** `docs/project/spec/teleclaude-config.md`

- [ ] Add to `config_keys` section:
  ```yaml
  whatsapp:
    enabled: boolean
    phone_number_id: string
    access_token: string
    webhook_secret: string
    verify_token: string
    api_version: string
    template_name: string
    template_language: string
  ```
- [ ] Add to `environment_variables` list:
  - `WHATSAPP_PHONE_NUMBER_ID`
  - `WHATSAPP_ACCESS_TOKEN`
  - `WHATSAPP_WEBHOOK_SECRET`
  - `WHATSAPP_VERIFY_TOKEN`
  - `WHATSAPP_TEMPLATE_NAME`
  - `WHATSAPP_TEMPLATE_LANGUAGE`
  - `WHATSAPP_BUSINESS_NUMBER`

---

## Phase 3: Validation

### Task 3.1: Tests

- [ ] Run `make test` — verify no regressions
- [ ] Manually verify TUI renders WhatsApp env vars (SIGUSR2 reload)

### Task 3.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify `telec config validate` reports WhatsApp env vars
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

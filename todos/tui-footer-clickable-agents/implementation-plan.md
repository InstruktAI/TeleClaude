# Implementation Plan: tui-footer-clickable-agents

## Overview

Add clickable agent pills to the TUI StatusBar by: (1) adding `degraded_until` to the data model so degraded state can auto-expire, (2) adding a new API endpoint for setting agent status, (3) adding the corresponding API client method, (4) tracking agent pill positions during render, and (5) handling clicks to cycle status via the API. The approach preserves the semantic distinction between degraded (manual-only, still selectable) and unavailable (fully disabled).

## Phase 1: Data Model — `degraded_until`

### Task 1.1: Add `degraded_until` column to db model

**File(s):** `teleclaude/core/db_models.py`

- [x] Add `degraded_until: Optional[str] = None` to the `AgentAvailability` model

### Task 1.2: Update `mark_agent_degraded` to accept `degraded_until`

**File(s):** `teleclaude/core/db.py`

- [x] Add `degraded_until: str | None = None` parameter to `mark_agent_degraded`
- [x] Set `row.degraded_until = degraded_until` alongside existing reason logic
- [x] In `mark_agent_available`, also clear `degraded_until` (set to `None`)

### Task 1.3: Update expiry logic to clear expired degraded agents

**File(s):** `teleclaude/core/db.py`

- [x] In `clear_expired_agent_availability`, add a second update statement (or extend the existing one) to also reset agents whose `degraded_until` is non-null and past — set `available=1, degraded_until=None, reason=None`

### Task 1.4: Expose `degraded_until` in DTOs

**File(s):** `teleclaude/api_models.py`, `teleclaude/cli/models.py` (if `AgentAvailabilityInfo` lives there)

- [x] Add `degraded_until: str | None = None` to `AgentAvailabilityDTO`
- [x] Add `degraded_until: str | None = None` to `AgentAvailabilityInfo` (client model)
- [x] Update the `GET /agents/availability` handler in `api_server.py` to populate `degraded_until` from the db row

## Phase 2: API Layer

### Task 2.1: Add POST endpoint for agent status

**File(s):** `teleclaude/api_server.py`

- [x] Add `POST /agents/{agent}/status` endpoint accepting JSON body `{ "status": "available" | "degraded" | "unavailable", "reason": str | null, "duration_minutes": int | null }`
- [x] For available: call `db.mark_agent_available(agent)`
- [x] For degraded: compute `degraded_until` from `duration_minutes` (default 60), call `db.mark_agent_degraded(agent, reason, degraded_until=degraded_until)`
- [x] For unavailable: compute `unavailable_until` from `duration_minutes` (default 60), call `db.mark_agent_unavailable(agent, unavailable_until, reason)`
- [x] Re-fetch and return the updated `AgentAvailabilityDTO` for the agent

### Task 2.2: Add API client method

**File(s):** `teleclaude/cli/api_client.py`

- [x] Add `async def set_agent_status(self, agent: str, status: str, reason: str | None = None, duration_minutes: int = 60) -> AgentAvailabilityInfo`
- [x] POST to `/agents/{agent}/status` with the appropriate JSON body
- [x] Parse and return the updated availability info

## Phase 3: TUI Click Handling

### Task 3.1: Track agent pill positions in StatusBar

**File(s):** `teleclaude/cli/tui/widgets/status_bar.py`

- [x] Add instance field `_agent_regions: list[tuple[int, int, str]]` to track `(start_x, end_x, agent_name)` for each rendered pill
- [x] In `render()`, record each agent pill's start and end x-positions based on `line.cell_len` before and after appending
- [x] Reset regions at the start of each render call

### Task 3.2: Handle agent pill clicks

**File(s):** `teleclaude/cli/tui/widgets/status_bar.py`

- [x] In `on_click()`, check if click x falls within any agent region before checking toggle regions
- [x] If agent region hit, post `SettingsChanged("agent_status", {"agent": agent_name})`
- [x] The cycle logic (determining the _next_ status) lives in the app handler, not the widget

### Task 3.3: Handle agent status change in app

**File(s):** `teleclaude/cli/tui/app.py`

- [x] In `on_settings_changed`, add handler for key `"agent_status"`
- [x] Extract agent name from `message.value`
- [x] Look up current status from the `StatusBar` widget's `_agent_availability` dict
- [x] Determine next status: available → degraded, degraded → unavailable, unavailable → available
- [x] Call `self.api.set_agent_status(agent, next_status, reason="manual", duration_minutes=60)`
- [x] On success, update the StatusBar's `_agent_availability` for that agent from the API response and call `status_bar.refresh()`
- [x] On failure, show error notification

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Add or update tests for the API endpoint
- [x] Add or update tests for the status cycle logic
- [x] Add or update tests for `clear_expired_agent_availability` covering `degraded_until`
- [x] Run `make test`

### Task 4.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)

# Discord Adapter Message Integrity

## Problem Statement

The Discord adapter has multiple output delivery issues causing incomplete session mirroring. Sessions visible in the TUI show full output but Discord shows gaps — missing text blocks, skipped events, and stale metadata.

## Specific Issues

### 1. Missing text output between tool calls (CRITICAL)

When threaded output mode is active, the poller (`send_output_update`) is suppressed on Discord. But the incremental renderer (`_maybe_send_incremental_output`) only fires on hook events: `tool_use`, `tool_done`, `agent_stop`. Text written between tools (reasoning, explanations, user-facing prose) has NO trigger to deliver it to Discord.

**Root cause**: `agent_coordinator.py` only calls `_maybe_send_incremental_output` from hook event handlers. There is no text-streaming trigger for threaded output mode.

**Evidence**: Session `514ff3f2` — Discord shows tool call summaries (`len=77`, `len=143`) but not the multi-paragraph text blocks visible in TUI.

### 2. Agent status not synced to Discord

The active agent information visible in TUI (agent name, thinking mode) is not reflected in Discord threads. Discord threads don't show which agent is active or update when agents change.

### 3. Output appears debounced/skipped

Observations suggest that rapid successive events cause some output to be dropped or deduplicated when it shouldn't be. The `last_output_digest` check (line 741 of agent_coordinator.py) may over-aggressively skip sends.

### 4. Stale `all_sessions_channel_id` caused misrouting

The provisioning code (`_ensure_discord_infrastructure`) only creates the catch-all forum when `all_sessions_channel_id is None`. When the old channel was deleted during restructuring, the config still held the stale ID, causing all non-project-matched sessions to 404 silently. This was fixed in this session but the provisioning code should validate existing IDs.

**Fixed inline**: Cleared stale config, daemon auto-provisioned new Unknown forum.

### 5. Single "Projects" category doesn't support multi-computer setups

The current provisioning creates one "Projects" category for all project forums. When multiple computers (MozBook, mozmini, raspi) each have their own trusted_dirs, all their forums end up under the same category with no visual separation. Each computer should provision its own "Projects - {computer_name}" category so sessions from different machines are clearly separated in the Discord guild.

## Proposed Solutions

### For issue 1 (missing text)

The poller already streams text continuously. For Discord in threaded mode, instead of suppressing the poller entirely, the poller should ALSO render through the threaded renderer — or the incremental output should be triggered by poller events, not just hook events.

Options:

- A) Remove poller suppression for Discord when threaded output is active; let both paths contribute
- B) Have the poller trigger `_maybe_send_incremental_output` when threaded mode is active
- C) Add a periodic timer that renders incremental output independent of hook events

### For issue 4 (stale channel validation)

Add a validation step in `_ensure_discord_infrastructure` that checks if configured channel IDs actually resolve to live Discord channels. If not, clear the stale ID and re-provision.

## Files Involved

- `teleclaude/core/agent_coordinator.py` — incremental output trigger logic
- `teleclaude/adapters/ui_adapter.py` — poller suppression logic (`send_output_update`)
- `teleclaude/adapters/discord_adapter.py` — thread creation, routing, infrastructure provisioning
- `teleclaude/utils/transcript.py` — output rendering

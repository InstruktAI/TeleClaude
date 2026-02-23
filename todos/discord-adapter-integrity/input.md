# Discord Adapter Integrity

## Problem Statement

The Discord adapter has infrastructure reliability issues, lacks multi-computer separation, and silently drops admin input from project forums.

## Specific Issues

### 1. Stale channel IDs cause misrouting

The provisioning code (`_ensure_discord_infrastructure`) only creates channels when the stored ID is None. When an existing channel is deleted from Discord, the config still holds the stale ID, causing silent 404s. The `_ensure_category` method already validates cached IDs — this pattern must extend to all channel ID guards.

### 2. Single "Projects" category doesn't support multi-computer setups

The current provisioning creates one "Projects" category for all project forums. When multiple computers each have their own trusted_dirs, all forums end up under the same category with no visual separation. Each computer should provision its own "Projects - {computer_name}" category.

### 3. Forum input silently dropped — hardcoded customer role (CRITICAL)

When a user sends a message in a Discord project forum, `_create_session_for_message` (line 1374) hardcodes `human_role: "customer"`. The session creates and tmux opens (via `auto_command`), but then the customer gate at line 1039 blocks the input because the message is from a project forum, not help desk.

**Root cause:** `_create_session_for_message` was built for help desk customer intake but is the fallback for ALL forum message types. It:

- Hardcodes `human_role: "customer"` (should resolve identity like DM handler at line 896)
- Hardcodes `project_path=config.computer.help_desk_dir` (should resolve from forum → project mapping)

**Evidence:** Sending a message in any project forum creates a tmux session visible in TUI but delivers no input. Zero logs of the `process_message` call because `_handle_on_message` has no entry-level logging.

## Files Involved

- `teleclaude/adapters/discord_adapter.py` — all changes in this file

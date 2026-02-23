# Requirements: discord-adapter-integrity

## Goal

Fix Discord adapter infrastructure and input routing so that the Discord guild is reliable, correctly partitioned per computer, and admin input from forums is routed correctly.

## Scope

### In scope

1. **Infrastructure validation** — `_ensure_discord_infrastructure` validates that stored channel/forum IDs resolve to live Discord channels before trusting them. Stale IDs are cleared and re-provisioned.
2. **Per-computer project categories** — each computer provisions its own "Projects - {computer_name}" category in Discord. Each computer's trusted_dirs forums live under its own category. Sessions from different computers are visually separated.
3. **Forum input routing** — `_create_session_for_message` must resolve identity (role from people config, not hardcoded "customer") and project path (from forum mapping, not hardcoded help_desk_dir). Admin messages in project forums must not be silently dropped by the customer gate. Entry-level logging in `_handle_on_message` for debuggability.

### Out of scope

- Agent status sync to Discord threads (separate todo).
- Text delivery between tool calls (separate todo: `adapter-output-delivery`).
- User input reflection across adapters (separate todo: `adapter-output-delivery`).
- Telegram-specific UI polish.

## Success Criteria

- [ ] Deleting a Discord forum and restarting the daemon causes automatic re-provisioning (no silent 404s).
- [ ] Two computers (e.g. MozBook and mozmini) each have their own "Projects - MozBook" and "Projects - mozmini" categories with their respective project forums.
- [ ] Sessions route to the correct computer-specific project forum.
- [ ] Admin sending a message in a project forum creates a session with correct role (not "customer") and correct project path (from forum mapping, not help_desk_dir).
- [ ] Admin input in project forums is delivered to the tmux session (not silently dropped).
- [ ] `_handle_on_message` produces entry-level DEBUG logs for all incoming messages, including dropped ones.

## Constraints

- Daemon availability policy: restarts must be brief and verified via `make restart` / `make status`.
- All changes in `teleclaude/adapters/discord_adapter.py` only.

## Risks

- Per-computer categories change the Discord guild layout. Existing forum threads under the old single "Projects" category will need manual migration or will remain orphaned under the old category.

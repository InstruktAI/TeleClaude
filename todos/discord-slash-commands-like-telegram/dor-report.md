# DOR Report: discord-slash-commands-like-telegram

## Assessment: GATE PASS

### Gate 1: Intent & Success

**Status:** Pass

Problem statement is explicit: Discord adapter lacks slash commands that Telegram has. Goal, scope, and 14 testable success criteria in requirements.md cover all command categories (key commands, agent commands, session commands, help). Each criterion describes observable behavior.

### Gate 2: Scope & Size

**Status:** Pass

Atomic change: 3 new files (package init, command handlers mixin, tests), 1 modified (discord_adapter.py). Follows established Telegram mixin pattern. No cross-cutting changes. Fits a single AI session.

### Gate 3: Verification

**Status:** Pass

- Unit tests for handler methods and slash command registration.
- Integration test for interaction → dispatch flow.
- Automated demo scripts (import check, CommandTree creation, make test, make lint).
- Guided presentation with 7 observable steps.

### Gate 4: Approach Known

**Status:** Pass

- `discord.py >= 2.4.0` `app_commands.CommandTree` is proven and stable.
- `CommandTree` attaches to `discord.Client` without switching to `commands.Bot`.
- Guild-scoped sync provides instant availability.
- Telegram `CommandHandlersMixin` pattern is established in codebase.
- Existing `_find_session()`, `_dispatch_command()`, and `CommandService` provide the execution path.

### Gate 5: Research Complete

**Status:** Pass

- `discord.py` is existing project dependency.
- `app_commands` module is part of discord.py, not a new library.
- No new third-party dependencies.
- Guild-scoped registration avoids the 1-hour global sync delay.

### Gate 6: Dependencies & Preconditions

**Status:** Pass

- `after: discord-session-routing` set in roadmap.yaml.
- All infrastructure exists: `UiCommands`, `CommandService`, `UiAdapter._dispatch_command()`, `db.get_sessions_by_adapter_metadata()`.
- No missing configs or environments.

### Gate 7: Integration Safety

**Status:** Pass

- Additive mixin — existing `_handle_on_message` flow untouched.
- Slash commands create a parallel input path alongside text messages.
- `_dispatch_command` handles cross-adapter broadcasting automatically.
- Rollback: remove mixin from inheritance chain and tree setup.

### Gate 8: Tooling Impact

**Status:** N/A (no tooling changes)

## Gate Tightenings Applied

1. **Task 2.1 metadata key**: Fixed from `"channel_id"` to `"thread_id"` and aligned with existing `_find_session()` pattern.
2. **Task 3.2 interaction routing**: Replaced contradictory instruction with clear conditional (verify auto-dispatch, fallback to manual registration).
3. **Authorization model**: Replaced "whitelist" reference with correct managed-forum gating pattern matching existing Discord adapter behavior.

## Open Questions (Non-blocking)

1. **`/new_session` context**: Auto-select project from forum-to-project mapping (reasonable default from `_project_forum_map`).
2. **Authorization**: Uses managed-forum gating (existing pattern). No user whitelist needed.

## Assumptions

- `CommandTree` can be attached to `discord.Client` — standard discord.py pattern.
- Guild ID is always configured when Discord adapter is enabled.
- Discord slash command names support underscores (`^[-\w]{1,32}$`).
- Ephemeral responses are sufficient for command feedback.

## Final Score: 8/10

All 8 DOR gates pass. Plan traces to requirements without contradictions. Minor tightenings applied. Ready for build phase.

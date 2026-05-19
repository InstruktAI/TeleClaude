---
id: project/spec/feature/integration/headless-session-bootstrap-from-hook
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: When an agent_session_start hook arrives for a session the daemon has never seen, the dispatcher creates a headless session row inline from the hook payload before continuing normal event dispatch.
---

# Headless Session Bootstrap from Hook — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The daemon hook outbox dispatcher's just-in-time session creation path.
When the dispatcher claims an `AGENT_SESSION_START` row for a session id
the sessions table does not yet contain, instead of dropping the event the
dispatcher synthesizes a `CreateSessionCommand` from the hook payload (cwd,
native session id, transcript path, agent, caller-email identity) and
creates the session row before continuing dispatch.

The bootstrap is "headless" because the resulting session has no live tmux
process supervised by the daemon — only a database row. The agent CLI was
already running when the hook fired; the daemon catches up by recording the
session's existence after the fact. This makes agent CLIs invoked outside
the daemon's launch flow (manual `claude`, `codex`, `gemini` invocations
from a terminal) observable as TeleClaude sessions.

## Canonical fields

### Use cases

#### UC-HB1: Manual agent invocation registers a headless session

```gherkin
Given a user runs `claude` manually in /Users/me/work/myproject
And the user is authenticated via teleclaude session auth in this TTY
And Claude invokes telec-hook ... --cwd /Users/me/work/myproject SessionStart
And the daemon has no session row for this native session
When the dispatcher claims the AGENT_SESSION_START outbox row
Then _dispatch_hook_event detects db.get_session returns None
And the event_type is AgentHookEvents.AGENT_SESSION_START
And _ensure_headless_session runs
And it reads native_log_file, native_session_id, agent_name, cwd from the hook payload
And _resolve_headless_project_context maps cwd to (project_path, subdir) using config.computer.get_all_trusted_dirs()
And read_current_session_email returns the authenticated caller's email if any
And a CreateSessionCommand is built with headless=True, the native binding fields, project context, origin=InputOrigin.TERMINAL, caller-email metadata
And get_command_service().create_session(cmd) creates the row
And event_bus.emit(SESSION_STARTED, ...) fires with EventVisibility.CLUSTER
And _dispatch_hook_event continues normal dispatch for the now-existing session
```

#### UC-HB2: Non-session-start event for unknown session is dropped

```gherkin
Given a TOOL_USE outbox row arrives for a session_id db.get_session does not find
And the event_type is NOT AgentHookEvents.AGENT_SESSION_START
When _dispatch_hook_event runs
Then a debug log records "Ignoring hook event for unknown session (not session_start)"
And the function returns early without bootstrap
And the outbox row is deleted as processed (no retry)
```

#### UC-HB3: Untrusted cwd produces null project context

```gherkin
Given the hook cwd is /tmp/some-random-dir not under any configured trusted_dirs
When _resolve_headless_project_context runs
Then split_project_path_and_subdir returns (None, None)
And the CreateSessionCommand is built with project_path=""
And the session is created without a project association
And subsequent hooks still update the row but no project-scoped behaviors (memory, person header) fire
```

#### UC-HB4: Caller email role assignment

```gherkin
Given read_current_session_email returns "mo@example.com"
When _ensure_headless_session builds the CreateSessionCommand
Then origin_metadata is TerminalOriginMetadata(email="mo@example.com")
And human_role is left None (allowing config role resolution)
Otherwise (no email): human_role defaults to HUMAN_ROLE_CUSTOMER
```

#### UC-HB5: Worktree subdir captured from cwd

```gherkin
Given the cwd is /Users/me/work/myproject/trees/feature-x
And /Users/me/work/myproject is a trusted_dir
When _resolve_headless_project_context runs
Then project_path = "/Users/me/work/myproject", subdir = "trees/feature-x"
And the CreateSessionCommand carries both
And the session row reflects the worktree branch
```

#### UC-HB6: SESSION_STARTED event fires after creation

```gherkin
Given _ensure_headless_session successfully created a session row
When the bootstrap completes
Then event_bus.emit(TeleClaudeEvents.SESSION_STARTED, SessionLifecycleContext(...)) is invoked
And EventVisibility.CLUSTER ensures downstream cluster consumers see the new session
And UI watchers, agent_runtime live-state, and notification subscribers all observe the bootstrap
```

#### UC-HB7: Creation failure raises and triggers retry

```gherkin
Given get_command_service().create_session fails to return a session_id
When _ensure_headless_session attempts to load the session row by the returned id
And db.get_session returns None
Then a ValueError("Headless session creation returned missing session: ...") is raised
And the dispatcher's _is_retryable_hook_error returns True (the message does NOT contain "not found")
And the row is rescheduled with exponential backoff
```

### Implementation pointers (v1)

- `teleclaude/daemon_hook_outbox.py` —
  `_ensure_headless_session` (L365),
  `_resolve_headless_project_context` (L415),
  the bootstrap fork inside `_dispatch_hook_event` (L442) at the
  `if not session:` branch.
- `teleclaude/core/command_registry.py` — `get_command_service` →
  `create_session` command handler.
- `teleclaude/types/commands.py` — `CreateSessionCommand` schema.
- `teleclaude/core/models/_adapter.py` — `TerminalOriginMetadata`.
- `teleclaude/core/origins.py` — `InputOrigin.TERMINAL`.
- `teleclaude/core/session_utils.py` — `split_project_path_and_subdir`
  trusted-dir resolution.
- `teleclaude/cli/session_auth.py` — `read_current_session_email`
  (TTY-bound path then global identity fallback).
- `teleclaude/core/models.py` — `Session`, `SessionLaunchIntent`,
  `SessionLaunchKind`.

### Cross-context references

- Belongs (in v2) to `agent_runtime` along with the session aggregate.
  Bootstrap remains a property of session creation, not of integration.
- Reads identity context (caller email) via the auth subsystem;
  resolution rules live in `identity`.
- Reads trusted-dirs from `config` (computer.get_all_trusted_dirs).
- Emits a `SESSION_STARTED` EventBus event with CLUSTER visibility;
  downstream consumers include the API server, frontends, and any
  notification dispatcher.

## Known caveats

- The native_session_id is captured at bootstrap time but the session
  row is not yet linked to a tmux process — `agent_runtime` supervision
  cannot reattach to a manually started agent CLI after the fact.
- Codex sub-agent transcripts are filtered earlier (the receiver drops
  subagent events pre-resolution); they never reach this bootstrap.
- `read_current_session_email` resolution order is: (1) per-TTY auth file
  under `SESSION_AUTH_DIR/<tty_key>.json` if a TTY is detectable, then
  (2) the global identity file at `_global_auth_path()` as a fallback.
  Running the agent CLI in a subshell that loses TTY context falls
  through to the global identity file; only when both are absent does
  `read_current_session_email` return `None`, in which case the bootstrap
  builds the command with `human_role=HUMAN_ROLE_CUSTOMER`.
- `_resolve_headless_project_context` returns `(None, None)` for any cwd
  not under a configured trusted_dir; the session is still created,
  just without a project association.
- The bootstrap path is taken once per session; subsequent hooks for the
  same session_id find the row and skip directly to normal dispatch.
- Bootstrap failures retry with the dispatcher's exponential backoff;
  a stuck `AGENT_SESSION_START` row will eventually accumulate
  attempt_count and reach the dead-letter region of the configured
  backoff cap.

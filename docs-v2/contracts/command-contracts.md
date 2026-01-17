# Command Contracts (Internal)

These describe internal command payloads. The REST API translates its public request
shapes into these internal commands.

## create_session

**Required:** `project_path`  
**Optional:** `subdir`, `title`, `agent`, `thinking_mode`, `message`, `native_session_id`

**Implicit behavior:**
- no `agent` + no `message` → empty tmux session
- `agent` present → start agent
- `agent` + `message` → start agent, then inject message
- `native_session_id` present → resume agent (agent required)
- `message` without `agent` → inject message into tmux session

**Emitted events:**
- `session_created`
- `agent_ready` (if agent started)
- `task_delivered` (if message injected after agent ready)
- `agent_resumed` (if native_session_id used)
- `message_delivered` (if message injected without agent)

---

## agent_restart

**Required:** `session_id`, `agent`

**Emitted events:**
- `agent_restarted`

---

## agent_command

**Required:** `session_id`, `agent`, `command_text`

**Emitted events:**
- `command_delivered`

---

## send_message

**Required:** `session_id`, `message_text`

**Emitted events:**
- `message_delivered`

---

## end_session

**Required:** `session_id`

**Emitted events:**
- `session_closed`

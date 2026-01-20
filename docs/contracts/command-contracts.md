# Command Contracts

## new_session

**Required:** `project_path`  
**Optional:** `subdir`, `title`, `launch_intent`

**Implicit behavior (via `launch_intent`):**
- `kind: EMPTY` → empty tmux session
- `kind: AGENT` → start agent (`agent`, `thinking_mode` required)
- `kind: AGENT_THEN_MESSAGE` → start agent, wait for stabilization, then inject `message`
- `kind: AGENT_RESUME` → resume agent (`agent` required, `native_session_id` optional)

**Emitted events:**
- `session_created`
- `agent_event` (with `event_type="session_start"`) if agent started
- `session_updated` when agent details or title change

---

## agent_restart

**Required:** `session_id`  
**Optional:** `agent`

**Behavior:**
- Kills existing agent process (SIGINT x2)
- Resumes agent using stored `native_session_id`

**Emitted events:**
- `session_updated` (when agent process starts)

---

## message

**Required:** `session_id`, `text`

**Behavior:**
- Injects `text` followed by `ENTER` into the session's tmux pane.
- Triggers output polling.

**Emitted events:**
- `session_updated` (updates `last_message_sent`)

---

## kill / cancel / cancel2x

**Required:** `session_id`

**Behavior:**
- `kill`: Sends `SIGKILL`.
- `cancel`: Sends `SIGINT`.
- `cancel2x`: Sends `SIGINT` twice.

---

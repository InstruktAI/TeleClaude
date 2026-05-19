---
id: 'project/spec/feature/agent_runtime/session-input-delivery'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Delivers operator and orchestrator input (text messages and keystrokes) into running agent sessions via the daemon''s tmux paste-buffer pipeline.'
---

# Session Input Delivery — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The write-side surface that lets operators, orchestrators, and other agents inject input into a running agent session. Two endpoints share the same downstream tmux pipeline:

- **`POST /sessions/{id}/message`** — structured message. The daemon resolves the target session, optionally wraps the payload with a caller-origin header (machine roles only), enqueues a `message` command through `CommandService.process_message`, and ultimately delivers the text to the agent's tmux pane via the paste-buffer pipeline. This is the path the CLI uses for `telec sessions send`.
- **`POST /sessions/{id}/keys`** — raw key command. Routed through `CommandMapper`/`CommandService.keys`; used for special keys (Enter, BSpace, Up/Down, Tab, Ctrl-C, etc.) and key repeats via `request.count`.

Both paths converge on the tmux bridge in `teleclaude/core/tmux_bridge/_keys.py`, which speaks tmux's `load-buffer` / `paste-buffer -p -r` / discrete `send-keys C-m` sequence so multi-line payloads land as a single bracketed-paste event and are submitted with one Enter. Voice, file, result, widget, and escalate endpoints live next door (`sessions_actions_routes.py`) but belong to integration/messaging — see "Known caveats".

## Canonical fields

### Behavioral contract

#### Structured message — happy path

```
Given an authenticated caller POSTs /sessions/{session_id}/message with {"message": "<text>"}
And the target session exists, is not closed or closing, and has a tmux session attached
When the daemon handles the request
Then send_message_endpoint loads the target session via db.get_session
And builds a base MessageMetadata via _build_metadata()
And _wrap_message_with_origin prepends a machine-role identity header iff the caller's session has system_role in {Orchestrator, Integrator, System}
And the request is dispatched as a "message" command through CommandMapper.map_api_input and CommandService.process_message
And the command path eventually invokes the tmux bridge send_keys_existing_tmux
And the daemon returns SendMessageResponseDTO(status="success", mode="work")
```

#### Raw keys — happy path

```
Given an authenticated caller POSTs /sessions/{session_id}/keys with {"key": "<name>", "count": <int|null>}
And the target session exists and is accessible to the caller
When send_keys_endpoint handles the request
Then it constructs a "keys" command via CommandMapper.map_api_input carrying {session_id, key, args=[count?]}
And dispatches through CommandService.keys
And tmux bridge functions in core/tmux_bridge/_keys.py translate the key name to tmux notation (e.g., "enter" → "C-m", "up"/"down"/"left"/"right" → "Up"/"Down"/..., "tab" → "Tab", "btab" → "BTab", "bspace" → "BSpace")
And -N <count> is passed to tmux send-keys for repeatable keys (arrows, BTab, BSpace) when count is provided
And SIGINT becomes "C-c", SIGTERM becomes "C-\", SIGKILL is delivered by signalling the pane's foreground PID directly (pgrep -P on the pane shell, then kill -9)
And the response is {"status": "success"}
```

#### Target session missing or closed

```
Given the caller POSTs /sessions/{session_id}/message
And db.get_session returns None OR the session has closed_at set OR lifecycle_status in {closed, closing}
When _load_target_session_for_message validates the target
Then the daemon raises HTTPException 404 ("Session {id} not found") or 409 ("Session {id} is closed")
And no tmux interaction is attempted
```

#### Tmux pipeline failure

```
Given the target session is open but the underlying tmux session has died (pane gone, server crash, etc.)
When _send_keys_tmux executes its load-buffer → paste-buffer -p -r → sleep 0.2s → send-keys C-m pipeline
And any tmux subprocess returns nonzero OR exceeds SUBPROCESS_TIMEOUT_QUICK
Then the matching error is logged with reason ∈ {nonzero_exit_load_buffer, nonzero_exit_paste_buffer, nonzero_exit_submit}
And the temporary tmux buffer (buf_name = "telec-<uuid4>") is best-effort cleaned via delete-buffer; cleanup failures are logged but never override the operation result
And send_keys_existing_tmux returns False
And the upstream send_message_endpoint logs "process_message failed" and raises HTTPException 500 to the caller
And no retry or backoff is applied at this layer
```

#### Direct-link conflict (work-mode send blocked)

```
Given the caller already holds an active direct link with the target session
And the caller POSTs /sessions/{id}/message WITHOUT request.direct
When _reject_existing_direct_link finds the link
Then the daemon returns SendMessageResponseDTO(status="error", mode="direct", link_id=<id>, message="A direct link is already active with this peer…")
And no message is delivered to the agent
```

The direct-link creation / peer fan-out / close-link flows live in `_handle_direct_message_request` and the related helpers but are documented as their own feature; this spec only notes the work-send conflict response.

### Implementation pointers (v1)

- `teleclaude/api/sessions_routes.py:923` — `send_message_endpoint` (FastAPI handler for `POST /sessions/{id}/message`)
- `teleclaude/api/sessions_routes.py:705` — `_process_api_message` (builds the `message` command and dispatches via `CommandService.process_message`)
- `teleclaude/api/sessions_routes.py:688` — `_wrap_message_with_origin` (prepend machine-role origin header)
- `teleclaude/api/sessions_routes.py:665` — `_machine_origin_marker` (Orchestrator/Integrator/System label lookup; humans and workers return None)
- `teleclaude/api/sessions_routes.py:719` — `_load_target_session_for_message` (404/409 validation)
- `teleclaude/api/sessions_routes.py:852` — `_handle_direct_message_request` (referenced for the direct-mode special case)
- `teleclaude/api/sessions_routes.py:905` — `_reject_existing_direct_link` (work-mode conflict guard)
- `teleclaude/api/sessions_actions_routes.py:374` — `send_keys_endpoint` (FastAPI handler for `POST /sessions/{id}/keys`)
- `teleclaude/core/tmux_bridge/_keys.py:41` — `send_keys` (ensures the tmux session exists, then delegates to `_send_keys_tmux`)
- `teleclaude/core/tmux_bridge/_keys.py:85` — `send_keys_existing_tmux` (no-create variant used by the message path)
- `teleclaude/core/tmux_bridge/_keys.py:173` — `_send_keys_tmux` (load-buffer → paste-buffer -p -r → 0.2s gap → send-keys C-m)
- `teleclaude/core/tmux_bridge/_keys.py:123` — `send_keys_to_tty` (TIOCSTI fallback for non-tmux sessions)
- `teleclaude/core/tmux_bridge/_keys.py:314` — `send_signal` (SIGINT/SIGTERM via send-keys; SIGKILL via `pgrep -P` + `kill -9`)
- `teleclaude/core/tmux_bridge/_keys.py:421` — `send_escape`
- `teleclaude/core/tmux_bridge/_keys.py:442` — `send_ctrl_key`
- `teleclaude/core/tmux_bridge/_keys.py:466` / `:487` — `send_tab` / `send_shift_tab`
- `teleclaude/core/tmux_bridge/_keys.py:515` — `send_backspace`
- `teleclaude/core/tmux_bridge/_keys.py:543` — `send_enter`
- `teleclaude/core/tmux_bridge/_keys.py:564` — `send_arrow_key`
- CLI verb: `telec sessions send <session_id> <message>` (with `--direct` / `--close-link`); raw key dispatch is internal — there is no first-class CLI verb for `/keys` outside test fixtures and the TUI.

### Cross-context references

- **identity** — `CallerIdentity` (via `clearance_sessions_send` / `clearance_sessions_keys`) gates access; `identity.session_id` and `identity.system_role` feed origin wrapping.
- **integration** — When the originating user is on an external messaging adapter (Telegram, Web), the message reaches `send_message_endpoint` through the integration adapter; for terminal callers, origin metadata stays in agent_runtime.
- **session_mirrors** — Delivered text is captured downstream by the agent's native transcript and eventually extracted to the eternal mirror; this spec covers only the inbound write.
- **session_ledger** — `db.get_session`, `last_message_sent_at`, and `lifecycle_status` ride on session-ledger storage; this spec consumes those fields read-only.

## Known caveats

- **Voice, file, result, widget, escalate are intentionally NOT covered here.** `send_voice_endpoint`, `send_file_endpoint`, `send_result_endpoint`, `render_widget_endpoint`, and `escalate_session` live in the same `sessions_actions_routes.py` module but cross into integration/messaging (adapter delivery, Discord escalation, file storage) and are owned by that context.
- **Direct-link machinery deferred to its own spec.** The work-mode send conflict response and the work-mode auto-listener registration are described here; the create / fan-out / close-link flow has its own feature spec to avoid duplication.
- **No retry / no replay on tmux failure.** A tmux pipeline failure surfaces as HTTP 500 to the caller. There is no daemon-side retry, no queued redelivery, and no replay on session restart — the caller decides whether to retry.
- **Single tmux paste buffer per call.** `_send_keys_tmux` allocates a unique buffer name (`telec-<uuid4>.hex`) and always attempts `delete-buffer` on the way out, even when `paste-buffer` failed; a `delete-buffer` failure leaves the user payload resident in the tmux server's buffer list until the server exits and is logged at WARNING.
- **0.2 s post-paste gap is hardcoded.** `_SUBMIT_GAP_S = 0.2` is the ordering margin between the bracketed-paste close marker and the discrete `C-m` submit. It does NOT scale with payload size; resizing this constant affects every send.
- **Gemini `!` escaping is implicit.** When `active_agent == "gemini"`, `_send_keys_tmux` rewrites `!` to `\!` before paste because of a known gemini-cli bug (google-gemini/gemini-cli#4454). Other agents pass the payload through unchanged.
- **Machine-origin wrapping is opt-in by role.** `_wrap_message_with_origin` only prepends a header when the caller session has `system_role` in {Orchestrator, Integrator, System}. Workers and humans send unwrapped text; their identity is conveyed through the Peer bracket upstream or carried by the integration adapter.
- **Auto-registered one-shot listener is best-effort.** When a non-self caller with a tmux session sends a work-mode message, the daemon attempts a one-shot `register_listener` so the caller sees the response. Failures are swallowed at DEBUG and never block delivery.
- **No payload size cap at this layer.** `load-buffer` reads from stdin so the tmux ~16 KB argv limit does not apply, but very large payloads still pay paste-time cost in the agent's terminal renderer.

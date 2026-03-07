---
description: 'Text-to-speech system with multi-backend fallback, per-session voice assignment, queued playback, and chiptunes audio focus coordination.'
id: 'project/design/architecture/tts-system'
scope: 'project'
type: 'design'
---

# TTS System — Design

## Purpose

- Provide audible feedback for session events (start, agent stop).
- Assign one voice per session for consistency across interactions.
- Fall back through a priority chain of TTS backends when the primary fails.
- Serialize playback with a single in-process worker plus file-based locking to prevent audio overlap.
- Keep background chiptunes paused until foreground speech is fully drained.

## Inputs/Outputs

**Inputs:**

- Agent events from the event bus (AGENT_EVENT for AgentHookEvents.AGENT_SESSION_START, AgentHookEvents.AGENT_STOP)
- TTS configuration from `config.yml` (services, voices, events, priority)
- Voice assignments persisted in the database
- Environment variables: `ELEVENLABS_API_KEY`, `OPENAI_API_KEY` (for respective services)

**Outputs:**

- Audio playback via the selected backend
- Updated voice assignments in the database (adaptive fallback promotion)
- Chiptunes playback state broadcasts over the API WebSocket so the TUI reflects daemon truth instead of optimistic local state

## Primary flows

**Event-triggered playback:**

1. Event handler receives AGENT_EVENT (AgentHookEvents.AGENT_SESSION_START or AgentHookEvents.AGENT_STOP) from the event bus.
2. `TTSManager.trigger_event()` checks config, gets or assigns a voice from the database.
3. Builds a service chain: assigned service first, then fallbacks in `service_priority` order.
4. `TTSManager` enqueues the request into a single playback worker and claims foreground audio focus.
5. The playback worker processes one queued request at a time.
6. `run_tts_with_lock_async()` delegates the blocking backend call to a thread via `asyncio.to_thread()`.
7. Queue runner acquires exclusive file lock (`/tmp/teleclaude_tts/.playback.lock`) for cross-process serialization.
8. Tries each backend in the chain until one succeeds (`speak(text, voice) → bool`).
9. If a fallback service succeeds, the voice assignment is updated in the database.

**Chiptunes coordination:**

1. `AudioFocusCoordinator` tracks the number of queued or active speech jobs.
2. The first queued speech job pauses chiptunes if music is currently playing.
3. Chiptunes pause is a hard pause: the player stops emulation advance and releases the active audio stream instead of muting a live stream in the background.
4. Resume reopens the chiptunes stream only after foreground speech drains.
5. Additional TTS jobs do not toggle chiptunes again; they share the same foreground-audio claim.
6. Background music state changes re-assert foreground audio focus, so a newly started or resumed track is paused again while speech claims are active.
7. Chiptunes resumes only after the last queued or active speech job completes or the TTS manager shuts down.

**Voice assignment:**

1. `get_random_voice_for_session()` picks a random available voice from enabled services, excluding voices already assigned to non-closed sessions (including `initializing`).
2. `_get_or_assign_voice(session_id)` persists the assignment in the database — one voice per session.
3. `get_voice_env_vars(voice)` converts the assignment to environment variables injected into the tmux session.

**Backend registry:**

- `BACKENDS` dict populated at module load. Platform-specific backends (macos, qwen3) are conditionally imported on Darwin only.
- Available: elevenlabs (Flash v2.5 API), openai (gpt-4o-mini-tts), macos (`say` command), pyttsx3 (system TTS), qwen3 (local Qwen3 via mlx-audio, Apple Silicon only).
- MLX TTS prefers the in-process `mlx_audio` backend and only falls back to the installed `mlx_audio.tts.generate` entrypoint when import or model load fails. CLI fallback still plays the rendered WAV synchronously with `afplay`.

## Failure modes

- **Primary service unavailable** — fallback chain tries next service in priority order. If a fallback succeeds, it is promoted and saved to the database for future calls.
- **All services fail** — `run_tts_with_lock()` returns `(False, None, None)`. Warning logged, session continues without audio.
- **File lock contention** — `fcntl` exclusive lock ensures sequential playback. Concurrent TTS requests block until the lock is released.
- **Burst of TTS events** — requests accumulate in the in-process queue, but chiptunes stays paused until the queue is drained instead of flapping pause/resume between items.
- **Pause during chiptunes startup** — the player may already be prebuffering, but it must not open a sounddevice stream while paused; resume is responsible for reopening it.
- **Missing API key** — backend `speak()` returns `False`, triggering fallback to the next service.
- **TTSManager import hang** — manager is lazily initialized via `get_tts_manager()` singleton to avoid circular imports at module load time.

## Invariants

1. One voice per session — once assigned, the voice is reused for the session's lifetime.
2. Sequential playback — the in-process worker and file lock together prevent concurrent speech playback.
3. Fallback promotion — if the primary service fails and a fallback succeeds, the DB is updated so subsequent calls use the working service.
4. Lazy initialization — `TTSManager` is created on first use to avoid circular imports.
5. Chiptunes audio focus is queue-scoped, not item-scoped — music resumes only after all queued speech has completed.
6. Paused chiptunes does not keep a live audio stream open in the background.

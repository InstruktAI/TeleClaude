---
description: 'Text-to-speech system with multi-backend fallback, per-session voice assignment, and file-locked sequential playback.'
id: 'project/design/tts-system'
scope: 'project'
type: 'design'
---

# TTS System — Design

## Purpose

- Provide audible feedback for session events (start, agent stop).
- Assign one voice per session for consistency across interactions.
- Fall back through a priority chain of TTS backends when the primary fails.
- Serialize playback with file-based locking to prevent audio overlap.

## Inputs/Outputs

**Inputs:**

- Agent events from the event bus (AGENT_EVENT for AgentHookEvents.AGENT_SESSION_START, AgentHookEvents.AGENT_STOP)
- TTS configuration from `config.yml` (services, voices, events, priority)
- Voice assignments persisted in the database
- Environment variables: `ELEVENLABS_API_KEY`, `OPENAI_API_KEY` (for respective services)

**Outputs:**

- Audio playback via the selected backend
- Updated voice assignments in the database (adaptive fallback promotion)
- Session environment variables: `ELEVENLABS_VOICE_ID`, `OPENAI_VOICE`, `MACOS_VOICE`

## Primary flows

**Event-triggered playback:**

1. Event handler receives AGENT_EVENT (AgentHookEvents.AGENT_SESSION_START or AgentHookEvents.AGENT_STOP) from the event bus.
2. `TTSManager.trigger_event()` checks config, gets or assigns a voice from the database.
3. Builds a service chain: assigned service first, then fallbacks in `service_priority` order.
4. `run_tts_with_lock_async()` delegates to a thread via `asyncio.to_thread()`.
5. Queue runner acquires exclusive file lock (`~/.tmp/teleclaude_tts/.playback.lock`).
6. Tries each backend in the chain until one succeeds (`speak(text, voice) → bool`).
7. If a fallback service succeeds, the voice assignment is updated in the database.

**Voice assignment:**

1. `get_random_voice_for_session()` picks a random available voice from enabled services, excluding voices already assigned to active sessions.
2. `_get_or_assign_voice(session_id)` persists the assignment in the database — one voice per session.
3. `get_voice_env_vars(voice)` converts the assignment to environment variables injected into the tmux session.

**Backend registry:**

- `BACKENDS` dict populated at module load. Platform-specific backends (macos, qwen3) are conditionally imported on Darwin only.
- Available: elevenlabs (Flash v2.5 API), openai (gpt-4o-mini-tts), macos (`say` command), pyttsx3 (system TTS), qwen3 (local Qwen3 via mlx-audio, Apple Silicon only).

## Failure modes

- **Primary service unavailable** — fallback chain tries next service in priority order. If a fallback succeeds, it is promoted and saved to the database for future calls.
- **All services fail** — `run_tts_with_lock()` returns `(False, None, None)`. Warning logged, session continues without audio.
- **File lock contention** — `fcntl` exclusive lock ensures sequential playback. Concurrent TTS requests block until the lock is released.
- **Missing API key** — backend `speak()` returns `False`, triggering fallback to the next service.
- **TTSManager import hang** — manager is lazily initialized via `get_tts_manager()` singleton to avoid circular imports at module load time.

## Invariants

1. One voice per session — once assigned, the voice is reused for the session's lifetime.
2. Sequential playback — file lock prevents concurrent audio from overlapping.
3. Fallback promotion — if the primary service fails and a fallback succeeds, the DB is updated so subsequent calls use the working service.
4. Lazy initialization — `TTSManager` is created on first use to avoid circular imports.

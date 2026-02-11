# Requirements: TTS Fallback Saturation

## Goal

Ensure TTS fallback voice selection respects the "one voice per session" invariant by filtering out voices already in use by other active sessions, and move voice assignment to a just-in-time model.

## Functional Requirements

1.  **Awareness of Active Voices**
    - The `trigger_event` method in `TTSManager` MUST retrieve the set of currently assigned voices (`service_name`, `voice_id`) from the database before constructing the fallback chain.

2.  **Saturation-Based Selection**
    - When selecting a fallback voice from a candidate service, the system MUST filter the service's voice list against the set of active voices.
    - The system MUST only select a voice if it is NOT currently assigned to another active session.

3.  **Provider Skipping**
    - If a candidate service (in the priority list) has NO available (unassigned) voices, it MUST be skipped entirely in the fallback chain.
    - It MUST NOT return a random "used" voice as a fallback.

4.  **Priority Adherence**
    - The fallback chain construction MUST continue to respect the configured `service_priority` order, simply skipping saturated providers.

5.  **Invariant Preservation**
    - The session's _currently assigned_ voice (if valid) MUST always remain the first option in the service chain, regardless of the saturation check (since it is "in use" by _this_ session).

6.  **Lazy Voice Assignment (Refactor)**
    - Voice assignment MUST NOT occur at session creation time (`create_session`).
    - Voice assignment MUST happen lazily upon the first TTS event trigger (`trigger_event` -> `_get_or_assign_voice`) to ensure availability checks are performed against the current state of the system.

## Technical Constraints

- No changes to the `db.get_voices_in_use()` signature (it already returns the needed set).
- Must handle services with no explicit voice list (e.g., `macos` default) correctly (treat as a single voice ID matching the service name).

## Acceptance Criteria

- [ ] `trigger_event` logic queries `voices_in_use`.
- [ ] Fallback chain construction filters `service_cfg.voices`.
- [ ] If all fallback providers are saturated, the chain contains only the primary assigned voice (or empty if none).
- [ ] Code review confirms no blind `random.choice()` on the full voice list during fallback.
- [ ] `create_session` no longer assigns a voice.

# TTS Fallback Saturation Fix

## Context

The TTS system allows for multiple backend providers (ElevenLabs, OpenAI, etc.). When the primary provider fails, the system falls back to secondary providers.

## Problem

The current fallback logic in `teleclaude/tts/manager.py` (`trigger_event`) blindly selects a random voice from the fallback provider's list. It **does not check** if that voice is already assigned to another active session.

This leads to:

1.  **Voice Collisions:** Two sessions might end up using the same voice from a fallback provider.
2.  **Fragmented Personas:** If a session falls back and "promotes" a collided voice, it might switch to a voice that shouldn't be available.
3.  **Saturation Violation:** The intent is to fully saturate Provider 1's free voices, then Provider 2's free voices, etc. The current logic ignores saturation during fallback.

## Objective

Modify the fallback selection logic to:

1.  Check which voices are currently in use (using `db.get_voices_in_use()`).
2.  When building the fallback chain, **only select voices that are NOT in use**.
3.  If a provider has no free voices, skip it in the fallback chain.
4.  Ensure that we saturate from top to bottom (priority order) using only _available_ inventory.

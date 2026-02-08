"""TTS Manager - unified interface for TTS across TeleClaude."""

import asyncio
import random
from typing import Optional

from instrukt_ai_logging import get_logger

from teleclaude.config import TTSConfig, config
from teleclaude.core.db import db
from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.origins import InputOrigin
from teleclaude.core.voice_assignment import VoiceConfig
from teleclaude.tts.queue_runner import run_tts_with_lock_async

SESSION_START_MESSAGES = [
    "Standing by with grep patterns locked and loaded. What can I find?",
    "Warmed up and ready to hunt down that bug!",
    "Cache cleared, mind fresh. What's the task?",
    "All systems nominal, ready to ship some code!",
    "Initialized and ready to make those tests pass. What needs fixing?",
    "Compiled with optimism and ready to refactor!",
    "Ready to turn coffee into code. Where do we start?",
    "Standing by like a well-indexed database!",
    "Alert and ready to parse whatever you need. What's up?",
    "Primed to help you ship that feature!",
    "Spun up and ready to debug. What's broken?",
    "Loaded and eager to make things work!",
    "Ready to dig into the details. What should I investigate?",
    "All systems go for some serious coding!",
    "Prepared to tackle whatever you throw at me. What's the challenge?",
    "Standing by to help ship something awesome!",
    "Ready to make the build green. What needs attention?",
    "Warmed up and waiting to assist!",
    "Initialized and ready to solve problems. What's the issue?",
    "All set to help you build something great!",
]

logger = get_logger(__name__)


class TTSManager:
    """Manages TTS configuration and event triggering."""

    def __init__(self):
        """Initialize TTS manager from config."""
        self.tts_config = self._load_tts_config()
        self.enabled = self.tts_config.enabled

    def _load_tts_config(self) -> TTSConfig:
        """Load TTS config from config.yaml."""
        if not config.tts:
            # Return disabled config if TTS not configured
            return TTSConfig(
                enabled=False,
                events={},
                services={},
            )

        return config.tts

    async def get_random_voice_for_session(self) -> tuple[str, Optional[str]] | None:
        """
        Get a random voice from enabled services, excluding voices already in use
        by active sessions.

        Returns:
            Tuple of (service_name, voice_id_or_name) or None if no voices configured
        """
        if not self.enabled:
            return None

        voices_in_use = await db.get_voices_in_use()

        # Priority order: use configured service_priority or default fallback
        priority = self.tts_config.service_priority or [
            "elevenlabs",
            "openai",
            "macos",
            "pyttsx3",
        ]

        # Try services in priority order until we find one with available voices
        for service_name in priority:
            service_cfg = self.tts_config.services.get(service_name)
            if service_cfg and service_cfg.enabled and service_cfg.voices:
                # Filter out voices already assigned to active sessions
                available = [v for v in service_cfg.voices if (service_name, v.voice_id or v.name) not in voices_in_use]
                if not available:
                    logger.debug("All %s voices in use, trying next service", service_name)
                    continue
                voice = random.choice(available)
                logger.info(
                    f"Assigned voice: {voice.name} from service {service_name}",
                )
                return (service_name, voice.voice_id or voice.name)

        logger.debug("No TTS services with available voices")
        return None

    async def _get_or_assign_voice(self, session_id: str) -> Optional[VoiceConfig]:
        """Get stored voice for session, or assign a new one if none exists.

        Args:
            session_id: TeleClaude session ID

        Returns:
            VoiceConfig or None if no services available
        """
        # Try to get existing voice assignment
        voice = await db.get_voice(session_id)
        if voice and voice.service_name:
            logger.debug(
                f"Using stored voice: {voice.voice} from {voice.service_name}",
                extra={"session_id": session_id[:8]},
            )
            return voice

        # No voice assigned yet - pick one and store it
        voice_result = await self.get_random_voice_for_session()
        if not voice_result:
            return None

        service_name, voice_param = voice_result
        new_voice = VoiceConfig(service_name=service_name, voice=voice_param or "")
        await db.assign_voice(session_id, new_voice)
        logger.info(
            f"Assigned new voice: {voice_param} from {service_name}",
            extra={"session_id": session_id[:8]},
        )
        return new_voice

    async def trigger_event(
        self,
        event_name: str | AgentHookEventType,
        session_id: str,
        text: Optional[str] = None,
    ) -> bool:
        """
        Trigger TTS for an event.

        Args:
            event_name: "session_start" or "agent_stop"
            session_id: TeleClaude session ID
            text: Custom text to speak (overrides config message)

        Returns:
            True if TTS was queued, False otherwise
        """
        if not self.enabled:
            logger.debug("TTS disabled globally")
            return False

        normalized_event_name = self._normalize_event_name(event_name)
        if not normalized_event_name:
            logger.debug("Ignoring unsupported TTS event %s", event_name)
            return False
        event_cfg = self.tts_config.events.get(normalized_event_name)
        if not event_cfg or not event_cfg.enabled:
            logger.debug(f"Event {normalized_event_name} disabled or not configured")
            return False

        # Use custom text, or built-in session_start messages, or config messages, or fallback message
        if text:
            text_to_speak = text
        elif normalized_event_name == "session_start":
            text_to_speak = random.choice(SESSION_START_MESSAGES) if SESSION_START_MESSAGES else "Session started."
        elif event_cfg.messages:
            text_to_speak = random.choice(event_cfg.messages)
        else:
            text_to_speak = event_cfg.message or "Session started."

        if not text_to_speak:
            logger.debug(f"No message for event {event_name}")
            return False

        # Get session to check origin
        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for TTS", session_id)
            return False

        if session.last_input_origin == InputOrigin.TELEGRAM.value:
            logger.info(f"Skipping TTS for session {session_id[:8]} (origin: telegram)")
            return False

        # Get or assign voice for this session (persisted in DB)
        voice = await self._get_or_assign_voice(session_id)
        if not voice:
            logger.warning("No voice available for TTS")
            return False

        # Build fallback chain starting with session's assigned service
        service_chain: list[tuple[str, Optional[str]]] = []

        # First, add the session's assigned voice
        service_chain.append((voice.service_name, voice.voice))

        # Then add fallback services (different from assigned service)
        priority = self.tts_config.service_priority or [
            "elevenlabs",
            "openai",
            "macos",
            "pyttsx3",
        ]
        for service_name in priority:
            if service_name == voice.service_name:
                continue  # Skip - already added as primary
            service_cfg = self.tts_config.services.get(service_name)
            if service_cfg and service_cfg.enabled:
                fallback_voice: Optional[str] = None
                if service_cfg.voices:
                    random_voice = random.choice(service_cfg.voices)
                    fallback_voice = random_voice.voice_id or random_voice.name
                service_chain.append((service_name, fallback_voice))

        logger.debug(
            f"TTS triggered for {normalized_event_name}: {text_to_speak[:50]}...",
            extra={"session_id": session_id[:8]},
        )

        # Queue TTS (non-blocking)
        task = asyncio.create_task(run_tts_with_lock_async(text_to_speak, service_chain, session_id))
        task.add_done_callback(
            lambda t: asyncio.create_task(self._handle_tts_result(t, session_id, voice.service_name))
        )
        return True

    async def speak(self, text: str) -> bool:
        """Speak text without coupling to sessions or event types."""
        if not self.enabled:
            logger.debug("TTS disabled globally")
            return False

        if not text:
            logger.debug("No text provided for TTS")
            return False

        service_chain: list[tuple[str, Optional[str]]] = []
        priority = self.tts_config.service_priority or [
            "elevenlabs",
            "openai",
            "macos",
            "pyttsx3",
        ]
        for service_name in priority:
            service_cfg = self.tts_config.services.get(service_name)
            if not service_cfg or not service_cfg.enabled:
                continue
            voice_param: Optional[str] = None
            if service_cfg.voices:
                random_voice = random.choice(service_cfg.voices)
                voice_param = random_voice.voice_id or random_voice.name
            service_chain.append((service_name, voice_param))

        if not service_chain:
            logger.warning("No TTS services enabled for speak()")
            return False

        logger.debug("TTS speak queued: %s...", text[:50])
        task = asyncio.create_task(run_tts_with_lock_async(text, service_chain, "summary"))
        task.add_done_callback(
            lambda t: asyncio.create_task(self._handle_tts_result(t, "summary", service_chain[0][0]))
        )
        return True

    def _normalize_event_name(self, event_name: str | AgentHookEventType) -> str | None:
        """Map agent hook events to TTS event config keys."""
        if event_name == AgentHookEvents.AGENT_SESSION_START:
            return "session_start"
        if event_name == "stop":
            return "agent_stop"
        if event_name == AgentHookEvents.AGENT_STOP:
            return "agent_stop"
        return None

    async def _handle_tts_result(
        self,
        task: asyncio.Task[tuple[bool, str | None, str | None]],
        session_id: str,
        primary_service: str,
    ) -> None:
        """Persist fallback voice when a non-primary service succeeds."""
        try:
            success, used_service, used_voice = task.result()
        except Exception as exc:  # noqa: BLE001 - background task failure should not crash
            logger.error("TTS task failed: %s", exc, extra={"session_id": session_id[:8]})
            return

        if not success or not used_service:
            return
        if used_service == primary_service:
            return

        await db.assign_voice(session_id, VoiceConfig(service_name=used_service, voice=used_voice or ""))
        logger.info(
            "Promoted fallback voice %s from %s for session %s",
            used_voice or "default",
            used_service,
            session_id[:8],
        )

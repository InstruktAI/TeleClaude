"""TTS Manager - unified interface for TTS across TeleClaude."""

import random
from typing import Optional

from instrukt_ai_logging import get_logger

from teleclaude.config import TTSConfig, config
from teleclaude.core.db import db
from teleclaude.core.voice_assignment import VoiceConfig
from teleclaude.tts.queue_runner import run_tts_with_lock

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

    def get_random_voice_for_session(self) -> tuple[str, Optional[str]] | None:
        """
        Get a random voice from enabled services.

        Returns:
            Tuple of (service_name, voice_id_or_name) or None if no voices configured
        """
        if not self.enabled:
            return None

        # Priority order: use configured service_priority or default fallback
        priority = self.tts_config.service_priority or [
            "elevenlabs",
            "openai",
            "macos",
            "pyttsx3",
        ]

        # Try services in priority order until we find one with voices
        for service_name in priority:
            service_cfg = self.tts_config.services.get(service_name)
            if service_cfg and service_cfg.enabled and service_cfg.voices:
                # Pick random voice from this service
                voice = random.choice(service_cfg.voices)
                logger.info(
                    f"Assigned voice: {voice.name} from service {service_name}",
                )
                return (service_name, voice.voice_id or voice.name)

        logger.debug("No TTS services with voices enabled")
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
        if voice and voice.service_name and voice.voice_name:
            logger.debug(
                f"Using stored voice: {voice.voice_name} from {voice.service_name}",
                extra={"session_id": session_id[:8]},
            )
            return voice

        # No voice assigned yet - pick one and store it
        voice_result = self.get_random_voice_for_session()
        if not voice_result:
            return None

        service_name, voice_param = voice_result
        new_voice = VoiceConfig(service_name=service_name, voice_name=voice_param or "")
        await db.assign_voice(session_id, new_voice)
        logger.info(
            f"Assigned new voice: {voice_param} from {service_name}",
            extra={"session_id": session_id[:8]},
        )
        return new_voice

    async def trigger_event(
        self,
        event_name: str,
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

        event_cfg = self.tts_config.events.get(event_name)
        if not event_cfg or not event_cfg.enabled:
            logger.debug(f"Event {event_name} disabled or not configured")
            return False

        # Use custom text, or pick from messages list, or use single message
        if text:
            text_to_speak = text
        elif event_cfg.messages:
            text_to_speak = random.choice(event_cfg.messages)
        else:
            text_to_speak = event_cfg.message

        if not text_to_speak:
            logger.debug(f"No message for event {event_name}")
            return False

        # Get or assign voice for this session (persisted in DB)
        voice = await self._get_or_assign_voice(session_id)
        if not voice:
            logger.warning("No voice available for TTS")
            return False

        # Build fallback chain starting with session's assigned service
        service_chain: list[tuple[str, Optional[str]]] = []

        # First, add the session's assigned voice
        service_chain.append((voice.service_name, voice.voice_name))

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
                if service_cfg.voices:
                    fallback_voice = random.choice(service_cfg.voices)
                    service_chain.append((service_name, fallback_voice.voice_id or fallback_voice.name))
                else:
                    service_chain.append((service_name, None))

        logger.debug(
            f"TTS triggered for {event_name}: {text_to_speak[:50]}...",
            extra={"session_id": session_id[:8]},
        )

        # Queue TTS (non-blocking)
        return run_tts_with_lock(text_to_speak, service_chain, session_id)

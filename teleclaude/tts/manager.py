"""TTS Manager - unified interface for TTS across TeleClaude."""

import asyncio
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config import TTSConfig, config
from teleclaude.core.db import db
from teleclaude.core.events import AgentHookEvents, AgentHookEventType
from teleclaude.core.origins import InputOrigin
from teleclaude.core.voice_assignment import VoiceConfig
from teleclaude.tts.audio_focus import AudioFocusCoordinator
from teleclaude.tts.queue_runner import run_tts_with_lock_async

if TYPE_CHECKING:
    from teleclaude.chiptunes.manager import ChiptunesManager

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


@dataclass(slots=True)
class _SpeechJob:
    text: str
    service_chain: list[tuple[str, str | None]]
    session_id: str
    primary_service: str


class TTSManager:
    """Manages TTS configuration and event triggering."""

    def __init__(self) -> None:
        """Initialize TTS manager from config."""
        self.tts_config = self._load_tts_config()
        self.enabled = self.tts_config.enabled
        self._chiptunes_manager: ChiptunesManager | None = None
        self._audio_focus = AudioFocusCoordinator()
        self._speech_queue: asyncio.Queue[_SpeechJob] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._runtime_lock: asyncio.Lock | None = None

    def set_chiptunes_manager(self, manager: "ChiptunesManager") -> None:
        """Inject ChiptunesManager reference for pause/resume during TTS."""
        self._ensure_runtime_state()
        self._chiptunes_manager = manager
        self._audio_focus.set_chiptunes_manager(manager)

    def on_chiptunes_state_change(self) -> None:
        """Re-assert foreground speech ownership after background audio changes."""
        self._ensure_runtime_state()
        self._audio_focus.on_background_state_change()

    def on_chiptunes_user_pause(self) -> None:
        """Honor an explicit user pause even if TTS currently owns audio focus."""
        self._ensure_runtime_state()
        self._audio_focus.cancel_background_resume()

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

    async def get_random_voice_for_session(self) -> tuple[str, str | None] | None:
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
            if not service_cfg or not service_cfg.enabled:
                continue

            # Services with no voice list use the provider name as the voice identifier
            if not service_cfg.voices:
                if (service_name, service_name) not in voices_in_use:
                    logger.info("Assigned voice: %s (provider default)", service_name)
                    return (service_name, service_name)
                continue

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

    async def _get_or_assign_voice(self, session_id: str) -> VoiceConfig | None:
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
        text: str | None = None,
    ) -> bool:
        """
        Trigger TTS for an event.

        Args:
            event_name: "session_start"
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

        if session.last_input_origin != InputOrigin.TERMINAL.value:
            logger.info("Skipping TTS for session %s (origin: %s)", session_id[:8], session.last_input_origin)
            return False

        # Get or assign voice for this session (persisted in DB)
        voice = await self._get_or_assign_voice(session_id)
        if not voice:
            logger.warning("No voice available for TTS")
            return False

        # Build fallback chain starting with session's assigned service
        service_chain: list[tuple[str, str | None]] = []

        # First, add the session's assigned voice
        service_chain.append((voice.service_name, voice.voice))

        # Query active voices to filter saturated providers from fallback chain
        voices_in_use = await db.get_voices_in_use()

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
            if not service_cfg or not service_cfg.enabled:
                continue

            fallback_voice: str | None = None
            if service_cfg.voices:
                available = [v for v in service_cfg.voices if (service_name, v.voice_id or v.name) not in voices_in_use]
                if not available:
                    logger.debug("All %s voices in use, skipping fallback service", service_name)
                    continue
                random_voice = random.choice(available)
                fallback_voice = random_voice.voice_id or random_voice.name
            else:
                # Services with no voice list use the provider name as voice ID
                if (service_name, service_name) in voices_in_use:
                    logger.debug("All %s voices in use, skipping fallback service", service_name)
                    continue

            service_chain.append((service_name, fallback_voice))

        logger.debug(
            f"TTS triggered for {normalized_event_name}: {text_to_speak[:50]}...",
            extra={"session_id": session_id[:8]},
        )

        await self._enqueue_speech(text_to_speak, service_chain, session_id, voice.service_name)
        return True

    async def speak(self, text: str, session_id: str) -> bool:
        """Speak text using the session's persisted voice."""
        if not self.enabled:
            logger.debug("TTS disabled globally")
            return False

        if not text:
            logger.debug("No text provided for TTS")
            return False

        session = await db.get_session(session_id)
        if not session:
            logger.warning("Session %s not found for TTS speak()", session_id[:8])
            return False

        if session.last_input_origin != InputOrigin.TERMINAL.value:
            logger.info("Skipping TTS speak for session %s (origin: %s)", session_id[:8], session.last_input_origin)
            return False

        voice = await self._get_or_assign_voice(session_id)
        if not voice:
            logger.warning("No voice available for TTS speak()", extra={"session_id": session_id[:8]})
            return False

        service_chain: list[tuple[str, str | None]] = [(voice.service_name, voice.voice)]
        logger.debug("TTS speak queued (voice %s): %s...", voice.voice, text[:50])

        await self._enqueue_speech(text, service_chain, session_id, voice.service_name)
        return True

    def _normalize_event_name(self, event_name: str | AgentHookEventType) -> str | None:
        """Map agent hook events to TTS event config keys."""
        if event_name == AgentHookEvents.AGENT_SESSION_START:
            return "session_start"
        return None

    def _ensure_runtime_state(self) -> None:
        """Backfill async runtime state for tests that bypass __init__."""
        if not hasattr(self, "_chiptunes_manager"):
            self._chiptunes_manager = None
        if not hasattr(self, "_audio_focus"):
            self._audio_focus = AudioFocusCoordinator()
            if self._chiptunes_manager is not None:
                self._audio_focus.set_chiptunes_manager(self._chiptunes_manager)
        if not hasattr(self, "_speech_queue"):
            self._speech_queue = None
        if not hasattr(self, "_worker_task"):
            self._worker_task = None
        if not hasattr(self, "_runtime_lock"):
            self._runtime_lock = None

    async def _ensure_playback_runtime(self) -> None:
        self._ensure_runtime_state()
        if self._runtime_lock is None:
            self._runtime_lock = asyncio.Lock()
        async with self._runtime_lock:
            if self._speech_queue is None:
                self._speech_queue = asyncio.Queue()
            if self._worker_task is None or self._worker_task.done():
                self._worker_task = asyncio.create_task(self._speech_worker(), name="tts-playback-worker")
                self._worker_task.add_done_callback(self._log_worker_failure)

    async def _enqueue_speech(
        self,
        text: str,
        service_chain: list[tuple[str, str | None]],
        session_id: str,
        primary_service: str,
    ) -> None:
        await self._ensure_playback_runtime()
        assert self._runtime_lock is not None
        assert self._speech_queue is not None
        async with self._runtime_lock:
            self._audio_focus.claim_foreground()
            self._speech_queue.put_nowait(
                _SpeechJob(
                    text=text,
                    service_chain=service_chain,
                    session_id=session_id,
                    primary_service=primary_service,
                )
            )
            logger.debug(
                "TTS queued: pending=%d queue=%d",
                self._audio_focus.active_claims,
                self._speech_queue.qsize(),
                extra={"session_id": session_id[:8]},
            )

    async def _speech_worker(self) -> None:
        assert self._speech_queue is not None
        while True:
            job = await self._speech_queue.get()
            try:
                await self._run_speech_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("TTS worker failed: %s", exc, extra={"session_id": job.session_id[:8]})
            finally:
                self._speech_queue.task_done()
                self._audio_focus.release_foreground()

    async def _run_speech_job(self, job: _SpeechJob) -> None:
        """Speak one queued request and persist fallback voice promotions."""
        success, used_service, used_voice = await run_tts_with_lock_async(
            job.text,
            job.service_chain,
            job.session_id,
        )
        if not success or not used_service:
            return
        if used_service == job.primary_service:
            return

        await db.assign_voice(job.session_id, VoiceConfig(service_name=used_service, voice=used_voice or ""))
        logger.info(
            "Promoted fallback voice %s from %s for session %s",
            used_voice or "default",
            used_service,
            job.session_id[:8],
        )

    def _log_worker_failure(self, task: asyncio.Task[None]) -> None:
        """Log unexpected worker exits."""
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is None:
            return
        logger.error("TTS worker crashed: %s", exc, exc_info=exc)

    async def shutdown(self) -> None:
        """Stop the background worker and restore background audio state."""
        self._ensure_runtime_state()
        worker = self._worker_task
        self._worker_task = None
        if worker is not None:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._speech_queue = None
        self._audio_focus.reset()

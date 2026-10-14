"""OpenAI Whisper STT backend — cloud-based transcription."""

from pathlib import Path

from instrukt_ai_logging import get_logger
from openai import AsyncOpenAI

from teleclaude.config.machine import config
from teleclaude.stt.errors import STTServiceUnavailableError

logger = get_logger(__name__)

OPENAI_SERVICE = "openai"
_OPENAI_UNAVAILABLE_MESSAGE = "OpenAI Whisper STT unavailable: stt.services.openai.api_key not set"


class OpenAIWhisperBackend:
    """Cloud STT using OpenAI Whisper API."""

    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None

    def _ensure_client(self) -> bool:
        """Lazy-init the OpenAI client on first use."""
        if self._client is not None:
            return True
        stt = config.stt
        service = (stt.services or {}).get(OPENAI_SERVICE) if stt is not None and stt.enabled else None
        api_key = service.api_key if service is not None and service.enabled else None
        if not api_key:
            logger.debug("OpenAI Whisper STT unavailable: stt.services.openai.api_key not set")
            return False
        self._client = AsyncOpenAI(api_key=api_key)
        return True

    async def transcribe(self, audio_file_path: str, language: str | None = None) -> str:
        """Transcribe audio file using Whisper API.

        Args:
            audio_file_path: Path to audio file
            language: Optional language code (e.g., 'en'). None for auto-detect.

        Returns:
            Transcribed text

        Raises:
            RuntimeError: If client cannot be initialized
            FileNotFoundError: If audio file does not exist
        """
        if not self._ensure_client():
            raise STTServiceUnavailableError(_OPENAI_UNAVAILABLE_MESSAGE)

        audio_path = Path(audio_file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        with open(audio_file_path, "rb") as audio_file:
            params: dict[str, object] = {  # guard: loose-dict - OpenAI SDK kwargs are dynamic.
                "model": "whisper-1",
                "file": audio_file,
            }
            if language:
                params["language"] = language

            transcript = await self._client.audio.transcriptions.create(**params)  # type: ignore

        text: str = str(transcript.text).strip()
        logger.debug("Whisper STT: transcribed %d chars", len(text))
        return text

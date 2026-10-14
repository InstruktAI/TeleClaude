"""MLX Parakeet STT backend — local on-device transcription for Apple Silicon."""

import asyncio
import json
import shutil
import subprocess
import tempfile
from importlib import import_module
from pathlib import Path
from threading import Lock

from instrukt_ai_logging import get_logger

from teleclaude.config._models import STTServiceConfig
from teleclaude.config.machine import config
from teleclaude.mlx_utils import is_local_path, resolve_model_ref
from teleclaude.stt.errors import STTServiceUnavailableError

load_stt_model = None
mlx_audio_import_error: Exception | None = None
_mlx_audio_import_attempted = False

logger = get_logger(__name__)

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
PARAKEET_SERVICE = "parakeet"
_UNRESOLVED_MODEL_REF = ""
_PARAKEET_UNAVAILABLE_MESSAGE = "Parakeet STT unavailable"


class MLXParakeetBackend:
    """Local STT using mlx-audio with Parakeet model."""

    def __init__(self) -> None:
        self._model = None
        self._model_ref = _UNRESOLVED_MODEL_REF
        self._cli_bin: str | None = None
        self._prepared = False
        self._model_lock = Lock()

    def _prepare(self) -> None:
        """Resolve the service's model and CLI binary on first use and validate the model reference."""
        with self._model_lock:
            if self._prepared:
                return
            self._model_ref = self._resolve_model_ref()
            self._cli_bin = self._resolve_cli_bin()
            self._validate_config()
            self._prepared = True

    def _validate_config(self) -> None:
        """Validate the model ref: local paths must exist, HF IDs are accepted as-is."""
        if is_local_path(self._model_ref):
            path = Path(self._model_ref)
            if not path.exists():
                raise FileNotFoundError(f"Parakeet STT model path does not exist: {self._model_ref}")
            if not path.is_dir():
                raise NotADirectoryError(f"Parakeet STT model path is not a directory: {self._model_ref}")
            logger.info("Parakeet STT: validated local model at %s", self._model_ref)
        else:
            logger.info("Parakeet STT: using HuggingFace model %s (downloaded on first use)", self._model_ref)

    def _resolve_cli_bin(self) -> str | None:
        configured_cli_bin = self._service_config().cli_bin
        if configured_cli_bin:
            candidate = str(Path(configured_cli_bin).expanduser())
            if Path(candidate).exists():
                return candidate

        from_path = shutil.which("mlx_audio.stt.generate")
        if from_path:
            return from_path

        default_tool_bin = str(Path("~/.local/bin/mlx_audio.stt.generate").expanduser())
        if Path(default_tool_bin).exists():
            return default_tool_bin

        return None

    def _resolve_model_ref(self) -> str:
        return resolve_model_ref(self._service_config().model or DEFAULT_MODEL)

    @staticmethod
    def _service_config() -> STTServiceConfig:
        if config.stt and config.stt.services:
            configured = config.stt.services.get(PARAKEET_SERVICE)
            if configured is not None:
                return configured
        return STTServiceConfig(enabled=False, model=DEFAULT_MODEL)

    def _ensure_model(self) -> bool:
        with self._model_lock:
            return self._ensure_model_locked()

    def _ensure_model_locked(self) -> bool:
        global load_stt_model, mlx_audio_import_error, _mlx_audio_import_attempted

        # CLI-only mode: never import mlx_audio when CLI backend exists.
        if self._cli_bin:
            logger.debug("Parakeet STT using CLI backend only: %s", self._cli_bin)
            return True

        # Local model path: lazy-import mlx_audio only when CLI is unavailable.
        if not _mlx_audio_import_attempted:
            _mlx_audio_import_attempted = True
            try:
                stt_module = import_module("mlx_audio.stt")
                load_candidate = getattr(stt_module, "load", None)
                if callable(load_candidate):
                    load_stt_model = load_candidate
            except Exception as import_error:
                mlx_audio_import_error = import_error

        if load_stt_model is None:
            logger.error(
                "Parakeet STT unavailable: mlx_audio import failed and no CLI fallback (%s)", mlx_audio_import_error
            )
            return False

        if self._model is not None:
            return True
        try:
            self._model_ref = self._resolve_model_ref()
            self._model = load_stt_model(self._model_ref)
            logger.info("Parakeet STT model loaded: %s", self._model_ref)
            return True
        except Exception as e:
            logger.error("Failed to load Parakeet STT model (%s): %s", self._model_ref, e)
            return False

    async def transcribe(self, audio_file_path: str, language: str | None = None) -> str:
        """Transcribe audio file using local Parakeet model.

        Args:
            audio_file_path: Path to audio file (any format mlx_audio supports)
            language: Optional language hint for CLI fallback (Parakeet can auto-detect).

        Returns:
            Transcribed text

        Raises:
            RuntimeError: If model cannot be loaded
            FileNotFoundError: If audio file does not exist
        """
        audio_path = Path(audio_file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        await asyncio.to_thread(self._prepare)
        if not await asyncio.to_thread(self._ensure_model):
            raise STTServiceUnavailableError(_PARAKEET_UNAVAILABLE_MESSAGE)

        if self._model is None and self._cli_bin:
            return await asyncio.to_thread(self._transcribe_cli, audio_file_path, language)

        return await asyncio.to_thread(self._transcribe_local, audio_file_path)

    def _transcribe_local(self, audio_file_path: str) -> str:
        result = self._model.generate(audio_file_path)  # type: ignore
        text = result.text.strip()
        logger.debug("Parakeet STT: transcribed %d chars (local)", len(text))
        return text  # type: ignore[no-any-return]

    def _transcribe_cli(self, audio_file_path: str, language: str | None = None) -> str:
        if not self._cli_bin:
            raise RuntimeError("Parakeet CLI unavailable")

        # mlx_audio CLI appends ".{format}" to --output-path, so we pass a base
        # path without an extension and read from "{base}.json".
        with tempfile.TemporaryDirectory() as tmpdir:
            output_base = str(Path(tmpdir) / "transcript")
            cmd = [
                self._cli_bin,
                "--model",
                self._model_ref,
                "--audio",
                audio_file_path,
                "--output-path",
                output_base,
                "--format",
                "json",
            ]
            if language:
                cmd.extend(["--language", language])

            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f"Parakeet CLI failed: {(result.stderr or result.stdout).strip()}")

            output_json = Path(f"{output_base}.json")
            payload = output_json.read_text(encoding="utf-8").strip() if output_json.exists() else ""
            if not payload:
                payload = result.stdout.strip()
            if not payload:
                raise RuntimeError("Parakeet CLI returned empty output")

            data = json.loads(payload)
            text = str(data.get("text", "")).strip() if isinstance(data, dict) else ""
            if not text:
                raise RuntimeError("Parakeet CLI output did not contain transcription text")
            logger.debug("Parakeet STT: transcribed %d chars (CLI fallback)", len(text))
            return text

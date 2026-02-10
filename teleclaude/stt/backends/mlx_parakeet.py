"""MLX Parakeet STT backend — local on-device transcription for Apple Silicon."""

import os
import shutil
from pathlib import Path

from instrukt_ai_logging import get_logger

try:
    from mlx_audio.stt import load as load_stt_model
except Exception as import_error:  # noqa: BLE001 - keep backend available via CLI fallback
    load_stt_model = None  # type: ignore[assignment]
    MLX_AUDIO_IMPORT_ERROR = import_error
else:
    MLX_AUDIO_IMPORT_ERROR = None

from teleclaude.config import config
from teleclaude.mlx_utils import is_local_path, resolve_model_ref

logger = get_logger(__name__)

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
MODEL_ENV_VAR = "TELECLAUDE_PARAKEET_MODEL"
CLI_BIN_ENV_VAR = "TELECLAUDE_PARAKEET_CLI_BIN"


class MLXParakeetBackend:
    """Local STT using mlx-audio with Parakeet model."""

    def __init__(self) -> None:
        self._model = None
        self._model_ref = self._resolve_model_ref()
        self._cli_bin = self._resolve_cli_bin()
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate model ref at startup: local paths must exist, HF IDs are accepted as-is."""
        if is_local_path(self._model_ref):
            path = Path(self._model_ref)
            if not path.exists():
                raise FileNotFoundError(
                    f"Parakeet STT model path does not exist: {self._model_ref}"
                )
            if not path.is_dir():
                raise NotADirectoryError(
                    f"Parakeet STT model path is not a directory: {self._model_ref}"
                )
            logger.info("Parakeet STT: validated local model at %s", self._model_ref)
        else:
            logger.info("Parakeet STT: using HuggingFace model %s (downloaded on first use)", self._model_ref)

    def _resolve_cli_bin(self) -> str | None:
        cli_from_env = os.getenv(CLI_BIN_ENV_VAR)
        if cli_from_env:
            candidate = str(Path(cli_from_env).expanduser())
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
        model_from_env = os.getenv(MODEL_ENV_VAR)
        if model_from_env:
            return resolve_model_ref(model_from_env)

        configured_ref: str | None = None
        if config.stt and config.stt.services:
            parakeet_cfg = config.stt.services.get("parakeet")
            if parakeet_cfg and parakeet_cfg.model:
                configured_ref = parakeet_cfg.model

        return resolve_model_ref(configured_ref or DEFAULT_MODEL)

    def _ensure_model(self) -> bool:
        if load_stt_model is None:
            if self._cli_bin:
                logger.info(
                    "Parakeet STT using CLI fallback (%s); mlx_audio import failed: %s",
                    self._cli_bin,
                    MLX_AUDIO_IMPORT_ERROR,
                )
                return True
            logger.error("Parakeet STT unavailable: mlx_audio not installed and no CLI fallback")
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
            language: Ignored (Parakeet auto-detects). Kept for protocol compatibility.

        Returns:
            Transcribed text

        Raises:
            RuntimeError: If model cannot be loaded
            FileNotFoundError: If audio file does not exist
        """
        audio_path = Path(audio_file_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

        if not self._ensure_model():
            raise RuntimeError("Parakeet STT unavailable")

        import asyncio

        if self._model is None and self._cli_bin:
            return await asyncio.to_thread(self._transcribe_cli, audio_file_path)

        return await asyncio.to_thread(self._transcribe_local, audio_file_path)

    def _transcribe_local(self, audio_file_path: str) -> str:
        result = self._model.generate(audio_file_path)  # type: ignore[union-attr]
        text = result.text.strip()
        logger.debug("Parakeet STT: transcribed %d chars (local)", len(text))
        return text

    def _transcribe_cli(self, audio_file_path: str) -> str:
        import json
        import subprocess

        cmd = [
            self._cli_bin,  # type: ignore[list-item]
            "--model",
            self._model_ref,
            "--audio",
            audio_file_path,
            "--format",
            "json",
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Parakeet CLI failed: {(result.stderr or result.stdout).strip()}")
        data = json.loads(result.stdout)
        text = str(data.get("text", "")).strip()
        logger.debug("Parakeet STT: transcribed %d chars (CLI fallback)", len(text))
        return text

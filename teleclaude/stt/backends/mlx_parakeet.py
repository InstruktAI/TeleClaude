"""MLX Parakeet STT backend — local on-device transcription for Apple Silicon."""

import os
import shutil
import tempfile
from importlib import import_module
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config import config
from teleclaude.mlx_utils import is_local_path, resolve_model_ref

load_stt_model = None
mlx_audio_import_error: Exception | None = None
try:
    stt_module = import_module("mlx_audio.stt")
    load_candidate = getattr(stt_module, "load", None)
    if callable(load_candidate):
        load_stt_model = load_candidate
except Exception as import_error:  # noqa: BLE001 - keep backend available via CLI fallback
    mlx_audio_import_error = import_error

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
                raise FileNotFoundError(f"Parakeet STT model path does not exist: {self._model_ref}")
            if not path.is_dir():
                raise NotADirectoryError(f"Parakeet STT model path is not a directory: {self._model_ref}")
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
                    mlx_audio_import_error,
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

        if not self._ensure_model():
            raise RuntimeError("Parakeet STT unavailable")

        import asyncio

        if self._model is None and self._cli_bin:
            return await asyncio.to_thread(self._transcribe_cli, audio_file_path, language)

        return await asyncio.to_thread(self._transcribe_local, audio_file_path)

    def _transcribe_local(self, audio_file_path: str) -> str:
        result = self._model.generate(audio_file_path)  # type: ignore[union-attr]
        text = result.text.strip()
        logger.debug("Parakeet STT: transcribed %d chars (local)", len(text))
        return text

    def _transcribe_cli(self, audio_file_path: str, language: str | None = None) -> str:
        import json
        import subprocess

        if not self._cli_bin:
            raise RuntimeError("Parakeet CLI unavailable")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as output_file:
            output_path = output_file.name

        cmd = [
            self._cli_bin,
            "--model",
            self._model_ref,
            "--audio",
            audio_file_path,
            "--output-path",
            output_path,
            "--format",
            "json",
        ]
        if language:
            cmd.extend(["--language", language])

        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Parakeet CLI failed: {(result.stderr or result.stdout).strip()}")

            output_json = Path(output_path)
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
        finally:
            Path(output_path).unlink(missing_ok=True)

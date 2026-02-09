"""Qwen3 TTS backend - local MLX-based text-to-speech."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from instrukt_ai_logging import get_logger

try:
    from mlx_audio.tts.generate import generate_audio
    from mlx_audio.tts.utils import load_model
except Exception as import_error:  # noqa: BLE001 - keep backend available via CLI fallback
    generate_audio = None  # type: ignore[assignment]
    load_model = None  # type: ignore[assignment]
    MLX_AUDIO_IMPORT_ERROR = import_error
else:
    MLX_AUDIO_IMPORT_ERROR = None

from teleclaude.config import config

logger = get_logger(__name__)

DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
MODEL_ENV_VAR = "TELECLAUDE_QWEN3_MODEL"
INSTRUCT_ENV_VAR = "TELECLAUDE_QWEN3_INSTRUCT"
CLI_BIN_ENV_VAR = "TELECLAUDE_QWEN3_CLI_BIN"
DEFAULT_VOICE = "serena"
DEFAULT_VOICE_DESIGN_INSTRUCT = "A clear, natural conversational voice."


class Qwen3TTSBackend:
    """Local TTS using mlx-audio with Qwen3 model."""

    def __init__(self):
        self._model = None
        self._model_ref = self._resolve_model_ref()
        self._cli_bin = self._resolve_cli_bin()

    def _is_local_path(self, value: str) -> bool:
        """Check if value is an actual filesystem path rather than HF repo id."""
        return (
            value.startswith(".")
            or value.startswith("/")
            or value.startswith("~")
            or (len(value) > 1 and value[1] == ":")
        )

    def _normalize_model_ref(self, value: str) -> str:
        """Expand local paths but keep Hugging Face repo IDs untouched."""
        if self._is_local_path(value):
            return str(Path(value).expanduser())
        return value

    def _resolve_cli_bin(self) -> str | None:
        """Find mlx-audio CLI executable for subprocess fallback."""
        cli_from_env = os.getenv(CLI_BIN_ENV_VAR)
        if cli_from_env:
            candidate = str(Path(cli_from_env).expanduser())
            if Path(candidate).exists():
                return candidate

        from_path = shutil.which("mlx_audio.tts.generate")
        if from_path:
            return from_path

        default_tool_bin = str(Path("~/.local/bin/mlx_audio.tts.generate").expanduser())
        if Path(default_tool_bin).exists():
            return default_tool_bin

        return None

    def _resolve_model_ref(self) -> str:
        """Resolve model reference from env/config, falling back to default repo id."""
        model_from_env = os.getenv(MODEL_ENV_VAR)
        if model_from_env:
            return self._normalize_model_ref(model_from_env)

        if config.tts and config.tts.services:
            qwen3_cfg = config.tts.services.get("qwen3")
            if qwen3_cfg and qwen3_cfg.model:
                return self._normalize_model_ref(qwen3_cfg.model)

        return DEFAULT_MODEL

    def _ensure_model(self):
        """Lazy-load the model on first use."""
        if load_model is None:
            if self._cli_bin:
                logger.info(
                    "Qwen3 TTS using CLI fallback (%s); mlx_audio import failed in daemon interpreter: %s",
                    self._cli_bin,
                    MLX_AUDIO_IMPORT_ERROR,
                )
                return True
            logger.error("Failed to load Qwen3 TTS model: mlx_audio unavailable and no CLI fallback found")
            return False

        if self._model is not None:
            return True
        try:
            self._model_ref = self._resolve_model_ref()
            self._model = load_model(self._model_ref)
            logger.info("Qwen3 TTS model loaded: %s", self._model_ref)
            return True
        except Exception as e:
            logger.error("Failed to load Qwen3 TTS model (%s): %s", self._model_ref, e)
            return False

    def speak(self, text: str, voice_name: str | None = None) -> bool:
        """
        Speak text using Qwen3 TTS via mlx-audio.

        Args:
            text: Text to speak
            voice_name: Voice name (e.g., "serena", "ryan"). Falls back to DEFAULT_VOICE.

        Returns:
            True if successful, False otherwise
        """
        if not self._ensure_model():
            return False

        try:
            voice = voice_name or DEFAULT_VOICE
            model_type = getattr(getattr(self._model, "config", None), "tts_model_type", "unknown")

            if self._model is None and self._cli_bin:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    prefix = f"{tmp_dir}/tts_output"
                    cmd = [
                        self._cli_bin,
                        "--model",
                        self._model_ref,
                        "--text",
                        text,
                        "--voice",
                        voice,
                        "--file_prefix",
                        prefix,
                        "--join_audio",
                        "--audio_format",
                        "wav",
                        "--play",
                    ]
                    instruct = os.getenv(INSTRUCT_ENV_VAR)
                    if instruct:
                        cmd.extend(["--instruct", instruct])

                    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
                    if result.returncode != 0:
                        logger.error("Qwen3 CLI fallback failed: %s", (result.stderr or result.stdout).strip())
                        return False

                    audio_file = Path(f"{prefix}.wav")
                    if not audio_file.exists() or audio_file.stat().st_size == 0:
                        logger.error("Qwen3 CLI fallback produced no audio file (voice=%s)", voice)
                        return False

                logger.debug("Qwen3 TTS: spoke %d chars via CLI fallback (voice=%s)", len(text), voice)
                return True

            with tempfile.TemporaryDirectory() as tmp_dir:
                prefix = f"{tmp_dir}/tts_output"
                generate_kwargs = {
                    "model": self._model,
                    "text": text,
                    "voice": voice,
                    "file_prefix": prefix,
                    "play": False,
                    "join_audio": True,
                    "audio_format": "wav",
                    "verbose": False,
                }

                if model_type == "voice_design":
                    generate_kwargs["instruct"] = os.getenv(INSTRUCT_ENV_VAR, DEFAULT_VOICE_DESIGN_INSTRUCT)

                generate_audio(**generate_kwargs)

                audio_file = Path(f"{prefix}.wav")
                if not audio_file.exists() or audio_file.stat().st_size == 0:
                    logger.error(
                        "Qwen3 TTS produced no audio file (model=%s voice=%s)",
                        model_type,
                        voice,
                    )
                    return False

                result = subprocess.run(
                    ["afplay", str(audio_file)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    logger.error("Qwen3 playback failed: %s", (result.stderr or result.stdout).strip())
                    return False

            logger.debug("Qwen3 TTS: spoke %d chars (model=%s voice=%s)", len(text), model_type, voice)
            return True
        except Exception as e:
            logger.error("Qwen3 TTS failed: %s", e)
            return False

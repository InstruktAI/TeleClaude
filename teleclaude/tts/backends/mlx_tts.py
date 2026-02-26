"""Unified MLX TTS backend — local on-device speech synthesis for any mlx_audio model."""

import os
import shutil
import subprocess
import tempfile
from importlib import import_module
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.mlx_utils import resolve_model_ref

generate_audio = None
load_model = None
mlx_audio_import_error: Exception | None = None
_mlx_audio_import_attempted = False

logger = get_logger(__name__)

DEFAULT_VOICE_DESIGN_INSTRUCT = "A clear, natural conversational voice."
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _looks_like_python_script(path: str) -> bool:
    """Detect direct python script executables that can break on broken environments."""
    candidate = Path(path)
    if not candidate.is_file():
        return False
    if candidate.suffix == ".py":
        return True
    try:
        with candidate.open(encoding="utf-8", errors="ignore") as handle:
            first_line = handle.readline()
    except OSError:
        return False
    return first_line.startswith("#!") and ("python" in first_line)


class MLXTTSBackend:
    """Local TTS using mlx_audio. One instance per model in config."""

    def __init__(
        self,
        service_name: str,
        model_ref: str,
        params: dict[str, object] | None = None,  # guard: loose-dict - Backend kwargs vary by model.
    ) -> None:
        self._service_name = service_name
        self._model = None
        self._model_ref = resolve_model_ref(model_ref)
        self._params = params or {}
        self._cli_bin = self._resolve_cli_bin()
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate model ref at startup."""
        from teleclaude.mlx_utils import is_local_path

        if is_local_path(self._model_ref):
            path = Path(self._model_ref)
            if not path.exists():
                raise FileNotFoundError(
                    f"MLX TTS model path does not exist: {self._model_ref} (service: {self._service_name})"
                )
            if not path.is_dir():
                raise NotADirectoryError(
                    f"MLX TTS model path is not a directory: {self._model_ref} (service: {self._service_name})"
                )
            logger.info("MLX TTS [%s]: validated local model at %s", self._service_name, self._model_ref)
        else:
            logger.info(
                "MLX TTS [%s]: using HuggingFace model %s (downloaded on first use)",
                self._service_name,
                self._model_ref,
            )

    def _resolve_cli_bin(self) -> str | None:
        """Find mlx-audio CLI executable for subprocess fallback."""
        cli_from_env = os.getenv("TELECLAUDE_MLX_TTS_CLI_BIN")
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

    def _ensure_model(self) -> bool:
        """Lazy-load the model on first use."""
        global generate_audio, load_model, mlx_audio_import_error, _mlx_audio_import_attempted

        # CLI-only mode: never import mlx_audio when CLI backend exists.
        if self._cli_bin:
            logger.debug("MLX TTS [%s] using CLI backend only: %s", self._service_name, self._cli_bin)
            return True

        # Local model path: lazy-import mlx_audio only when CLI is unavailable.
        if not _mlx_audio_import_attempted:
            _mlx_audio_import_attempted = True
            try:
                tts_generate_module = import_module("mlx_audio.tts.generate")
                tts_utils_module = import_module("mlx_audio.tts.utils")
                generate_candidate = getattr(tts_generate_module, "generate_audio", None)
                load_candidate = getattr(tts_utils_module, "load_model", None)
                if callable(generate_candidate) and callable(load_candidate):
                    generate_audio = generate_candidate
                    load_model = load_candidate
            except Exception as import_error:  # noqa: BLE001 - keep backend available via CLI fallback
                mlx_audio_import_error = import_error

        if load_model is None:
            logger.error(
                "MLX TTS [%s] unavailable: mlx_audio import failed and no CLI fallback (%s)",
                self._service_name,
                mlx_audio_import_error,
            )
            return False

        if self._model is not None:
            return True
        try:
            self._model = load_model(self._model_ref)
            logger.info("MLX TTS [%s] model loaded: %s", self._service_name, self._model_ref)
            return True
        except Exception as e:
            logger.error("Failed to load MLX TTS model [%s] (%s): %s", self._service_name, self._model_ref, e)
            return False

    def speak(self, text: str, voice_name: str | None = None) -> bool:
        """Speak text using the loaded MLX TTS model.

        Args:
            text: Text to speak
            voice_name: Voice name if the model supports named voices. None for default.

        Returns:
            True if successful, False otherwise
        """
        if not self._ensure_model():
            return False

        try:
            voice = voice_name or self._service_name
            model_type = getattr(getattr(self._model, "config", None), "tts_model_type", "unknown")

            if self._model is None and self._cli_bin:
                return self._speak_cli(text, voice)

            return self._speak_local(text, voice, model_type)
        except Exception as e:
            logger.error("MLX TTS [%s] failed: %s", self._service_name, e)
            return False

    def _speak_cli(self, text: str, voice: str) -> bool:
        """Speak via CLI subprocess fallback."""
        if not self._cli_bin:
            return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            prefix = f"{tmp_dir}/tts_output"
            cmd = self._build_cli_command(
                text=text,
                voice=voice,
                file_prefix=prefix,
            )

            # Pass config params as CLI flags
            for key, val in self._params.items():
                cmd.extend([f"--{key}", str(val)])

            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(
                    "MLX TTS [%s] CLI failed: %s", self._service_name, (result.stderr or result.stdout).strip()
                )
                return False

            audio_file = Path(f"{prefix}.wav")
            if not audio_file.exists() or audio_file.stat().st_size == 0:
                logger.error("MLX TTS [%s] CLI produced no audio file (voice=%s)", self._service_name, voice)
                return False

            # Play audio explicitly (synchronous) while temp dir still exists.
            # This keeps the playback lock held for the full audio duration,
            # preventing overlapping playback that would otherwise cause echoes.
            play_result = subprocess.run(
                ["afplay", str(audio_file)],
                check=False,
                capture_output=True,
                text=True,
            )
            if play_result.returncode != 0:
                logger.error(
                    "MLX TTS [%s] CLI playback failed: %s",
                    self._service_name,
                    (play_result.stderr or play_result.stdout).strip(),
                )
                return False

        logger.debug("MLX TTS [%s]: spoke %d chars via CLI (voice=%s)", self._service_name, len(text), voice)
        return True

    def _build_cli_command(self, text: str, voice: str, file_prefix: str) -> list[str]:
        """Build the CLI command list for the fallback CLI path."""
        cli_args = [
            "--model",
            self._model_ref,
            "--text",
            text,
            "--voice",
            voice,
            "--file_prefix",
            file_prefix,
            "--join_audio",
            "--audio_format",
            "wav",
        ]

        if self._cli_bin and _looks_like_python_script(self._cli_bin):
            return [
                "uv",
                "run",
                "--quiet",
                "--project",
                str(_REPO_ROOT),
                "--extra",
                "mlx",
                "--with",
                "pip",
                "python",
                "-m",
                "mlx_audio.tts.generate",
                *cli_args,
            ]

        assert self._cli_bin is not None
        return [self._cli_bin, *cli_args]

    def _speak_local(self, text: str, voice: str, model_type: str) -> bool:
        """Speak via in-process mlx_audio."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            prefix = f"{tmp_dir}/tts_output"
            generate_kwargs: dict[str, object] = {  # guard: loose-dict - mlx_audio kwargs are dynamic.
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
                generate_kwargs["instruct"] = os.getenv("TELECLAUDE_MLX_TTS_INSTRUCT", DEFAULT_VOICE_DESIGN_INSTRUCT)

            # Merge config params, but never let user params override the internally-
            # controlled keys. Overriding `play` would cause double-playback (echo);
            # overriding `verbose` would leak model output to the daemon TTY.
            _protected = frozenset(
                {"play", "verbose", "model", "text", "voice", "file_prefix", "join_audio", "audio_format"}
            )
            generate_kwargs.update({k: v for k, v in self._params.items() if k not in _protected})

            generate_audio(**generate_kwargs)

            audio_file = Path(f"{prefix}.wav")
            if not audio_file.exists() or audio_file.stat().st_size == 0:
                logger.error(
                    "MLX TTS [%s] produced no audio (model_type=%s voice=%s)",
                    self._service_name,
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
                logger.error(
                    "MLX TTS [%s] playback failed: %s", self._service_name, (result.stderr or result.stdout).strip()
                )
                return False

        logger.debug(
            "MLX TTS [%s]: spoke %d chars (model_type=%s voice=%s)", self._service_name, len(text), model_type, voice
        )
        return True

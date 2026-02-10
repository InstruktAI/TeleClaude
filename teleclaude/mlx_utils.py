"""Shared utilities for MLX model backends (STT and TTS)."""

from pathlib import Path

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def is_local_path(value: str) -> bool:
    """Check if value is a filesystem path rather than a HuggingFace repo ID."""
    return (
        value.startswith(".") or value.startswith("/") or value.startswith("~") or (len(value) > 1 and value[1] == ":")
    )


def normalize_model_ref(value: str) -> str:
    """Expand local paths but keep HuggingFace repo IDs untouched."""
    if is_local_path(value):
        return str(Path(value).expanduser())
    return value


def probe_local_caches(repo_id: str) -> str | None:
    """Probe known local model caches for an already-downloaded model.

    Only checks LM Studio cache. HuggingFace Hub cache is skipped because
    mlx_audio's load_model handles HF repo IDs natively and snapshot hash
    paths break model type detection.

    Returns the local path if found, None otherwise.
    """
    org_model = repo_id.split("/", 1)
    if len(org_model) != 2:
        return None
    org, model = org_model

    # LM Studio: ~/.cache/lm-studio/models/{org}/{model}/
    lm_studio = Path.home() / ".cache" / "lm-studio" / "models" / org / model
    if lm_studio.is_dir():
        logger.info("Found model in LM Studio cache: %s", lm_studio)
        return str(lm_studio)

    return None


def resolve_model_ref(ref: str) -> str:
    """Resolve a model reference: expand local paths, probe caches for HF IDs."""
    if is_local_path(ref):
        return normalize_model_ref(ref)

    cached = probe_local_caches(ref)
    if cached:
        return cached

    return ref

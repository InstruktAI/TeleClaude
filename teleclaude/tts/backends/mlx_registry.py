"""MLX TTS backends built from the current configuration, on first request.

A service's backend exists only while that service's own ``enabled`` holds, so a
disabled service's model, parameters, CLI binary and instruction are never read.
The backend is rebuilt when the service's configuration changes, which is how a
service enabled later through the ``tts`` hot reload gets its backend on first use.
"""

import sys
from threading import Lock

from instrukt_ai_logging import get_logger

from teleclaude.config._models import TTSServiceConfig
from teleclaude.config.machine import config
from teleclaude.tts.backends.mlx_tts import MLXTTSBackend

logger = get_logger(__name__)

_MLX_PLATFORM = "darwin"
_REGISTERED_LOG = "Registered MLX TTS backend: %s (model=%s)"
_INIT_FAILED_LOG = "MLX TTS backend '%s' failed to initialize"
_lock = Lock()
# service name -> (configuration the backend was built from, the backend or None when it failed to initialize)
_built: dict[str, tuple[TTSServiceConfig, MLXTTSBackend | None]] = {}


def mlx_backend_for(service_name: str) -> MLXTTSBackend | None:
    """Return the service's MLX backend when it is enabled and names a model, building it if needed."""
    if sys.platform != _MLX_PLATFORM:
        return None
    services = config.tts.services if config.tts else None
    service_cfg = services.get(service_name) if services else None
    with _lock:
        if service_cfg is None or not service_cfg.enabled or not service_cfg.model:
            _built.pop(service_name, None)
            return None
        cached = _built.get(service_name)
        if cached is not None and cached[0] == service_cfg:
            return cached[1]
        try:
            backend: MLXTTSBackend | None = MLXTTSBackend(
                service_name,
                service_cfg.model,
                service_cfg.params,
                service_cfg.cli_bin,
                service_cfg.instruct,
            )
            logger.info(_REGISTERED_LOG, service_name, service_cfg.model)
        except Exception:
            logger.warning(_INIT_FAILED_LOG, service_name, exc_info=True)
            backend = None
        _built[service_name] = (service_cfg.model_copy(deep=True), backend)
        return backend

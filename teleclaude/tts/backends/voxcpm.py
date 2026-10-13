"""VoxCPM synthesis with service defaults overlaid by the selected voice."""

from collections.abc import Mapping

from teleclaude.config._models import VoxCPMServiceConfig
from teleclaude.tts.backends.mlx_tts import MLXTTSBackend


class VoxCPMTTSBackend(MLXTTSBackend):
    """Resolve per-voice parameters without changing the shared backend state."""

    def __init__(self, service_name: str, model_ref: str, config: VoxCPMServiceConfig) -> None:
        self._voice_config = config.model_copy(deep=True)
        super().__init__(service_name, model_ref, config.params, config.cli_bin, config.instruct)

    def _params_for_voice(self, voice: str) -> Mapping[object, object]:
        return self._voice_config.effective_params(voice)

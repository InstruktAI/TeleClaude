"""Alpha cartridge sandboxing — Docker sidecar execution tier."""

from teleclaude_events.alpha.bridge import AlphaBridgeCartridge
from teleclaude_events.alpha.container import AlphaContainerManager

__all__ = ["AlphaBridgeCartridge", "AlphaContainerManager"]

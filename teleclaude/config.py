"""Global configuration management.

Config is loaded once at daemon startup and available globally.
This avoids passing config as a parameter to every function.
"""

from typing import Any, Dict, Optional

_config: Optional[Dict[str, Any]] = None


def init_config(config: Dict[str, Any]) -> None:
    """Initialize global config.

    Called once at daemon startup after loading config.yml.

    Args:
        config: Configuration dictionary from config.yml (with env vars expanded)

    Raises:
        RuntimeError: If config is already initialized
    """
    global _config
    if _config is not None:
        raise RuntimeError("Config already initialized")
    _config = config


def get_config() -> Dict[str, Any]:
    """Get global configuration.

    Returns:
        Configuration dictionary

    Raises:
        RuntimeError: If config not initialized (call init_config first)
    """
    if _config is None:
        raise RuntimeError("Config not initialized. Call init_config() first.")
    return _config


def is_initialized() -> bool:
    """Check if config is initialized.

    Returns:
        True if config is initialized, False otherwise
    """
    return _config is not None

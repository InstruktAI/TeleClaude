"""Secret-safe capture for maintenance command output."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.config.errors import ConfigLoadError, describe_load_error
from teleclaude.config.secret_masking import declared_secret_values, mask_secret_values

logger = get_logger(__name__)

_OUTPUT_WITHHELD = "output withheld: the configuration that declares its secrets does not load ({reason})"
_SECRET_DISCOVERY_FAILED_EVENT = "post_commit_maintenance_secret_discovery_failed"


def secret_output_masker(root: Path) -> Callable[[str], str]:
    """Mask configured secrets in captured output, withholding it if secret discovery fails."""
    secrets: frozenset[str] | None = None
    unknown: str | None = None

    def mask(output: str) -> str:
        nonlocal secrets, unknown
        if secrets is None and unknown is None:
            try:
                secrets = declared_secret_values(root)
            except ConfigLoadError as error:
                unknown = describe_load_error(error)
            except Exception as error:
                unknown = type(error).__name__
                logger.error(_SECRET_DISCOVERY_FAILED_EVENT, project_root=str(root), error_kind=unknown)
        if secrets is None:
            return _OUTPUT_WITHHELD.format(reason=unknown)
        return mask_secret_values(output, secrets)

    return mask

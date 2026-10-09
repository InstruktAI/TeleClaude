"""The one error a configuration document raises when it cannot be read or validated."""

from __future__ import annotations


class ConfigLoadError(ValueError):
    """A configuration document could not be read or validated; the message names the file and the cause."""

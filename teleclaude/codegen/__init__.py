"""Code generation helpers for TeleClaude."""

from importlib import import_module
from types import ModuleType


def __getattr__(name: str) -> ModuleType:
    """Lazy-load codegen modules so package imports do not pre-execute CLI targets."""
    if name != "pydantic_to_typescript":
        raise AttributeError(name)
    return import_module("teleclaude.codegen.pydantic_to_typescript")

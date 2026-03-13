"""Cartridge manifest schema and error types."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class CartridgeManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    description: str
    version: str = "0.1.0"
    domain_affinity: list[str] = []  # empty = any domain
    depends_on: list[str] = []  # list of cartridge IDs within same domain
    output_slots: list[str] = []  # e.g. ["enrichment.git"] — conflict detection key
    personal: bool = False  # true = personal/member scope only
    module: str = "cartridge"  # Python module filename (without .py)


class CartridgeError(Exception):
    """Base exception for cartridge errors."""


class CartridgeCycleError(CartridgeError):
    """Raised when a dependency cycle is detected in the cartridge DAG."""


class CartridgeDependencyError(CartridgeError):
    """Raised when a declared dependency is missing."""


class CartridgeScopeError(CartridgeError):
    """Raised when a cartridge is used outside its declared domain affinity."""

"""Standardized metadata for adapter events.

Provides Pydantic models for type-safe event metadata across adapters.
"""

from typing import Optional

from pydantic import BaseModel, Field


class AdapterMetadata(BaseModel):  # type: ignore[explicit-any]
    """Standardized metadata for adapter events.

    This model ensures consistent metadata structure across all adapters
    while allowing platform-specific extensions.
    """

    # Required fields
    origin: str = Field(..., description="Origin (telegram, discord, api, mcp, etc.)")

    # Optional common fields
    user_id: Optional[str] = Field(None, description="Platform user ID (if human)")
    message_id: Optional[str] = Field(None, description="Platform message ID")
    origin_adapter: Optional[str] = Field(None, description="Origin adapter for observers")
    target_computer: Optional[str] = Field(None, description="Target computer for AI-to-AI sessions")

    # Platform-specific data (nested dicts)
    telegram: Optional[dict[str, object]] = Field(None, description="Telegram-specific data")  # noqa: loose-dict - Adapter-specific metadata
    redis: Optional[dict[str, object]] = Field(None, description="Redis-specific data")  # noqa: loose-dict - Adapter-specific metadata

    class Config:
        """Pydantic configuration."""

        extra = "allow"  # Allow additional platform-specific fields

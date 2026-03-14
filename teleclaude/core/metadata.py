"""Standardized metadata for adapter events.

Provides Pydantic models for type-safe event metadata across adapters.
"""

from pydantic import BaseModel, Field


class AdapterMetadata(BaseModel):  # type: ignore[explicit-any]
    """Standardized metadata for adapter events.

    This model ensures consistent metadata structure across all adapters
    while allowing platform-specific extensions.
    """

    # Required fields
    origin: str = Field(..., description="Origin (InputOrigin.*.value)")

    # Optional common fields
    user_id: str | None = Field(None, description="Platform user ID (if human)")
    message_id: str | None = Field(None, description="Platform message ID")
    last_input_origin: str | None = Field(
        None, description="Entry point that initiated or last interacted with the session"
    )
    target_computer: str | None = Field(None, description="Target computer for AI-to-AI sessions")

    # Platform-specific data (nested dicts)
    telegram: dict[str, object] | None = Field(  # guard: loose-dict - Adapter-specific metadata
        None, description="Telegram-specific data"
    )
    redis: dict[str, object] | None = Field(  # guard: loose-dict - Adapter-specific metadata
        None, description="Redis-specific data"
    )

    class Config:
        """Pydantic configuration."""

        extra = "allow"  # Allow additional platform-specific fields

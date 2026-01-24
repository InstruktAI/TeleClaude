"""TTS configuration models."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EventConfig:
    """Configuration for a TTS event."""

    enabled: bool
    message: Optional[str] = None


@dataclass
class ServiceVoiceConfig:
    """Voice configuration for a specific service."""

    name: str
    voice_id: Optional[str] = None  # ElevenLabs voice ID


@dataclass
class ServiceConfig:
    """Configuration for a single TTS service."""

    enabled: bool
    voices: list[ServiceVoiceConfig] = field(default_factory=list)


@dataclass
class TTSConfig:
    """Complete TTS configuration."""

    enabled: bool
    events: dict[str, EventConfig] = field(default_factory=dict)
    services: dict[str, ServiceConfig] = field(default_factory=dict)

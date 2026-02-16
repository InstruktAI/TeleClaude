"""Provider guidance registry for configuration fields."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FieldGuidance:
    """Guidance for a specific configuration field."""

    description: str
    steps: List[str] = field(default_factory=list)
    url: Optional[str] = None
    format_example: Optional[str] = None
    validation_hint: Optional[str] = None


class GuidanceRegistry:
    """Registry of guidance for configuration fields."""

    def __init__(self):
        self._registry: Dict[str, FieldGuidance] = {}
        self._populate_defaults()

    def register(self, field_path: str, guidance: FieldGuidance) -> None:
        self._registry[field_path] = guidance

    def get(self, field_path: str) -> Optional[FieldGuidance]:
        return self._registry.get(field_path)

    def _populate_defaults(self) -> None:
        # Telegram
        self.register(
            "adapters.telegram.bot_token",
            FieldGuidance(
                description="The authentication token for your Telegram bot.",
                steps=[
                    "Open Telegram and message @BotFather.",
                    "Send /newbot and follow instructions.",
                    "Copy the HTTP API access token provided.",
                ],
                url="https://t.me/BotFather",
                format_example="123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
                validation_hint="Starts with numbers, followed by colon",
            ),
        )
        self.register(
            "adapters.discord.token",
            FieldGuidance(
                description="The authentication token for your Discord bot.",
                steps=[
                    "Go to the Discord Developer Portal.",
                    "Create a new Application.",
                    "Go to the Bot tab and click 'Reset Token'.",
                    "Copy the token.",
                ],
                url="https://discord.com/developers/applications",
                format_example="MTA...",
                validation_hint="Long base64-like string",
            ),
        )
        # Add more defaults as needed...


# Global instance
guidance_registry = GuidanceRegistry()

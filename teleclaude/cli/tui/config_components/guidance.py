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
        self.register(
            "adapters.whatsapp.phone_number_id",
            FieldGuidance(
                description="Business phone number ID from your Meta WhatsApp app.",
                steps=[
                    "Create or open your app in Meta for Developers.",
                    "Add the WhatsApp product to the app.",
                    "Copy the Phone Number ID from the WhatsApp dashboard.",
                ],
                url="https://developers.facebook.com/",
                format_example="123456789012345",
                validation_hint="Numeric ID from Meta dashboard",
            ),
        )
        self.register(
            "adapters.whatsapp.access_token",
            FieldGuidance(
                description="System user access token for WhatsApp API calls.",
                steps=[
                    "Open Meta Business Manager and create a system user.",
                    "Assign your app assets to that system user.",
                    "Generate a long-lived token with whatsapp_business_messaging permission.",
                ],
                url="https://business.facebook.com/",
                format_example="EAAx...",
                validation_hint="Long-lived token with WhatsApp permissions",
            ),
        )
        self.register(
            "adapters.whatsapp.webhook_secret",
            FieldGuidance(
                description="App secret used to verify incoming webhook signatures.",
                steps=[
                    "Open your app in Meta App Dashboard.",
                    "Go to Settings > Basic.",
                    "Copy the App Secret value.",
                ],
                url="https://developers.facebook.com/apps/",
                format_example="abc123...",
                validation_hint="Use your exact App Secret value",
            ),
        )
        self.register(
            "adapters.whatsapp.verify_token",
            FieldGuidance(
                description="Shared verify token for webhook challenge-response.",
                steps=[
                    "Generate a random string and store it securely.",
                    "Set this value in TeleClaude as verify_token.",
                    "Use the same value in Meta webhook configuration.",
                ],
                url="https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks/",
                format_example="my-verify-token",
                validation_hint="Must exactly match Meta webhook verify token",
            ),
        )
        # Add more defaults as needed...


# Global instance
guidance_registry = GuidanceRegistry()

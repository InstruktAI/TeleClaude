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
        # Telegram — additional
        self.register(
            "adapters.telegram.supergroup_id",
            FieldGuidance(
                description="Chat ID of the Telegram supergroup the bot operates in.",
                steps=[
                    "Add your bot to the target group.",
                    "Send a message in the group.",
                    "Message @RawDataBot in the group, or call getUpdates on your bot.",
                    "Copy the chat.id value (starts with -100).",
                ],
                url="https://t.me/RawDataBot",
                format_example="-1001234567890",
                validation_hint="Negative number starting with -100",
            ),
        )
        self.register(
            "adapters.telegram.user_ids",
            FieldGuidance(
                description="Comma-separated Telegram user IDs allowed to interact with the bot.",
                steps=[
                    "Open Telegram and message @userinfobot from each account.",
                    "Copy the numeric user ID it returns.",
                    "Repeat for every user, then join with commas.",
                ],
                url="https://t.me/userinfobot",
                format_example="123456789,987654321",
                validation_hint="Comma-separated numeric IDs, no spaces",
            ),
        )
        # Discord — additional
        self.register(
            "adapters.discord.guild_id",
            FieldGuidance(
                description="The numeric ID of your Discord server (guild).",
                steps=[
                    "Open Discord and go to User Settings → Advanced.",
                    "Enable Developer Mode.",
                    "Right-click your server icon in the sidebar.",
                    "Click 'Copy Server ID'.",
                ],
                url="https://support.discord.com/hc/en-us/articles/206346498",
                format_example="123456789012345678",
                validation_hint="18-digit numeric ID",
            ),
        )
        # AI keys
        self.register(
            "adapters.ai.anthropic_api_key",
            FieldGuidance(
                description="API key for Anthropic Claude (used for summarization).",
                steps=[
                    "Go to the Anthropic Console.",
                    "Navigate to Settings → API Keys.",
                    "Click 'Create Key' and copy it.",
                ],
                url="https://console.anthropic.com/settings/keys",
                format_example="sk-ant-api03-...",
                validation_hint="Starts with sk-ant-",
            ),
        )
        self.register(
            "adapters.ai.openai_api_key",
            FieldGuidance(
                description="API key for OpenAI (secondary summarizer, Whisper STT, TTS).",
                steps=[
                    "Go to the OpenAI Platform.",
                    "Navigate to API keys.",
                    "Click 'Create new secret key' and copy it.",
                ],
                url="https://platform.openai.com/api-keys",
                format_example="sk-proj-...",
                validation_hint="Starts with sk-",
            ),
        )
        # Voice
        self.register(
            "adapters.voice.elevenlabs_api_key",
            FieldGuidance(
                description="API key for ElevenLabs text-to-speech.",
                steps=[
                    "Go to ElevenLabs and sign in.",
                    "Open Profile → API Keys.",
                    "Copy your API key or generate a new one.",
                ],
                url="https://elevenlabs.io/app/profile-settings",
                format_example="sk_...",
                validation_hint="Starts with sk_",
            ),
        )
        # Redis
        self.register(
            "adapters.redis.password",
            FieldGuidance(
                description="Redis password for multi-computer transport.",
                steps=[
                    "Redis Cloud: open your database → Security → copy the password.",
                    "Self-hosted: set 'requirepass' in redis.conf and use that value.",
                ],
                url="https://app.redislabs.com/",
                format_example="your-redis-password",
                validation_hint="Must match the password configured on your Redis server",
            ),
        )
        # WhatsApp — additional
        self.register(
            "adapters.whatsapp.template_name",
            FieldGuidance(
                description="Approved WhatsApp message template name for 24h window boundary messages.",
                steps=[
                    "Open Meta Business Manager.",
                    "Go to WhatsApp → Message Templates.",
                    "Find or create an approved template.",
                    "Copy the template name exactly as shown.",
                ],
                url="https://business.facebook.com/wa/manage/message-templates/",
                format_example="hello_world",
                validation_hint="Must match an approved template name exactly",
            ),
        )
        self.register(
            "adapters.whatsapp.template_language",
            FieldGuidance(
                description="Language code for the WhatsApp message template.",
                steps=[
                    "Open the same Message Templates view in Meta Business Manager.",
                    "Check the Language column for your template.",
                    "Copy the language code (e.g. en_US).",
                ],
                url="https://business.facebook.com/wa/manage/message-templates/",
                format_example="en_US",
                validation_hint="BCP 47 language tag with underscore (e.g. en_US)",
            ),
        )
        self.register(
            "adapters.whatsapp.business_number",
            FieldGuidance(
                description="Your WhatsApp Business phone number for invite deep links.",
                steps=[
                    "Open your WhatsApp Business account settings.",
                    "Copy your business phone number in E.164 format.",
                ],
                url="https://business.facebook.com/",
                format_example="+1234567890",
                validation_hint="E.164 format: + followed by country code and number",
            ),
        )


# Env var name → field path mapping for all _ADAPTER_ENV_VARS entries
_ENV_TO_FIELD: dict[str, str] = {
    "TELEGRAM_BOT_TOKEN": "adapters.telegram.bot_token",
    "TELEGRAM_SUPERGROUP_ID": "adapters.telegram.supergroup_id",
    "TELEGRAM_USER_IDS": "adapters.telegram.user_ids",
    "DISCORD_BOT_TOKEN": "adapters.discord.token",
    "DISCORD_GUILD_ID": "adapters.discord.guild_id",
    "ANTHROPIC_API_KEY": "adapters.ai.anthropic_api_key",
    "OPENAI_API_KEY": "adapters.ai.openai_api_key",
    "ELEVENLABS_API_KEY": "adapters.voice.elevenlabs_api_key",
    "REDIS_PASSWORD": "adapters.redis.password",
    "WHATSAPP_PHONE_NUMBER_ID": "adapters.whatsapp.phone_number_id",
    "WHATSAPP_ACCESS_TOKEN": "adapters.whatsapp.access_token",
    "WHATSAPP_WEBHOOK_SECRET": "adapters.whatsapp.webhook_secret",
    "WHATSAPP_VERIFY_TOKEN": "adapters.whatsapp.verify_token",
    "WHATSAPP_TEMPLATE_NAME": "adapters.whatsapp.template_name",
    "WHATSAPP_TEMPLATE_LANGUAGE": "adapters.whatsapp.template_language",
    "WHATSAPP_BUSINESS_NUMBER": "adapters.whatsapp.business_number",
}


def get_guidance_for_env(env_var_name: str) -> Optional[FieldGuidance]:
    """Look up guidance by env var name via the field-path mapping."""
    field_path = _ENV_TO_FIELD.get(env_var_name)
    if field_path is None:
        return None
    return guidance_registry.get(field_path)


# Global instance
guidance_registry = GuidanceRegistry()

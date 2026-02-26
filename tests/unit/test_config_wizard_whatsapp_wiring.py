from teleclaude.cli.tui.config_components.adapters import WhatsAppConfigComponent
from teleclaude.cli.tui.config_components.guidance import guidance_registry


class _NoopCallback:
    def on_animation_context_change(self, target: str, section_id: str, state: str, progress: float) -> None:
        return None

    def request_redraw(self) -> None:
        return None


def test_whatsapp_config_component_loads_whatsapp_env_vars():
    component = WhatsAppConfigComponent(_NoopCallback())
    assert [env.name for env in component.env_vars] == [
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_WEBHOOK_SECRET",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_TEMPLATE_NAME",
        "WHATSAPP_TEMPLATE_LANGUAGE",
        "WHATSAPP_BUSINESS_NUMBER",
    ]


def test_whatsapp_guidance_entries_present():
    phone_guidance = guidance_registry.get("adapters.whatsapp.phone_number_id")
    access_guidance = guidance_registry.get("adapters.whatsapp.access_token")
    webhook_guidance = guidance_registry.get("adapters.whatsapp.webhook_secret")
    verify_guidance = guidance_registry.get("adapters.whatsapp.verify_token")

    assert phone_guidance is not None
    assert access_guidance is not None
    assert webhook_guidance is not None
    assert verify_guidance is not None
    assert phone_guidance.format_example == "123456789012345"
    assert access_guidance.format_example == "EAAx..."
    assert webhook_guidance.format_example == "abc123..."
    assert verify_guidance.format_example == "my-verify-token"

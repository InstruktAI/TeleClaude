from teleclaude.cli.tui.config_components.guidance import guidance_registry


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

from teleclaude.config.schema import AgentDispatchConfig


def test_agent_dispatch_config_defaults():
    config = AgentDispatchConfig()
    assert config.enabled is True


def test_agent_dispatch_config_disabled():
    config = AgentDispatchConfig(enabled=False)
    assert config.enabled is False


def test_agent_dispatch_config_extra_fields():
    # model_config allows extra fields
    config = AgentDispatchConfig(enabled=True, extra_field="something")
    assert config.enabled is True
    assert config.extra_field == "something"

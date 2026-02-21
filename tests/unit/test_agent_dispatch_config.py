from teleclaude.config.schema import AgentDispatchConfig


def test_agent_dispatch_config_defaults():
    config = AgentDispatchConfig()
    assert config.enabled is True
    assert config.strengths == ""
    assert config.avoid == ""


def test_agent_dispatch_config_values():
    config = AgentDispatchConfig(enabled=False, strengths="Python, logic", avoid="Creative writing")
    assert config.enabled is False
    assert config.strengths == "Python, logic"
    assert config.avoid == "Creative writing"


def test_agent_dispatch_config_extra_fields():
    # model_config allows extra fields
    config = AgentDispatchConfig(enabled=True, extra_field="something")
    assert config.enabled is True
    assert config.extra_field == "something"

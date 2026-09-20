"""Installation adapter for config-owned agent-state inspection and mutation."""

from __future__ import annotations

import argparse

from teleclaude.agent_registry import AgentName
from teleclaude.config.machine_config_mutation import configure_agents, inspect_machine_config

_AGENTS = tuple(AgentName)
_AGENT_NAMES = tuple(agent.value for agent in _AGENTS)
_DEFAULT = "default"
_ENABLED = "enabled"
_UNSET = "unset"


def main() -> None:
    """Run the installer's narrow semantic agent configuration operation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--default")
    for agent in _AGENT_NAMES:
        parser.add_argument(f"--{agent}")
    args = parser.parse_args()
    if args.inspect:
        _inspect()
        return
    if not args.apply or args.default is None:
        parser.error("--apply and --default are required for mutation")
    default_agent = AgentName(args.default)
    enabled = {agent: getattr(args, agent.value) == "true" for agent in _AGENTS}
    configure_agents(enabled, default_agent)


def _inspect() -> None:
    """Print shell-consumable agent values from the current-schema inspection result."""
    raw = inspect_machine_config().raw
    agents = raw.get("agents", {})
    if not isinstance(agents, dict):
        return
    default = agents.get(_DEFAULT)
    if isinstance(default, str):
        print(f"{_DEFAULT}={default}")
    for agent in _AGENTS:
        entry = agents.get(agent.value)
        value = entry.get(_ENABLED) if isinstance(entry, dict) else None
        rendered = str(value).lower() if isinstance(value, bool) else _UNSET
        print(f"{agent.value}={rendered}")


if __name__ == "__main__":
    main()

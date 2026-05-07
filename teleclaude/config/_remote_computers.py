"""Remote computer config dataclass and parser."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RemoteComputerConfig:
    """Configuration for a remote computer defined in config."""

    name: str
    user: str | None = None
    host: str | None = None
    ip: str | None = None
    teleclaude_path: str | None = None
    bot_username: str | None = None


def parse_remote_computers(
    raw: object,  # guard: loose-dict - YAML mapping of remote computer entries
) -> list[RemoteComputerConfig]:
    """Parse remote_computers mapping from config into structured entries.

    Args:
        raw: Mapping of {name: properties} from YAML, or None/empty.

    Returns:
        List of RemoteComputerConfig objects.
    """
    if not raw:
        return []
    if not isinstance(raw, dict):
        raise ValueError(f"remote_computers must be a mapping of name → properties, got {type(raw).__name__}.")

    result: list[RemoteComputerConfig] = []
    for name, props in raw.items():
        if not isinstance(props, dict):
            raise ValueError(
                f"Invalid remote_computers entry '{name}': expected a mapping, got {type(props).__name__}."
            )
        result.append(
            RemoteComputerConfig(
                name=str(name),
                user=str(props["user"]) if props.get("user") else None,
                host=str(props["host"]) if props.get("host") else None,
                ip=str(props["ip"]) if props.get("ip") else None,
                teleclaude_path=str(props["teleclaude_path"]) if props.get("teleclaude_path") else None,
                bot_username=str(props["bot_username"]) if props.get("bot_username") else None,
            )
        )
    return result

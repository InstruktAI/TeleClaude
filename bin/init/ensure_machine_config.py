"""Installation adapter for schema-owned machine configuration generation."""

from teleclaude.config.generation import ensure_machine_config
from teleclaude.paths import MACHINE_CONFIG_PATH


def main() -> None:
    """Create the machine config when installation finds it absent."""
    print(ensure_machine_config(MACHINE_CONFIG_PATH))


if __name__ == "__main__":
    main()

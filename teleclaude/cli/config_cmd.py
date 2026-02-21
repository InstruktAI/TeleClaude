"""Daemon config commands: telec config get/patch/validate.

Operates on the daemon's config.yml (not user-facing teleclaude.yml).
"""

import json
import os
import sys
from pathlib import Path

import yaml


def handle_config_command(args: list[str]) -> None:
    """Dispatcher for config subcommands."""
    if not args:
        print("Error: Missing config subcommand (get, patch, validate)")
        sys.exit(1)

    subcommand = args[0]
    sub_args = args[1:]

    # Intercept --help/-h at any level
    if subcommand in ("--help", "-h") or "--help" in sub_args or "-h" in sub_args:
        from teleclaude.cli.telec import _usage

        print(_usage("config"))
        return

    if subcommand == "get":
        handle_get(sub_args)
    elif subcommand == "patch":
        handle_patch(sub_args)
    elif subcommand == "validate":
        handle_validate(sub_args)
    else:
        print(f"Error: Unknown config subcommand: {subcommand}")
        sys.exit(1)


def _deep_merge(
    base: dict[str, object],  # guard: loose-dict - recursive merge of arbitrary YAML
    override: dict[str, object],  # guard: loose-dict - recursive merge of arbitrary YAML
) -> dict[str, object]:  # guard: loose-dict - recursive merge of arbitrary YAML
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_config_path(project_root: Path | None) -> Path:
    """Resolve config.yml path."""
    if project_root:
        return project_root / "config.yml"

    env_path = os.getenv("TELECLAUDE_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    return Path.cwd() / "config.yml"


def _load_raw_config(
    path: Path,
) -> dict[str, object]:  # guard: loose-dict - raw YAML config
    """Load raw YAML config."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _extract_subtree(
    data: dict[str, object],  # guard: loose-dict - raw YAML config
    path: str,
) -> dict[str, object]:  # guard: loose-dict - raw YAML subtree
    """Extract a subtree rooted at the original hierarchy."""
    parts = path.split(".")
    result: dict[str, object] = {}  # guard: loose-dict - building subtree
    target: dict[str, object] = result  # guard: loose-dict - traversal pointer
    source: object = data

    for i, part in enumerate(parts):
        if not isinstance(source, dict) or part not in source:
            raise KeyError(f"Path not found: {path} (missing '{part}')")
        node = source[part]
        if i == len(parts) - 1:
            target[part] = node
        else:
            child: dict[str, object] = {}  # guard: loose-dict - subtree node
            target[part] = child
            target = child
            source = node

    return result


def handle_get(args: list[str]) -> None:
    """Handle 'telec config get'."""
    project_root: Path | None = None
    output_format = "yaml"
    paths: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--project-root", "-p") and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg in ("--format", "-f") and i + 1 < len(args):
            output_format = args[i + 1].lower()
            if output_format not in ("yaml", "json"):
                print(f"Error: Invalid output format: {output_format} (must be yaml or json)")
                sys.exit(1)
            i += 2
        elif arg.startswith("-"):
            print(f"Error: Unknown option: {arg}")
            sys.exit(1)
        else:
            paths.append(arg)
            i += 1

    config_path = _resolve_config_path(project_root)
    if not config_path.exists():
        print(f"Error: Config file not found at {config_path}")
        sys.exit(1)

    raw_config = _load_raw_config(config_path)

    if not paths:
        display_data = raw_config
    else:
        display_data: dict[str, object] = {}  # guard: loose-dict - aggregated subtrees
        errors = []
        for path in paths:
            try:
                subtree = _extract_subtree(raw_config, path)
                display_data = _deep_merge(display_data, subtree)
            except KeyError as e:
                errors.append(str(e))

        if errors:
            print("Errors encountered:")
            for err in errors:
                print(f"  {err}")
            sys.exit(1)

    if output_format == "json":
        print(json.dumps(display_data, indent=2))
    else:
        print(yaml.dump(display_data, sort_keys=False).strip())


def handle_patch(args: list[str]) -> None:
    """Handle 'telec config patch'."""
    project_root: Path | None = None
    output_format = "yaml"
    patch_yaml: str | None = None
    from_file: Path | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--project-root", "-p") and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg in ("--format", "-f") and i + 1 < len(args):
            output_format = args[i + 1].lower()
            if output_format not in ("yaml", "json"):
                print(f"Error: Invalid output format: {output_format} (must be yaml or json)")
                sys.exit(1)
            i += 2
        elif arg == "--from-file" and i + 1 < len(args):
            from_file = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg == "--yaml" and i + 1 < len(args):
            patch_yaml = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Error: Unknown option: {arg}")
            sys.exit(1)
        else:
            print(f"Error: Unexpected argument: {arg}")
            sys.exit(1)

    # Read patch data
    if from_file:
        with open(from_file, "r", encoding="utf-8") as f:
            patch_data = yaml.safe_load(f)
    elif patch_yaml:
        patch_data = yaml.safe_load(patch_yaml)
    else:
        if sys.stdin.isatty():
            print("Error: No patch provided. Use --yaml, --from-file, or pipe YAML to stdin.")
            sys.exit(1)
        patch_data = yaml.safe_load(sys.stdin.read())

    if not isinstance(patch_data, dict):
        print("Error: Patch must be a YAML mapping.")
        sys.exit(1)

    config_path = _resolve_config_path(project_root)
    if not config_path.exists():
        print(f"Error: Config file not found at {config_path}")
        sys.exit(1)

    raw_config = _load_raw_config(config_path)
    merged_raw = _deep_merge(raw_config, patch_data)

    # Atomic write
    temp_path = config_path.with_suffix(".tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(merged_raw, f, sort_keys=False)
        temp_path.replace(config_path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        print(f"Error: Writing config failed: {e}")
        sys.exit(1)

    if output_format == "json":
        print(json.dumps(merged_raw, indent=2))
    else:
        print(yaml.dump(merged_raw, sort_keys=False).strip())


def handle_validate(args: list[str]) -> None:
    """Handle 'telec config validate'."""
    project_root: Path | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--project-root", "-p") and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg.startswith("-"):
            print(f"Error: Unknown option: {arg}")
            sys.exit(1)
        else:
            print(f"Error: Unexpected argument: {arg}")
            sys.exit(1)

    config_path = _resolve_config_path(project_root)
    if not config_path.exists():
        print(f"Error: Config file not found at {config_path}")
        sys.exit(1)

    _load_raw_config(config_path)
    print(f"Configuration at {config_path} is valid.")

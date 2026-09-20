"""Daemon machine-config command adapters."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

from teleclaude.cli.telec import _maybe_show_help
from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.surface import CONFIG_GET, CONFIG_PATCH
from teleclaude.config import config_path
from teleclaude.config.machine_config_mutation import inspect_machine_config, patch_machine_config

CONFIG_PATH_PROVENANCE = "Config file: {path}"
MISSING_SUBCOMMAND_ERROR = "Error: Missing config subcommand (get, patch)"
PATCH_VALIDATION_ERROR = "Error: {message}"
_YAML = "yaml"
_JSON = "json"
_FORMAT_ERROR = "Error: Invalid output format: {format} (must be yaml or json)"
_UNEXPECTED_ARGUMENT_ERROR = "Error: Unexpected argument: {argument}"
_MISSING_PATCH_ERROR = "Error: No patch provided. Use --yaml, --from-file, or pipe YAML to stdin."
_PATCH_MAPPING_ERROR = "Error: Patch must be a YAML mapping."
_PATH_NOT_FOUND_ERROR = "Path not found: {path} (missing '{segment}')"
_ERRORS_HEADING = "Errors encountered:"
_ERROR_ROW = "  {error}"


def handle_config_command(args: list[str]) -> None:
    """Dispatch machine-config command adapters."""
    if not args:
        print(MISSING_SUBCOMMAND_ERROR)
        raise SystemExit(1)
    subcommand, sub_args = args[0], args[1:]
    if subcommand in ("--help", "-h") or "--help" in sub_args or "-h" in sub_args:
        _maybe_show_help("config", args)
        return
    if subcommand == "get":
        handle_get(sub_args)
        return
    if subcommand == "patch":
        handle_patch(sub_args)
        return
    print(f"Error: Unknown config subcommand: {subcommand}")
    raise SystemExit(1)


def handle_get(args: list[str]) -> None:
    """Render the config-owned current-schema inspection projection."""
    parsed = parse_command_args(CONFIG_GET, args)
    output_format = _output_format(parsed.value(F.FLAG_CONFIG_FORMAT))
    inspection = inspect_machine_config()
    raw = _as_mapping(inspection.raw)
    print(CONFIG_PATH_PROVENANCE.format(path=config_path), file=sys.stderr)
    _render(_select_paths(raw, list(parsed.positionals)) if parsed.positionals else raw, output_format)


def handle_patch(args: list[str]) -> None:
    """Submit a patch to the config-owned lock-scoped mutation contract."""
    parsed = parse_command_args(CONFIG_PATCH, args)
    if parsed.positionals:
        print(_UNEXPECTED_ARGUMENT_ERROR.format(argument=parsed.positionals[0]))
        raise SystemExit(1)
    output_format = _output_format(parsed.value(F.FLAG_CONFIG_FORMAT))
    patch = _read_patch(parsed.value(F.FLAG_CONFIG_FROM_FILE), parsed.value(F.FLAG_CONFIG_YAML))
    try:
        result = patch_machine_config(patch)
    except (OSError, ValueError) as error:
        print(PATCH_VALIDATION_ERROR.format(message=error))
        raise SystemExit(1) from error
    _render(_as_mapping(result.raw), output_format)


def _output_format(value: str | None) -> str:
    """Validate the declared command output format."""
    output_format = value.lower() if value is not None else _YAML
    if output_format not in (_YAML, _JSON):
        print(_FORMAT_ERROR.format(format=output_format))
        raise SystemExit(1)
    return output_format


def _read_patch(from_file: str | None, patch_yaml: str | None) -> dict[object, object]:
    """Read one command-supplied YAML patch without touching the machine document."""
    if from_file is not None:
        source = Path(from_file).expanduser().resolve()
        content = source.read_text(encoding="utf-8")
    elif patch_yaml is not None:
        content = patch_yaml
    else:
        if sys.stdin.isatty():
            print(_MISSING_PATCH_ERROR)
            raise SystemExit(1)
        content = sys.stdin.read()
    parsed = yaml.safe_load(content)
    if not isinstance(parsed, dict):
        print(_PATCH_MAPPING_ERROR)
        raise SystemExit(1)
    return parsed


def _select_paths(raw: dict[object, object], paths: list[str]) -> dict[object, object]:
    """Select declared subtrees from one inspected current-schema projection."""
    selected: dict[object, object] = {}
    path_errors: list[str] = []
    for path in paths:
        try:
            _merge(selected, _extract_subtree(raw, path))
        except KeyError as error:
            path_errors.append(str(error))
    if path_errors:
        print(_ERRORS_HEADING)
        for path_error in path_errors:
            print(_ERROR_ROW.format(error=path_error))
        raise SystemExit(1)
    return selected


def _extract_subtree(raw: Mapping[object, object], path: str) -> dict[object, object]:
    """Extract one dotted path without exposing raw-document mutation."""
    result: dict[object, object] = {}
    target = result
    source: object = raw
    parts = path.split(".")
    for index, part in enumerate(parts):
        if not isinstance(source, Mapping) or part not in source:
            raise KeyError(_PATH_NOT_FOUND_ERROR.format(path=path, segment=part))
        node = source[part]
        if index == len(parts) - 1:
            target[part] = node
            continue
        child: dict[object, object] = {}
        target[part] = child
        target = child
        source = node
    return result


def _merge(base: dict[object, object], addition: Mapping[object, object]) -> None:
    """Merge selected subtrees into the command output only."""
    for key, value in addition.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge(current, value)
        else:
            base[key] = value


def _render(data: Mapping[object, object], output_format: str) -> None:
    """Render one config-owned result at the CLI edge."""
    if output_format == _JSON:
        print(json.dumps(data, indent=2))
        return
    print(yaml.dump(dict(data), sort_keys=False).strip())


def _as_mapping(data: Mapping[object, object]) -> dict[object, object]:
    """Copy the output envelope without changing the config-owned source projection."""
    return dict(data)

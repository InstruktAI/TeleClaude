"""Config surface markdown export for release inspector prompts.

Generates a structured markdown document from Pydantic config models,
suitable for injection into AI inspector prompts at pipeline runtime.
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from teleclaude.config.schema import GlobalConfig, PersonConfig, ProjectConfig

_MODELS: list[tuple[str, type[BaseModel]]] = [
    ("Global Config", GlobalConfig),
    ("Project Config", ProjectConfig),
    ("Person Config", PersonConfig),
]


def export_config_markdown() -> str:
    """Return a markdown document describing the TeleClaude config surface.

    Pure function — no I/O, no daemon. Safe for CI usage.
    """
    sections: list[str] = ["# TeleClaude Configuration Surface\n"]

    for label, model in _MODELS:
        schema = model.model_json_schema()
        sections.append(f"## {label}\n")
        sections.append(f"Model: `{model.__name__}`\n")

        props = schema.get("properties", {})
        if props:
            sections.append("| Field | Type | Description |")
            sections.append("|-------|------|-------------|")
            for field_name, field_info in sorted(props.items()):
                field_type = _resolve_type(field_info)
                desc = field_info.get("description", field_info.get("title", ""))
                sections.append(f"| `{field_name}` | {field_type} | {desc} |")
            sections.append("")

        # Include $defs for nested models
        defs = schema.get("$defs", {})
        if defs:
            sections.append(f"### {label} — Nested Types\n")
            for def_name, def_schema in sorted(defs.items()):
                sections.append(f"#### {def_name}\n")
                def_props = def_schema.get("properties", {})
                if def_props:
                    sections.append("| Field | Type | Description |")
                    sections.append("|-------|------|-------------|")
                    for field_name, field_info in sorted(def_props.items()):
                        field_type = _resolve_type(field_info)
                        desc = field_info.get("description", field_info.get("title", ""))
                        sections.append(f"| `{field_name}` | {field_type} | {desc} |")
                    sections.append("")

    # Append raw JSON schema as reference
    sections.append("## Raw JSON Schema\n")
    sections.append("```json")
    sections.append(json.dumps(GlobalConfig.model_json_schema(), indent=2))
    sections.append("```\n")

    return "\n".join(sections)


def _resolve_type(
    field_info: dict[str, object],  # guard: loose-dict - JSON schema field info is untyped at runtime
) -> str:
    """Extract a human-readable type string from a JSON Schema field."""
    if "type" in field_info:
        return str(field_info["type"])
    if "anyOf" in field_info:
        any_of = field_info["anyOf"]
        types = [_resolve_type(t) for t in any_of] if isinstance(any_of, list) else []
        return " | ".join(types)
    if "allOf" in field_info:
        all_of = field_info["allOf"]
        types = [_resolve_type(t) for t in all_of] if isinstance(all_of, list) else []
        return " & ".join(types)
    if "$ref" in field_info:
        ref = str(field_info["$ref"])
        return ref.rsplit("/", 1)[-1]
    if "const" in field_info:
        return repr(field_info["const"])
    if "enum" in field_info:
        enum_vals = field_info["enum"]
        return " | ".join(repr(v) for v in enum_vals) if isinstance(enum_vals, list) else "any"
    return "any"

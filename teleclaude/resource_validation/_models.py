"""Shared patterns, warning/error collection, and schema loading for resource validation."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Repo root (package form: three levels up from this file)
# ---------------------------------------------------------------------------

_PACKAGE_DIR = Path(__file__).resolve().parent  # teleclaude/resource_validation/
REPO_ROOT = _PACKAGE_DIR.parents[1]  # repo root (above teleclaude/)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from teleclaude.constants import TAXONOMY_TYPES  # noqa: E402

# ---------------------------------------------------------------------------
# Shared patterns
# ---------------------------------------------------------------------------

_REQUIRED_READS_HEADER = re.compile(r"^##\s+Required reads\s*$", re.IGNORECASE)
_SOURCES_HEADER = re.compile(r"^##\s+Sources\s*$", re.IGNORECASE)
_SEE_ALSO_HEADER = re.compile(r"^##\s+See also\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^#{1,6}\s+")
_REQUIRED_READ_LINE = re.compile(r"^\s*-\s*@(\S+)\s*$")
_H1_LINE = re.compile(r"^#\s+")
_H2_LINE = re.compile(r"^##\s+")
_INLINE_REF_LINE = re.compile(r"^\s*(?:-\s*)?@\S+")
_CODE_FENCE_LINE = re.compile(r"^```")
_HTML_COMMENT_LINE = re.compile(r"^\s*<!--")
_INLINE_CODE_SPAN = re.compile(r"`[^`]*`")
_SEE_ALSO_LIST_LINE = re.compile(r"^\s*-\s+(.+)$")

_SCHEMA_PATH = REPO_ROOT / "scripts" / "snippet_schema.yaml"

_ARTIFACT_REF_ORDER = TAXONOMY_TYPES.copy()

# ---------------------------------------------------------------------------
# Warning collection
# ---------------------------------------------------------------------------


class ValidationWarning(TypedDict):
    code: str
    path: str


_WARNINGS: list[dict[str, str]] = []
_ERRORS: list[dict[str, str]] = []


def _warn(code: str, path: str = "", **kwargs: str) -> None:
    payload: dict[str, str] = {"code": code, "path": path}
    payload.update({k: str(v) for k, v in kwargs.items()})
    _WARNINGS.append(payload)


def _error(code: str, path: str = "", **kwargs: str) -> None:
    payload: dict[str, str] = {"code": code, "path": path}
    payload.update({k: str(v) for k, v in kwargs.items()})
    _ERRORS.append(payload)


def get_warnings() -> list[dict[str, str]]:
    return list(_WARNINGS)


def get_errors() -> list[dict[str, str]]:
    return list(_ERRORS)


def clear_warnings() -> None:
    _WARNINGS.clear()
    _ERRORS.clear()


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


class GlobalSchemaConfig(TypedDict, total=False):
    required_reads_title: str
    see_also_title: str
    sources_title: str
    require_h1: bool
    require_h1_first: bool
    require_required_reads: bool
    required_reads_header_level: int
    see_also_header_level: int
    sources_header_level: int
    allow_h3: bool


class SectionSchema(TypedDict):
    required: list[str]
    allowed: list[str]


class SchemaConfig(TypedDict):
    global_: GlobalSchemaConfig
    sections: dict[str, SectionSchema]


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _load_schema() -> SchemaConfig:
    if not _SCHEMA_PATH.exists():
        return {"global_": {}, "sections": {}}
    raw = yaml.safe_load(_SCHEMA_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {"global_": {}, "sections": {}}

    global_raw = raw.get("global", {})
    global_cfg: GlobalSchemaConfig = {}
    if isinstance(global_raw, dict):
        for key, value in global_raw.items():
            if key in {
                "required_reads_title",
                "see_also_title",
                "sources_title",
            } and isinstance(value, str):
                global_cfg[key] = value
            elif key in {
                "require_h1",
                "require_h1_first",
                "require_required_reads",
                "allow_h3",
            } and isinstance(value, bool):
                global_cfg[key] = value
            elif key in {
                "required_reads_header_level",
                "see_also_header_level",
                "sources_header_level",
            } and isinstance(value, int):
                global_cfg[key] = value

    sections_raw = raw.get("sections", {})
    sections: dict[str, SectionSchema] = {}
    if isinstance(sections_raw, dict):
        for section_name, section_raw in sections_raw.items():
            if not isinstance(section_raw, dict):
                continue
            required = _as_str_list(section_raw.get("required"))
            allowed = _as_str_list(section_raw.get("allowed"))
            sections[str(section_name)] = {"required": required, "allowed": allowed}

    return {"global_": global_cfg, "sections": sections}


_SCHEMA = _load_schema()

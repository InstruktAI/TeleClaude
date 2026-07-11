"""Lazy MCP registry tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from teleclaude.mcp.registry import (
    DEFAULT_IDLE_TTL_SECONDS,
    McpConcurrency,
    McpTransport,
    RegistryError,
    extract_env_references,
    load_effective_registry,
    load_native_publish_servers,
)

pytestmark = pytest.mark.functional

_SPEC = "project/spec/feature/agent_runtime/lazy-mcp-runtime"
_FIRECRAWL_TRIGGER = "Use when pages mention ${IGNORED_TRIGGER}."
_UPDATED_TRIGGER = "Use for updated MCP discovery."
_JSON_SCHEMA_STRING_TYPE = "string"


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.mark.spec(_SPEC, "UC-LMCP-7")
def test_registry_merges_teleclaude_jsonc_with_local_overlay(tmp_path: Path, snapshot: object) -> None:
    _write(
        tmp_path / "teleclaude-mcp.jsonc",
        """
        {
          // comments and trailing commas are valid JSONC
          "servers": {
            "base": {
              "command": "base-command",
              "args": ["base-arg"],
              "env": { "TOKEN": "${BASE_TOKEN}" },
            }
          },
        }
        """,
    )
    _write(
        tmp_path / "teleclaude-mcp.local.jsonc",
        """
        {
          "servers": {
            "base": {
              "args": ["local-arg"],
              "env": { "LOCAL_TOKEN": "$LOCAL_TOKEN" }
            },
            "local-only": { "command": "local-command" }
          }
        }
        """,
    )

    registry = load_effective_registry(tmp_path)

    base = registry.require_server("base")
    assert {
        "base": base.to_wire_dict(),
        "local_only": registry.require_server("local-only").to_wire_dict(),
    } == snapshot
    assert base.env == {"TOKEN": "${BASE_TOKEN}", "LOCAL_TOKEN": "$LOCAL_TOKEN"}
    assert base.transport == McpTransport.STDIO


@pytest.mark.spec(_SPEC, "UC-LMCP-7")
def test_canonical_registry_wins_over_compatibility_import(tmp_path: Path, snapshot: object) -> None:
    _write_json(
        tmp_path / "mcp.json",
        {
            "mcpServers": {
                "shared": {"command": "compat-command"},
                "compat-only": {"command": "compat-only-command"},
            }
        },
    )
    _write(
        tmp_path / "teleclaude-mcp.jsonc",
        """
        {
          "servers": {
            "shared": { "command": "canonical-command" }
          }
        }
        """,
    )

    registry = load_effective_registry(tmp_path)

    assert {
        "shared": registry.require_server("shared").to_wire_dict(),
        "compat_only": registry.require_server("compat-only").to_wire_dict(),
    } == snapshot


@pytest.mark.spec(_SPEC, "UC-LMCP-1")
def test_registry_applies_runtime_defaults_and_catalog_is_secret_safe(tmp_path: Path) -> None:
    _write(
        tmp_path / "teleclaude-mcp.jsonc",
        """
        {
          "servers": {
            "firecrawl": {
              "trigger": "Use when pages mention ${IGNORED_TRIGGER}.",
              "command": "npx",
              "args": ["-y", "firecrawl-mcp"],
              "env": { "FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}" }
            }
          }
        }
        """,
    )

    server = load_effective_registry(tmp_path).require_server("firecrawl")

    assert server.lazy is True
    assert server.native_publish is False
    assert server.trigger == _FIRECRAWL_TRIGGER
    assert server.idle_ttl_seconds == DEFAULT_IDLE_TTL_SECONDS
    assert server.concurrency == McpConcurrency.SERIALIZED
    assert server.env_references == ("FIRECRAWL_API_KEY",)
    assert "trigger" not in server.to_launch_dict()
    assert server.to_catalog_dict()["requiresEnv"] == ["FIRECRAWL_API_KEY"]
    assert server.to_catalog_dict()["trigger"] == _FIRECRAWL_TRIGGER
    assert "FIRECRAWL_API_KEY" not in json.dumps(server.to_catalog_dict().get("command", ""))


@pytest.mark.spec(_SPEC, "UC-LMCP-6")
def test_fingerprint_ignores_trigger_but_tracks_runtime_lease_options(tmp_path: Path) -> None:
    _write(
        tmp_path / "teleclaude-mcp.jsonc",
        """
        {
          "servers": {
            "runtime": {
              "trigger": "Use when pages mention ${IGNORED_TRIGGER}.",
              "command": "npx",
              "args": ["-y", "runtime-mcp"],
              "lazy": {
                "idleTtlSec": 900,
                "concurrency": "serialized"
              }
            }
          }
        }
        """,
    )

    server = load_effective_registry(tmp_path).require_server("runtime")
    fingerprint = server.fingerprint({})

    assert "trigger" not in server.to_fingerprint_dict()
    assert replace(server, trigger=_UPDATED_TRIGGER).fingerprint({}) == fingerprint
    assert replace(server, idle_ttl_seconds=60).fingerprint({}) != fingerprint
    assert replace(server, concurrency=McpConcurrency.PARALLEL).fingerprint({}) != fingerprint
    assert replace(server, native_publish=True).fingerprint({}) != fingerprint


@pytest.mark.spec(_SPEC, "UC-LMCP-6")
def test_registry_rejects_malformed_jsonc_and_invalid_wrapper(tmp_path: Path) -> None:
    _write(tmp_path / "teleclaude-mcp.jsonc", '{ "servers": { "bad": { "command": "x", } ')

    with pytest.raises(RegistryError):
        load_effective_registry(tmp_path)

    _write(tmp_path / "teleclaude-mcp.jsonc", '{ "servers": [] }')
    with pytest.raises(RegistryError):
        load_effective_registry(tmp_path)

    _write(
        tmp_path / "teleclaude-mcp.jsonc",
        '{ "servers": { "bad": { "command": "x", "lazy": { "toolTimeoutSec": 15 } } } }',
    )
    with pytest.raises(RegistryError):
        load_effective_registry(tmp_path)


@pytest.mark.spec(_SPEC, "UC-LMCP-6")
def test_registry_extracts_env_placeholders_from_all_launch_fields(tmp_path: Path) -> None:
    spec = {
        "stdio": {
            "trigger": "Ignore ${TRIGGER_TOKEN}",
            "command": "${COMMAND_BIN}",
            "args": ["--token=${ARG_TOKEN}"],
            "env": {"TARGET_TOKEN": "${ENV_TOKEN}"},
        },
        "remote": {
            "trigger": "Ignore $REMOTE_TRIGGER_TOKEN too",
            "transport": "http",
            "url": "https://example.test/${URL_TOKEN}",
            "headers": {"Authorization": "Bearer ${HEADER_TOKEN}"},
        },
    }

    assert extract_env_references(spec) == [
        "COMMAND_BIN",
        "ARG_TOKEN",
        "ENV_TOKEN",
        "URL_TOKEN",
        "HEADER_TOKEN",
    ]


@pytest.mark.spec(_SPEC, "UC-LMCP-7")
def test_native_publication_requires_explicit_opt_in(tmp_path: Path, snapshot: object) -> None:
    _write(
        tmp_path / "teleclaude-mcp.jsonc",
        """
        {
          "servers": {
            "managed": { "command": "managed-command" },
            "native": { "command": "native-command", "nativePublish": true }
          }
        }
        """,
    )

    native = load_native_publish_servers(tmp_path)

    assert list(native) == ["native"]
    assert native["native"] == snapshot


@pytest.mark.spec(_SPEC, "UC-LMCP-8")
def test_schema_validates_representative_registry_examples() -> None:
    schema = json.loads(Path("schemas/teleclaude-mcp.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    validator.validate(
        {
            "servers": {
                "stdio": {
                    "trigger": "Use for stdio examples.",
                    "transport": "stdio",
                    "command": "npx",
                    "args": ["-y", "example-mcp"],
                    "lazy": {
                        "idleTtlSec": DEFAULT_IDLE_TTL_SECONDS,
                        "concurrency": "serialized",
                    },
                },
                "remote": {
                    "transport": "http",
                    "url": "https://example.test/mcp",
                    "headers": {"Authorization": "Bearer ${EXAMPLE_TOKEN}"},
                },
            }
        }
    )
    with pytest.raises(ValidationError):
        validator.validate({"mcpServers": {"legacy": {"command": "npx"}}})
    with pytest.raises(ValidationError):
        validator.validate({"servers": {"bad": {"transport": "http"}}})
    with pytest.raises(ValidationError):
        validator.validate({"servers": {"bad": {"command": "npx", "lazy": False}}})
    with pytest.raises(ValidationError):
        validator.validate({"servers": {"bad": {"command": "npx", "lazy": {"toolTimeoutSec": 15}}}})
    server_schema = schema["$defs"]["server"]
    stdio_rule, remote_rule = server_schema["allOf"]
    assert stdio_rule["then"]["required"] == ["command"]
    assert remote_rule["then"]["required"] == ["url"]
    assert server_schema["additionalProperties"] is False
    assert schema["properties"]["servers"]["description"]
    assert server_schema["properties"]["trigger"]["type"] == _JSON_SCHEMA_STRING_TYPE
    assert server_schema["properties"]["nativePublish"]["default"] is False
    assert server_schema["properties"]["lazy"]["properties"]["idleTtlSec"]["default"] == DEFAULT_IDLE_TTL_SECONDS

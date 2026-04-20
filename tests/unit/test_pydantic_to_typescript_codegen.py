# guard: no-companion

# pyright: reportMissingImports=false
# mypy: ignore-errors
"""Test spec (xfail) for pydantic-to-typescript-codegen.

Behavioral contracts for generating TypeScript type definitions from Pydantic
BaseModel subclasses in teleclaude/api_models.py. All tests are marked xfail —
they document the expected behavior and fail cleanly before implementation.
Remove the xfail marker from ``pytestmark`` once all tests pass after
implementation.
"""

from __future__ import annotations

import inspect
import re

import pytest
from pydantic import BaseModel

from teleclaude import api_models
from teleclaude.codegen import pydantic_to_typescript
from teleclaude.session_fields import SessionDTOIdentityFields, SessionDTOTimestampFields

pytestmark = [
    pytest.mark.unit,
]

# ---------------------------------------------------------------------------
# Test data — dynamically discover all BaseModel subclasses in api_models
# ---------------------------------------------------------------------------

_API_MODEL_CLASSES: dict[str, type[BaseModel]] = {
    name: cls
    for name, cls in inspect.getmembers(api_models, inspect.isclass)
    if issubclass(cls, BaseModel) and cls.__module__ == api_models.__name__
}

_REQUEST_TYPE_NAMES = sorted(name for name in _API_MODEL_CLASSES if name.endswith("Request"))

# Models with Literal type annotations and their expected string union values.
_LITERAL_FIELDS: list[tuple[str, str, list[str]]] = [
    ("SessionDTO", "agent_status", ["active", "idle", "unknown"]),
    ("PersonDTO", "role", ["admin", "member", "contributor", "newcomer"]),
    ("OperationStatusDTO", "state", ["queued", "running", "completed", "failed", "stale", "cancelled"]),
    ("CreateSessionRequest", "launch_kind", ["empty", "agent", "agent_then_message", "agent_resume"]),
    ("AgentAvailabilityDTO", "agent", ["claude", "gemini", "codex"]),
    ("ErrorEventDataDTO", "severity", ["warning", "error", "critical"]),
    ("ChiptunesStatusDTO", "playback", ["cold", "loading", "playing", "paused"]),
    ("MessageDTO", "role", ["user", "assistant", "system"]),
    ("MessageDTO", "type", ["text", "compaction", "tool_use", "tool_result", "thinking"]),
]

# Fields that were missing from the hand-maintained TodoInfo (the drift that motivates R8).
_TODO_PREVIOUSLY_MISSING = [
    "prepare_phase",
    "integration_phase",
    "finalize_status",
    "delivered_at",
    "after",
    "group",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_codegen():
    """Import the codegen module. Fails with ImportError if not implemented."""
    return pydantic_to_typescript


def _generate() -> str:
    """Call the generation function and return TypeScript output string."""
    mod = _import_codegen()
    fn = getattr(mod, "generate", None)
    assert fn is not None, "codegen module must expose a generate() function"
    result = fn()
    assert isinstance(result, str), "generate() must return a string"
    assert len(result) > 0, "generate() must return non-empty TypeScript"
    return result


def _collect_all_fields(model_cls: type[BaseModel]) -> set[str]:
    """Collect all field names including inherited ones from a Pydantic model."""
    return set(model_cls.model_fields.keys())


# ---------------------------------------------------------------------------
# R1 — Single source of truth
# ---------------------------------------------------------------------------


class TestSingleSourceOfTruth:
    """Generated TypeScript must derive from Pydantic models in api_models.py."""

    def test_codegen_module_exists(self) -> None:
        """The codegen module must be importable."""
        _import_codegen()

    def test_generate_function_exists(self) -> None:
        """The codegen module must expose a callable generate() function."""
        mod = _import_codegen()
        assert callable(getattr(mod, "generate", None)), "generate() must be callable"

    def test_generation_reflects_api_models_fields(self) -> None:
        """Generated output must contain fields from api_models.py Pydantic models."""
        output = _generate()
        # Verify key models' unique fields appear — proves derivation from models.
        assert re.search(r"\blaunch_kind\b", output), "CreateSessionRequest.launch_kind missing"
        assert re.search(r"\btmux_session_name\b", output), "SessionDTO.tmux_session_name missing"
        assert re.search(r"\bhas_requirements\b", output), "TodoDTO.has_requirements missing"
        assert re.search(r"\bpoll_after_ms\b", output), "OperationStatusDTO.poll_after_ms missing"


# ---------------------------------------------------------------------------
# R2 — Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Running generation twice must produce byte-identical output."""

    def test_generate_twice_produces_identical_output(self) -> None:
        """Two consecutive calls must return byte-identical output."""
        first = _generate()
        second = _generate()
        assert first == second, "Generation is not idempotent — two runs produced different output"

    def test_output_is_deterministic_across_repeated_runs(self) -> None:
        """Three consecutive runs must all produce the same result."""
        results = [_generate() for _ in range(3)]
        assert results[0] == results[1] == results[2], "Output varies across repeated runs"


# ---------------------------------------------------------------------------
# R3 — Completeness
# ---------------------------------------------------------------------------


class TestCompleteness:
    """All BaseModel subclasses in api_models.py must have corresponding TS types."""

    @pytest.mark.parametrize("model_name", sorted(_API_MODEL_CLASSES.keys()))
    def test_model_has_typescript_type(self, model_name: str) -> None:
        """Each API model must have a corresponding TypeScript type or interface."""
        output = _generate()
        # The name may be transformed (DTO removed/renamed) — search for a type
        # declaration containing the base concept name.
        base = model_name.replace("DTO", "").replace("Request", "")
        if not base:
            base = model_name
        # Must find an interface or type whose name contains the base
        pattern = rf"(?:export\s+)?(?:interface|type)\s+\w*{re.escape(base)}\w*"
        assert re.search(pattern, output), f"No TypeScript type found for {model_name} (searched base: '{base}')"


# ---------------------------------------------------------------------------
# R3 (cont.) — Inheritance flattening
# ---------------------------------------------------------------------------


class TestInheritanceFlattening:
    """Multi-inheritance models must produce flat interfaces with all inherited fields."""

    def test_session_dto_has_all_timestamp_fields(self) -> None:
        """SessionDTO must include every field from SessionDTOTimestampFields."""
        output = _generate()
        for field_name in SessionDTOTimestampFields.model_fields:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"Inherited timestamp field '{field_name}' missing from SessionDTO output"
            )

    def test_session_dto_has_all_identity_fields(self) -> None:
        """SessionDTO must include every field from SessionDTOIdentityFields."""
        output = _generate()
        for field_name in SessionDTOIdentityFields.model_fields:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"Inherited identity field '{field_name}' missing from SessionDTO output"
            )

    def test_session_dto_has_own_fields(self) -> None:
        """SessionDTO must include its directly-defined fields."""
        output = _generate()
        own_fields = {"session_id", "title", "status", "active_agent", "agent_status", "visibility"}
        for field_name in own_fields:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"SessionDTO own field '{field_name}' missing from output"
            )

    def test_session_dto_total_field_count(self) -> None:
        """SessionDTO must have 20+ fields after flattening — proves full inheritance."""
        all_fields = _collect_all_fields(_API_MODEL_CLASSES["SessionDTO"])
        assert len(all_fields) >= 20, f"SessionDTO should have 20+ fields after flattening (got {len(all_fields)})"
        output = _generate()
        for field_name in all_fields:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"Flattened SessionDTO field '{field_name}' missing from output"
            )

    def test_activity_event_subtypes_contain_base_fields(self) -> None:
        """Activity event subtypes must include BaseAgentActivityEventDTO fields."""
        output = _generate()
        base_fields = _collect_all_fields(_API_MODEL_CLASSES["BaseAgentActivityEventDTO"])
        for field_name in base_fields:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"Base activity field '{field_name}' missing from output"
            )

    def test_project_with_todos_contains_base_project_fields(self) -> None:
        """ProjectWithTodosDTO must include all ProjectDTO base fields."""
        output = _generate()
        base_fields = _collect_all_fields(_API_MODEL_CLASSES["ProjectDTO"])
        for field_name in base_fields:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"ProjectDTO base field '{field_name}' missing from ProjectWithTodos output"
            )
        # Plus its own fields
        assert re.search(r"\btodos\b", output), "ProjectWithTodosDTO.todos missing"
        assert re.search(r"\bhas_roadmap\b", output), "ProjectWithTodosDTO.has_roadmap missing"

    def test_project_with_todos_uses_extends_syntax(self) -> None:
        """Single-parent DTO inheritance must emit a TypeScript extends clause."""
        output = _generate()
        assert re.search(r"export\s+interface\s+ProjectWithTodosInfo\s+extends\s+ProjectInfo\s*\{", output), (
            "ProjectWithTodosDTO must render as ProjectWithTodosInfo extends ProjectInfo"
        )

    def test_activity_event_subtypes_use_extends_syntax(self) -> None:
        """Activity event subtypes must extend BaseAgentActivityEvent in TypeScript."""
        output = _generate()
        subtype_names = (
            "UserPromptSubmitActivityEvent",
            "ToolUseActivityEvent",
            "ToolDoneActivityEvent",
            "AgentStopActivityEvent",
        )
        for subtype_name in subtype_names:
            assert re.search(
                rf"export\s+interface\s+{re.escape(subtype_name)}\s+extends\s+BaseAgentActivityEvent\s*\{{",
                output,
            ), f"{subtype_name} must extend BaseAgentActivityEvent"

    def test_agent_activity_union_alias_is_exported(self) -> None:
        """AgentActivityEvent must be emitted as a discriminated union alias."""
        output = _generate()
        assert re.search(
            (
                r"export\s+type\s+AgentActivityEvent\s*=\s*"
                r"UserPromptSubmitActivityEvent\s*\|\s*"
                r"ToolUseActivityEvent\s*\|\s*"
                r"ToolDoneActivityEvent\s*\|\s*"
                r"AgentStopActivityEvent\s*;"
            ),
            output,
            re.DOTALL,
        ), "AgentActivityEvent union alias missing from generated output"


# ---------------------------------------------------------------------------
# R5 — Frontend naming convention
# ---------------------------------------------------------------------------


class TestNamingConvention:
    """Response DTOs drop 'DTO' suffix per frontend convention (Info for data DTOs)."""

    @pytest.mark.parametrize(
        "python_name,expected_ts_name",
        [
            ("SessionDTO", "SessionInfo"),
            ("TodoDTO", "TodoInfo"),
            ("PersonDTO", "PersonInfo"),
            ("ComputerDTO", "ComputerInfo"),
            ("ProjectDTO", "ProjectInfo"),
            ("JobDTO", "JobInfo"),
            ("MessageDTO", "MessageInfo"),
        ],
    )
    def test_data_dto_renamed_to_info(self, python_name: str, expected_ts_name: str) -> None:
        """Data DTOs must be available with 'Info' suffix in generated or re-exported TS."""
        output = _generate()
        assert re.search(rf"\b{re.escape(expected_ts_name)}\b", output), (
            f"{python_name} must appear as '{expected_ts_name}' in output"
        )

    @pytest.mark.parametrize("request_name", _REQUEST_TYPE_NAMES)
    def test_request_types_preserve_names(self, request_name: str) -> None:
        """Request types must keep their Python names in TypeScript."""
        output = _generate()
        assert re.search(rf"\b{re.escape(request_name)}\b", output), (
            f"Request type '{request_name}' must appear with same name in output"
        )

    def test_no_raw_dto_suffix_in_type_declarations(self) -> None:
        """No exported interface/type should carry the 'DTO' suffix."""
        output = _generate()
        dto_decls = re.findall(r"(?:export\s+)?(?:interface|type)\s+(\w+DTO)\b", output)
        assert len(dto_decls) == 0, f"Found DTO-suffixed type declarations in output: {dto_decls}"


# ---------------------------------------------------------------------------
# R7 — String literal unions (not enum)
# ---------------------------------------------------------------------------


class TestStringLiteralUnions:
    """Python Literal types must become TS string literal unions, never enum."""

    @pytest.mark.parametrize("model_name,field_name,expected_values", _LITERAL_FIELDS)
    def test_literal_produces_string_union(self, model_name: str, field_name: str, expected_values: list[str]) -> None:
        """Literal annotation must produce a string literal union type."""
        output = _generate()
        for value in expected_values:
            assert f'"{value}"' in output, (
                f"Literal value '{value}' from {model_name}.{field_name} not found as string literal in output"
            )

    def test_no_enum_declarations_in_output(self) -> None:
        """Generated output must never contain TypeScript enum declarations."""
        output = _generate()
        enum_matches = re.findall(r"\benum\s+\w+", output)
        assert len(enum_matches) == 0, f"Found enum declarations: {enum_matches}. Use string literal unions."

    def test_agent_name_union_values(self) -> None:
        """Agent name Literal must produce all three values as string literals."""
        output = _generate()
        for name in ("claude", "gemini", "codex"):
            assert f'"{name}"' in output, f"Agent name '{name}' missing from output"

    def test_operation_state_union_values(self) -> None:
        """OperationStatusDTO.state Literal values must all appear as string literals."""
        output = _generate()
        for state in ("queued", "running", "completed", "failed", "stale", "cancelled"):
            assert f'"{state}"' in output, f"Operation state '{state}' missing from output"


# ---------------------------------------------------------------------------
# R8 — Field completeness parity
# ---------------------------------------------------------------------------


class TestFieldCompletenessParity:
    """Every Python DTO field must appear in its TypeScript counterpart."""

    @pytest.mark.parametrize("model_name", sorted(_API_MODEL_CLASSES.keys()))
    def test_all_fields_present_in_output(self, model_name: str) -> None:
        """Each field of the Python model must appear in the generated TypeScript."""
        model_cls = _API_MODEL_CLASSES[model_name]
        all_fields = _collect_all_fields(model_cls)
        output = _generate()
        for field_name in all_fields:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"Field '{field_name}' from {model_name} not in generated TypeScript"
            )

    def test_todo_dto_includes_previously_missing_fields(self) -> None:
        """TodoDTO must include fields that were missing from hand-maintained types."""
        output = _generate()
        for field_name in _TODO_PREVIOUSLY_MISSING:
            assert re.search(rf"\b{re.escape(field_name)}\b", output), (
                f"Previously-missing TodoDTO field '{field_name}' not in output"
            )

    def test_session_dto_field_type_mappings(self) -> None:
        """SessionDTO fields must have correct TypeScript types."""
        output = _generate()
        assert re.search(r"\bsession_id\s*:\s*string\b", output), "session_id must be string"
        assert re.search(r"\btitle\s*:\s*string\b", output), "title must be string"
        assert re.search(r"\bstatus\s*:\s*string\b", output), "status must be string"

    def test_todo_dto_field_type_mappings(self) -> None:
        """TodoDTO fields must have correct TypeScript types."""
        output = _generate()
        assert re.search(r"\bslug\s*:\s*string\b", output), "slug must be string"
        assert re.search(r"\bhas_requirements\s*:\s*boolean\b", output), "has_requirements must be boolean"
        assert re.search(r"\bhas_impl_plan\s*:\s*boolean\b", output), "has_impl_plan must be boolean"
        assert re.search(r"\bfindings_count\s*:\s*number\b", output), "findings_count must be number"
        assert re.search(r"\bfiles\s*:\s*(?:string\[\]|Array<string>)", output), "files must be string[]"

    def test_computer_dto_field_type_mappings(self) -> None:
        """ComputerDTO fields must have correct TypeScript types."""
        output = _generate()
        assert re.search(r"\bname\s*:\s*string\b", output), "name must be string"
        assert re.search(r"\bis_local\s*:\s*boolean\b", output), "is_local must be boolean"


# ---------------------------------------------------------------------------
# R9 — Generated file hygiene
# ---------------------------------------------------------------------------


class TestGeneratedFileHygiene:
    """Generated TypeScript must have proper auto-generation markers and syntax."""

    def test_output_contains_autogenerated_header(self) -> None:
        """Generated output must start with a comment indicating auto-generation."""
        output = _generate()
        header = output[:500].lower()
        assert any(
            marker in header for marker in ("auto-generated", "autogenerated", "do not edit", "generated from")
        ), "Generated file must contain an auto-generated header comment"

    def test_output_contains_export_declarations(self) -> None:
        """Generated output must contain exported type declarations."""
        output = _generate()
        exports = re.findall(r"export\s+(?:interface|type)\s+\w+", output)
        assert len(exports) >= 10, f"Expected at least 10 exported types, found {len(exports)}"

    def test_output_does_not_contain_python_artifacts(self) -> None:
        """Generated output must not leak Python-specific syntax."""
        output = _generate()
        for artifact in ("BaseModel", "Field(", "Literal[", "model_config", "ConfigDict"):
            assert artifact not in output, f"Python artifact '{artifact}' leaked into generated TypeScript"

    def test_output_uses_named_exports_only(self) -> None:
        """Generated file must use named exports, not default exports."""
        output = _generate()
        assert "export default" not in output, "Must use named exports, not default exports"


# ---------------------------------------------------------------------------
# R10 — Re-export layer
# ---------------------------------------------------------------------------


class TestReExportLayer:
    """The re-export module maps generated names to frontend-preferred names."""

    def test_generated_types_are_importable_for_reexport(self) -> None:
        """Generated output must export enough types for the re-export layer to consume."""
        output = _generate()
        export_count = len(re.findall(r"\bexport\s+(?:interface|type)\b", output))
        model_count = len(_API_MODEL_CLASSES)
        # At least half the models should produce exports (some may share types)
        assert export_count >= model_count // 2, (
            f"Expected at least {model_count // 2} exports for {model_count} models, found {export_count}"
        )


class TestBuildIntegration:
    """The code generator exposes a file-writing entry point for build automation."""

    def test_codegen_module_exposes_main(self) -> None:
        """The codegen module must expose a callable main() entry point."""
        mod = _import_codegen()
        assert callable(getattr(mod, "main", None)), "main() must be callable for build integration"

    def test_main_writes_requested_output_file(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """main() must write generated output to the requested path."""
        mod = _import_codegen()
        output_path = tmp_path / "generated-types.ts"
        result = mod.main([str(output_path)])
        assert result == 0, "main() must return zero on success"
        output = output_path.read_text(encoding="utf-8")
        assert "export interface CreateSessionRequest" in output, "main() did not write generated TypeScript"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestOptionalFieldHandling:
    """Python optional fields (str | None) must produce correct TS nullable types."""

    def test_optional_string_field(self) -> None:
        """str | None fields must produce nullable or optional TS types."""
        output = _generate()
        # SessionDTO.last_input_origin is str | None
        match = re.search(r"last_input_origin\??\s*:\s*(.+?)[\n;]", output)
        assert match, "last_input_origin must appear with a type annotation"
        type_annotation = match.group(1).strip()
        assert "null" in type_annotation or "?" in output[max(0, match.start() - 5) : match.start()], (
            f"Optional field 'last_input_origin' must be nullable or optional (got: {type_annotation})"
        )

    def test_optional_int_field(self) -> None:
        """int | None fields must produce nullable or optional TS number types."""
        output = _generate()
        # KeysRequest.count is int | None
        match = re.search(r"\bcount\??\s*:\s*(.+?)[\n;]", output)
        assert match, "count field must appear with a type annotation"
        type_annotation = match.group(1).strip()
        assert "number" in type_annotation, f"int|None field must include 'number' (got: {type_annotation})"


class TestTypeMapping:
    """Python types must map to correct TypeScript types."""

    def test_list_str_produces_string_array(self) -> None:
        """list[str] must produce string[] or Array<string>."""
        output = _generate()
        match = re.search(r"\bfiles\s*:\s*(.+?)[\n;]", output)
        assert match, "files field must have a type annotation"
        assert "string[]" in match.group(1) or "Array<string>" in match.group(1), (
            f"list[str] → string[] or Array<string> (got: {match.group(1).strip()})"
        )

    def test_dict_produces_record_type(self) -> None:
        """dict[str, ...] must produce Record or index signature type."""
        output = _generate()
        # RenderWidgetRequest.data is a dict-typed field
        match = re.search(r"\bdata\s*:\s*(.+?)[\n;]", output)
        assert match, "data field must have a type annotation"
        type_str = match.group(1).strip()
        assert "Record" in type_str or "{" in type_str, (
            f"dict field must produce Record or index signature (got: {type_str})"
        )

    def test_bool_produces_boolean(self) -> None:
        """bool fields must produce TypeScript boolean."""
        output = _generate()
        match = re.search(r"\bis_local\s*:\s*(.+?)[\n;]", output)
        assert match, "is_local must have a type annotation"
        assert "boolean" in match.group(1), f"bool → boolean (got: {match.group(1).strip()})"

    def test_int_produces_number(self) -> None:
        """int fields must produce TypeScript number."""
        output = _generate()
        match = re.search(r"\bpoll_after_ms\s*:\s*(.+?)[\n;]", output)
        assert match, "poll_after_ms must have a type annotation"
        assert "number" in match.group(1), f"int → number (got: {match.group(1).strip()})"

    def test_float_produces_number(self) -> None:
        """float fields must produce TypeScript number."""
        output = _generate()
        match = re.search(r"\bposition_seconds\s*:\s*(.+?)[\n;]", output)
        assert match, "position_seconds must have a type annotation"
        assert "number" in match.group(1), f"float → number (got: {match.group(1).strip()})"

    def test_nested_model_reference(self) -> None:
        """Fields referencing other Pydantic models must use the generated TS type name."""
        output = _generate()
        # SettingsDTO.tts references TTSSettingsDTO
        # In TS, this should reference the generated type (TTSSettings or similar)
        match = re.search(r"\btts\s*:\s*(.+?)[\n;]", output)
        assert match, "tts field must have a type annotation"
        type_str = match.group(1).strip()
        # Must reference a named type, not inline the structure
        assert re.search(r"\b\w+Settings\b", type_str) or re.search(r"\bTTS\w+\b", type_str), (
            f"Nested model reference 'tts' must use a named type (got: {type_str})"
        )

    def test_list_of_nested_models(self) -> None:
        """list[SomeModel] must produce SomeType[] or Array<SomeType>."""
        output = _generate()
        # SessionsInitialDataDTO.sessions is list[SessionDTO]
        match = re.search(r"\bsessions\s*:\s*(.+?)[\n;]", output)
        assert match, "sessions field must have a type annotation"
        type_str = match.group(1).strip()
        # Must be an array of a named type
        assert "[]" in type_str or "Array<" in type_str, f"list[SessionDTO] must produce array type (got: {type_str})"

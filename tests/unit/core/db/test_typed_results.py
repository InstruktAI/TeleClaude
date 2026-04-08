# guard: no-companion
# pylint: disable=import-outside-toplevel,import-error,no-name-in-module,too-few-public-methods
"""Test spec (xfail) for R4: typed query results at all boundaries.

Every database query across all four databases returns typed results. No raw
sqlite3.Row, aiosqlite.Row, untyped dict, or positional row access at module
boundaries. Type checker must pass with no new untyped returns at query boundaries.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Static verification: no raw Row types in public function signatures
# ---------------------------------------------------------------------------


class TestNoRawRowTypesInSignatures:
    """Public functions must not expose sqlite3.Row or aiosqlite.Row in return types."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "teleclaude.core.todos_db._base",
            "teleclaude.core.todos_db._roadmap",
            "teleclaude.core.todos_db._state",
            "teleclaude.core.todos_db._artifacts",
        ],
    )
    def test_todos_db_modules_have_no_raw_row_returns(self, module_path: str) -> None:
        """todos_db modules do not return sqlite3.Row or aiosqlite.Row."""
        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        # After migration, these modules should use typed results
        assert "sqlite3.Row" not in source or "row_factory" in source, (
            f"{module_path} still references sqlite3.Row outside row_factory setup"
        )
        assert "aiosqlite.Row" not in source or "row_factory" in source, (
            f"{module_path} still references aiosqlite.Row outside row_factory setup"
        )

    def test_mirrors_store_has_no_raw_row_returns(self) -> None:
        """mirrors/store.py public functions return typed dataclasses, not sqlite3.Row."""
        from teleclaude.mirrors import store

        source = inspect.getsource(store)
        # Check that public function return annotations don't include sqlite3.Row
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue  # Skip private helpers
                if node.returns:
                    return_source = ast.unparse(node.returns)
                    assert "sqlite3.Row" not in return_source, f"Public function {node.name} returns sqlite3.Row"


class TestNoPositionalRowAccess:
    """No row[index] positional access at module boundaries after migration."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "teleclaude.core.todos_db._roadmap",
            "teleclaude.core.todos_db._state",
            "teleclaude.core.todos_db._artifacts",
        ],
    )
    def test_todos_db_has_no_positional_row_access(self, module_path: str) -> None:
        """todos_db query results use named attribute access, not row[index]."""
        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        # Pattern: row[0], row[1], etc. — positional access on query results
        # This is fragile under schema changes and indicates untyped results.
        # After SQLAlchemy migration, all access should be via named attributes.
        positional_accesses = re.findall(r"row\[\d+\]", source)
        assert not positional_accesses, f"{module_path} still uses positional row access: {positional_accesses}"


class TestNoUntypedDictsAtBoundaries:
    """No untyped dict returns at public function boundaries."""

    # The pattern we detect: a generic dict with str keys and Any values.
    _UNTYPED_DICT_PATTERN = "dict[str, " + "Any]"

    @pytest.mark.parametrize(
        "module_path",
        [
            "teleclaude.core.todos_db._roadmap",
            "teleclaude.core.todos_db._state",
            "teleclaude.core.todos_db._show",
        ],
    )
    def test_todos_db_query_functions_return_typed_results(self, module_path: str) -> None:
        """Query functions in todos_db return typed models, not plain dicts."""
        mod = importlib.import_module(module_path)
        source = inspect.getsource(mod)
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                if node.returns:
                    return_source = ast.unparse(node.returns)
                    # Detect untyped dict returns (generic dict with str keys and Any values)
                    assert self._UNTYPED_DICT_PATTERN not in return_source, (
                        f"{module_path}.{node.name} returns untyped dict"
                    )


class TestTodosDbQueryResultTypes:
    """After migration, todos_db queries return typed ORM models or dataclasses."""

    def test_roadmap_list_returns_typed_entries(self) -> None:
        """list_entries has an explicit return annotation that does not include Row."""
        from teleclaude.core.todos_db._roadmap import TodosDbRoadmapMixin

        hints = inspect.get_annotations(TodosDbRoadmapMixin.list_entries, eval_str=False)
        assert "return" in hints, "list_entries has no return annotation"
        return_hint = str(hints["return"])
        assert "Row" not in return_hint, "list_entries still returns raw Row objects"

    def test_state_get_returns_typed_result(self) -> None:
        """get_state has an explicit return annotation that does not include Row."""
        from teleclaude.core.todos_db._state import TodosDbStateMixin

        hints = inspect.get_annotations(TodosDbStateMixin.get_state, eval_str=False)
        assert "return" in hints, "get_state has no return annotation"
        return_hint = str(hints["return"])
        assert "Row" not in return_hint


class TestMirrorsQueryResultTypes:
    """mirrors/store.py queries return typed dataclasses."""

    def test_search_mirrors_returns_typed_results(self) -> None:
        """search_mirrors returns list[MirrorSearchResult], not raw rows."""
        from teleclaude.mirrors.store import search_mirrors

        hints = inspect.get_annotations(search_mirrors, eval_str=False)
        return_hint = str(hints.get("return", ""))
        assert "MirrorSearchResult" in return_hint

    def test_get_mirror_returns_typed_result(self) -> None:
        """get_mirror returns MirrorRecord | None, not raw row."""
        from teleclaude.mirrors.store import get_mirror

        hints = inspect.get_annotations(get_mirror, eval_str=False)
        return_hint = str(hints.get("return", ""))
        assert "MirrorRecord" in return_hint

    def test_list_mirrors_returns_typed_results(self) -> None:
        """list_mirrors returns list[MirrorRecord], not raw rows."""
        from teleclaude.mirrors.store import list_mirrors

        hints = inspect.get_annotations(list_mirrors, eval_str=False)
        return_hint = str(hints.get("return", ""))
        assert "MirrorRecord" in return_hint

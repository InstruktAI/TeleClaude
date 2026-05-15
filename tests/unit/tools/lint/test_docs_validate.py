from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit


def _load_docs_validate() -> ModuleType:
    script_path = Path(__file__).resolve().parents[4] / "tools" / "lint" / "docs_validate.py"
    spec = importlib.util.spec_from_file_location("docs_validate_lint", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestArtifactKind:
    def test_classifies_command_path_as_artifact(self) -> None:
        module = _load_docs_validate()
        assert module._artifact_kind("agents/commands/next-build.md") is not None

    def test_does_not_classify_partials_outside_commands(self) -> None:
        module = _load_docs_validate()
        assert module._artifact_kind("agents/_partials/slug-resolution.md") is None

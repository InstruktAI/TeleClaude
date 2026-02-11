"""Guardrails for project setup layering boundaries."""

from pathlib import Path


def test_project_setup_init_module_stays_thin() -> None:
    """__init__.py must remain a re-export surface, not an implementation host."""
    init_file = Path("teleclaude/project_setup/__init__.py")
    content = init_file.read_text(encoding="utf-8")

    assert "def " not in content
    assert "subprocess" not in content
    assert "input(" not in content


def test_bin_init_has_no_embedded_python_blocks() -> None:
    """bin/init.sh must call entrypoints, not embed Python heredocs."""
    init_script = Path("bin/init.sh")
    content = init_script.read_text(encoding="utf-8")

    forbidden_markers = (
        "<<'PY'",
        '<<"PY"',
        "python - <<",
        "python3 - <<",
    )
    for marker in forbidden_markers:
        assert marker not in content

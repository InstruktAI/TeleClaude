from pathlib import Path

import pytest

from scripts import migrate_requires


@pytest.mark.unit
def test_migrate_requires_appends_missing(tmp_path: Path) -> None:
    text = (
        "---\n"
        "id: example/doc\n"
        "type: policy\n"
        "scope: project\n"
        "description: Example\n"
        "requires:\n"
        "  - example/one\n"
        "  - example/two\n"
        "---\n"
        "\n"
        "# Title\n"
        "\n"
        "## Required reads\n"
        "- @example/one\n"
        "\n"
        "Body\n"
    )
    updated = migrate_requires.migrate_text(text)
    assert "requires:" not in updated
    assert "## Required reads" in updated
    assert "- @example/one" in updated
    assert "- @example/two" in updated


@pytest.mark.unit
def test_migrate_requires_inserts_section(tmp_path: Path) -> None:
    text = (
        "---\n"
        "id: example/doc\n"
        "type: policy\n"
        "scope: project\n"
        "description: Example\n"
        "requires:\n"
        "  - example/one\n"
        "---\n"
        "\n"
        "# Title\n"
        "\n"
        "Body\n"
    )
    updated = migrate_requires.migrate_text(text)
    assert "requires:" not in updated
    assert "## Required reads" in updated
    assert "- @example/one" in updated

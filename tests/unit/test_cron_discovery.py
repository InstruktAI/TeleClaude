from pathlib import Path

import pytest

from teleclaude.cron.discovery import discover_youtube_subscribers


@pytest.mark.unit
def test_discover_youtube_subscribers_supports_flat_interest_list(tmp_path: Path) -> None:
    root = tmp_path / ".teleclaude"
    person_dir = root / "people" / "alice"
    person_dir.mkdir(parents=True)
    (person_dir / "teleclaude.yml").write_text(
        "subscriptions:\n  - type: youtube\n    source: youtube.csv\ninterests:\n  - ai\n  - devtools\n",
        encoding="utf-8",
    )

    subscribers = discover_youtube_subscribers(root)
    assert len(subscribers) == 1
    assert subscribers[0].scope == "person"
    assert subscribers[0].name == "alice"
    assert subscribers[0].tags == ["ai", "devtools"]


@pytest.mark.unit
def test_discover_youtube_subscribers_supports_nested_tags(tmp_path: Path) -> None:
    root = tmp_path / ".teleclaude"
    person_dir = root / "people" / "bob"
    person_dir.mkdir(parents=True)
    (person_dir / "teleclaude.yml").write_text(
        "subscriptions:\n  - type: youtube\n    source: youtube.csv\ninterests:\n  tags:\n    - ml\n    - infra\n",
        encoding="utf-8",
    )

    subscribers = discover_youtube_subscribers(root)
    assert len(subscribers) == 1
    assert subscribers[0].scope == "person"
    assert subscribers[0].name == "bob"
    assert subscribers[0].tags == ["ml", "infra"]

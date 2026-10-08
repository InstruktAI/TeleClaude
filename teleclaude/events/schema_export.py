"""JSON Schema export utility for the platform event model.

Allows external mesh participants and tooling to validate events without
importing Python code: the received-event shape every consumer reads, and the
declaration of every event type the catalog generates. Run directly to write the
document to disk:

    python -m teleclaude.events.schema_export [output_path]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

from teleclaude.core.models import JsonDict
from teleclaude.events.catalog import build_default_catalog
from teleclaude.events.envelope import ReceivedEvent

_DOCUMENT_TITLE = "Platform Event Model"
_RECEIVED_EVENT_KEY = "received_event"
_EVENT_TYPES_KEY = "event_types"
_DEFAULT_OUTPUT = "event-schema.json"


def export_events_markdown() -> str:
    """Return the event model JSON Schema wrapped in markdown for inspector prompts.

    Pure function — no I/O, no daemon. Safe for CI usage.
    """
    lines = [
        f"# {_DOCUMENT_TITLE} — Event Schema\n",
        "```json",
        json.dumps(export_json_schema(), indent=2),
        "```\n",
    ]
    return "\n".join(lines)


def export_json_schema() -> JsonDict:
    """Return the JSON Schema document for the received event and the declared event types."""
    declarations = [declaration.model_dump(mode="json") for declaration in build_default_catalog().list_all()]
    return cast(
        JsonDict,
        {
            "title": _DOCUMENT_TITLE,
            _RECEIVED_EVENT_KEY: ReceivedEvent.model_json_schema(),
            _EVENT_TYPES_KEY: declarations,
        },
    )


def export_json_schema_file(path: Path) -> None:
    """Write the event model JSON Schema to *path*."""
    path.write_text(json.dumps(export_json_schema(), indent=2))


if __name__ == "__main__":
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(_DEFAULT_OUTPUT)
    export_json_schema_file(output_path)
    print(f"Schema written to {output_path}")

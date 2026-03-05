"""JSON Schema export utility for EventEnvelope.

Allows external mesh participants and tooling to validate envelopes without
importing Python code. Run directly to write the schema to disk:

    python -m teleclaude_events.schema_export [output_path]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from teleclaude_events.envelope import EventEnvelope


def export_json_schema() -> dict[str, Any]:
    """Return the JSON Schema document for EventEnvelope."""
    return EventEnvelope.model_json_schema()


def export_json_schema_file(path: Path) -> None:
    """Write the EventEnvelope JSON Schema to *path*."""
    schema = export_json_schema()
    path.write_text(json.dumps(schema, indent=2))


if __name__ == "__main__":
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("envelope-schema.json")
    export_json_schema_file(output_path)
    print(f"Schema written to {output_path}")

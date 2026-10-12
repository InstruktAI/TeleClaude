---
description: Structured assessment returned by the selected release inspector, including explicit assessment completeness.
visibility: internal
---

# Release Report Schema — Spec

## What it is

The shared structured assessment returned by whichever provider completes release
inspection. This schema describes the inspector's judgment; execution failures
and provider availability are recorded by the invoking workflow separately.

Automatically assessed publication consumes a valid, complete report under
`local/projects/teleclaude/spec/feature/release/publication`. Its explicit-version
path records the supplied decision independently and does not invoke this
inspector contract.

## Canonical fields

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
  "required": ["classification", "rationale", "contract_changes", "release_notes", "assessment_complete"],
  "properties": {
    "classification": {
      "type": "string",
      "enum": ["patch", "minor", "none"],
      "description": "The semver classification of the changes."
    },
    "rationale": {
      "type": "string",
      "description": "Detailed reasoning for the classification."
    },
    "contract_changes": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["surface", "item", "change_type", "details"],
        "properties": {
          "surface": {
            "type": "string",
            "enum": ["cli", "events", "config"],
            "description": "Which public surface was affected."
          },
          "item": {
            "type": "string",
            "description": "The name of the affected command, tool, event, or key."
          },
          "change_type": {
            "type": "string",
            "enum": ["added", "modified", "removed"],
            "description": "Nature of the change."
          },
          "details": {
            "type": "string",
            "description": "Brief description of the change."
          }
        }
      }
    },
    "release_notes": {
      "type": "string",
      "description": "Draft release notes for human and AI consumption."
    },
    "assessment_complete": {
      "type": "boolean",
      "description": "Whether the inspector completed the version and breaking/upgrade assessment for the supplied change interval."
    }
  }
}
```

### Consumption

Validation checks the report's declared structure. Meaning and classification
belong to the inspector (`general/principle/intelligence-boundaries`). An
incomplete assessment explains its gap in the rationale and supplies no
publication authority. A successful fallback report remains associated with the
prior provider's failure evidence; the report does not replace that evidence.

Completeness follows the required version and breaking/upgrade judgment defined
by the release-inspector prompt. Truthful summary highlights may be selective;
their exhaustiveness does not independently determine this flag. Unresolved
decision-relevant implications or actual evidence/execution limits require false.

The report's release-notes text is the automatic release summary. The complete
linked commit list is generated independently by the shared release-notes path.
Explicit-version releases produce that deterministic list without an AI summary.

## See Also

- docs/local/spec/release-inspector-prompt.md

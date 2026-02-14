---
id: 'project/spec/release-report-schema'
type: 'spec'
scope: 'project'
description: 'Standardized JSON schema for AI release inspector reports.'
---

# Release Report Schema — Spec

## What it is

This specification defines the JSON schema that all AI Release Inspector lanes (Claude, Codex, Gemini) must produce. This uniformity allows the Consensus Arbiter to process reports deterministically.

## Canonical fields

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["classification", "rationale", "contract_changes", "release_notes"],
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
        "required": ["surface", "item", "change_type"],
        "properties": {
          "surface": {
            "type": "string",
            "enum": ["cli", "mcp", "events", "config"],
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
    }
  }
}
```

## Usage

AI agents are prompted to return ONLY valid JSON matching this schema using the `run_once` pattern or a directed `run_job` completion.

## See Also

- project/spec/release-inspector-prompt

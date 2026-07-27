---
description: 'Standardized JSON schema for AI release inspector reports.'
visibility: 'public'
---

# Release Report Schema — Spec

## What it is

Standardized JSON schema for AI Release Inspector reports. All AI Release Inspector lanes (Claude, Codex, Gemini) must produce this schema. This uniformity allows the Consensus Arbiter to process reports deterministically.

## Canonical fields

- `classification`: semver classification — `patch`, `minor`, or `none`.
- `rationale`: detailed reasoning for the classification.
- `contract_changes`: array of surface change objects (surface, item, change_type, details).
- `release_notes`: draft release notes for human and AI consumption.

### JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": false,
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
    }
  }
}
```

### Usage

AI agents are prompted to return ONLY valid JSON matching this schema using the `run_once` pattern or a directed `run_job` completion.

<!-- planned:restore-release-authorization-as-runtime-assertion -->

### Arbiter decision contract

The Consensus Arbiter consumes lane reports and emits `arbiter-decision.json` — the authoritative release decision. Two entry points produce it: the consolidator's own CLI, and the lane runner, which imports the consensus resolver directly. Both emit through that one resolver, so the guarantees below hold for every release run.

Fields:

- `release_authorized`: whether a release is authorized.
- `quorum_met`: whether enough valid lane reports were present.
- `target_version`: the semver bump — `patch`, `minor`, or `none`.
- `authoritative_rationale`: the reasoning behind the decision.
- `lane_summary`: per-lane classification, or `null` for a lane that produced no valid report.
- `evidence`: the lane report filenames backing the decision.

#### Authorization invariants

Every decision satisfies all of the following:

- An authorized decision carries a `target_version` of `patch` or `minor`. A release is never authorized at `none`.
- An unauthorized decision carries a `target_version` of `none`.
- A decision that did not meet quorum is never authorized.
- `target_version` is one of `patch`, `minor`, or `none`.
- Every lane named in `evidence` carries a non-null `lane_summary` classification.

The resolver checks these invariants against the decision it just built, before that decision reaches either caller. A violation aborts the release run: the arbiter reports the breached invariant and the offending decision on stderr and exits non-zero, and no `arbiter-decision.json` is written.

No step downstream of the arbiter re-checks the pairing of `release_authorized` and `target_version`.

<!-- /planned:restore-release-authorization-as-runtime-assertion -->

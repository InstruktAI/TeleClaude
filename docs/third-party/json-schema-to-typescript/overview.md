---
description: Evaluation of json-schema-to-typescript npm tool against Pydantic v2
  schema patterns. Concluded not used — pure Python generator chosen instead.
id: third-party/json-schema-to-typescript/overview
scope: project
type: third-party
---

# json-schema-to-typescript — Overview

## What it is

`json-schema-to-typescript` is an npm package (`npm install -g json-schema-to-typescript` / `npx json-schema-to-typescript`) that converts JSON Schema documents into TypeScript type definitions. Version 15.x is the current stable release.

Key capabilities:

- Accepts JSON Schema Draft 4, 6, and 7.
- Handles `$ref` and `$defs` for forward references and shared definitions.
- Supports `anyOf`, `oneOf`, `allOf` composition.
- CLI usage: `json2ts --input schema.json --output types.ts`
- Programmatic API: `import { compile } from "json-schema-to-typescript"`
- Produces TypeScript interfaces and type aliases.
- Configurable `additionalProperties`, `bannerComment`, `style`.

## Canonical fields

Pydantic v2's `model_json_schema()` produces JSON Schema Draft 2020-12 output with specific patterns that interact poorly with `json-schema-to-typescript`:

**Nullable fields via `anyOf`:** Pydantic v2 encodes `str | None` as `{ "anyOf": [{ "type": "string" }, { "type": "null" }] }`. The tool renders this as `string | null` but does **not** set the property as optional (`?:`). Pydantic's semantic of "optional with default None" is lost.

**`$defs` cross-model references:** Each call to `model_json_schema()` produces an independent document with its own `$defs`. A single TypeScript file covering all models requires merging schemas into one root document — a custom step not provided by the tool.

**Name transformation:** The project requires renaming TypeScript output (e.g., `SessionDTO` → `SessionInfo`). The tool does not support name transformation hooks. Post-processing via text replacement is fragile and breaks when field types reference the renamed models.

**Inheritance structure:** Pydantic v2 flattens multi-inheritance into a single `model_fields` dict. The JSON Schema output for `SessionDTO` (inheriting from `SessionDTOTimestampFields` and `SessionDTOIdentityFields`) contains all fields at the top level. The tool cannot reconstruct TypeScript `extends` relationships from this flat schema.

## Known caveats

**Not used in this project.** After evaluating these patterns against the project's requirements (R11), the decision is to implement a pure Python generator that walks `model_fields` directly using Python's type annotation introspection (`typing.get_type_hints`, `model_fields`, `__mro__`).

Reasons for choosing pure Python:

1. Full control over nullable-field optionality (`?:` vs required `string | null`).
2. No schema-merging step — introspection operates directly on model classes.
3. Name transformation and naming convention enforcement built in natively.
4. Inheritance detection via `cls.__mro__` enables correct `extends` emission.
5. Eliminates Node.js runtime dependency from the Python build pipeline.
6. Follows the existing pattern in `teleclaude/events/schema_export.py`.

This document records the R11 evaluation as required by the Definition of Ready research gate.

## Sources

- https://github.com/bcherny/json-schema-to-typescript
- https://www.npmjs.com/package/json-schema-to-typescript

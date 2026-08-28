---
description: How YAML Language Server associates a YAML file with a JSON Schema — the inline modeline, how relative references resolve, and which association mechanisms are portable across checkouts.
---

# YAML Language Server — Overview

## What it is

YAML Language Server is the language-server implementation behind YAML editing
support in VS Code and other LSP clients. Among other things it validates a YAML
document against a JSON Schema and offers completion from that schema.

It selects a schema for a document through several mechanisms, in decreasing
locality:

- **An inline schema modeline** — a comment on the document's first line of the
  form `# yaml-language-server: $schema=<uri>`. It applies to the file that
  carries it and overrides client configuration for that file.
- **Client configuration** — a `yaml.schemas` mapping from schema URI to file
  glob, held in editor settings.
- **Schema store association** — matching a well-known filename against a public
  catalogue.

## Canonical fields

- The modeline value is a URI. A relative value resolves **against the location
  of the YAML file that carries it**, not against the workspace root or the
  editor's working directory. A file and the schema it names therefore travel
  together when both are inside the same tree.
- Absolute `file://` values and `http(s)://` values are both accepted. An
  absolute local path resolves only on a machine where that path exists; an
  `http(s)` value requires the client to reach the network and the schema to be
  served without authentication.
- The modeline is read by the editor only. It has no effect on any other
  consumer of the document, and a document with no modeline, an unresolvable
  reference, or a malformed one is still ordinary YAML to every non-editor
  reader.
- Client configuration is user- or workspace-scoped. It is not carried by the
  document and does not travel with a repository unless committed as workspace
  settings.

## Known caveats

- A relative modeline is the only association mechanism that is both portable
  across checkouts and free of a network dependency; it requires the schema to
  exist in the same tree as the file.
- A modeline naming a machine-local absolute path becomes wrong on every other
  checkout of a tracked file, and reveals that machine's directory layout to
  anyone reading the file.
- Schema-store association depends on a filename being well known upstream and
  is unavailable to a private or project-specific filename.

## Sources

- https://github.com/redhat-developer/yaml-language-server — upstream repository and README, which document the `# yaml-language-server: $schema=` modeline and the `yaml.schemas` setting.

---
description: How YAML Language Server associates a YAML file with a JSON Schema — every documented association mechanism, how relative references resolve, and which mechanisms are portable across checkouts.
---

# YAML Language Server — Overview

## What it is

YAML Language Server is the language-server implementation behind YAML editing
support in VS Code and other LSP clients. Among other things it validates a YAML
document against a JSON Schema and offers completion from that schema.

Upstream documents the schema-selection surfaces below, in decreasing
locality, plus one suppression control that is not itself an association.

**Association carried by the document itself:**

- **Modeline comment** — `# yaml-language-server: $schema=<uri>` as a comment.
  Applies to the file that carries it.
- **IntelliJ-compatible modeline** — `# $schema: <uri>`, also a comment, with
  identical resolution behavior.
- **Inline `$schema` property** — a top-level `$schema` key in the document
  body. Unlike the two modelines this is document _data_, not a comment, so it
  is visible to every other reader of the file and to any schema that rejects
  unknown keys.

**Association carried by the client:**

- **`yaml.schemas` setting** — maps schema URIs to file globs. Accepts remote
  URLs, local paths, relative paths, and the reserved `kubernetes` keyword.

**Association carried by the protocol or upstream catalogue:**

- **`json/schemaAssociations` notification** — the client sends
  schema-to-pattern mappings, replacing previous associations.
- **Custom schema provider** — the client registers via
  `yaml/registerCustomSchemaRequest`; the server then requests schemas through
  `custom/schema/request` and their content through `custom/schema/content`.
- **SchemaStore catalogue** — enabled by default; associates schemas with
  common YAML patterns from the public catalogue.
- **Kubernetes CRD store** — validates Kubernetes custom resources against
  remote CRD schemas when enabled.

**Suppression, not association:**

- **`yaml.disableSchemaDetection`** — globs that prevent automatic detection for
  matching files. It selects no schema; it withholds one.

## Canonical fields

- A relative reference in **either modeline form and in the inline `$schema`
  property** resolves against the location of the YAML file that carries it, not
  against the workspace root and not against the editor's working directory. A
  file and the schema it names therefore travel together when both are inside
  the same tree.
- Absolute `file://` values and `http(s)://` values are both accepted. An
  absolute local path resolves only on a machine where that path exists; an
  `http(s)` value requires the client to reach the network and the schema to be
  served without authentication.
- A document-carried association is read by the editor only. It has no effect on
  any other consumer of the document, and a document with no association, an
  unresolvable reference, or a malformed one is still ordinary YAML to every
  non-editor reader. The inline `$schema` property is the exception in one
  direction: being a real key, it is visible to every parser of the document.
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
- SchemaStore association depends on a filename being well known upstream and is
  unavailable to a private or project-specific filename.
- **Documented gaps.** Behavior verified here covers the association mechanisms
  and their path resolution only. Validation semantics, completion, hover,
  formatting, custom tag handling, and the multi-document (`---`) association
  rules are not covered. The exact precedence order when several mechanisms
  match one document is stated by upstream only as a locality ordering and has
  not been verified here against implementation.

## Sources

- https://github.com/redhat-developer/yaml-language-server#associating-schemas — upstream README, "Associating schemas".
- https://raw.githubusercontent.com/redhat-developer/yaml-language-server/main/README.md — full upstream README as fetched.

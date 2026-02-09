# Code Context Annotations

## Vision

Documentation quality is a function of distance from work context. When docs live in separate files, they rot — agents and humans modify code without touching the distant docs. When docs live _inside_ the code as docstring annotations, they survive because they're literally in the diff. The cost of maintaining them is near zero: the agent already has full context of the module it just changed.

This creates a foundation for something larger. Once you have a critical mass of granular, correct, code-level documentation that's continuously maintained by proximity:

1. **Self-documenting codebase** — Annotations flow through the scraper into the same `teleclaude__get_context` pipeline agents already use. No new tools to learn, no separate docs to maintain.

2. **Structured code discovery** — Remote consumers (agents without codebase access) can query `get_context(areas=["code-ref"])` and get accurate, granular answers about what the project does, how it's structured, and what each component is responsible for.

3. **Data lake for self-correction** — The annotation corpus becomes a queryable model of the codebase's self-understanding. Inconsistencies between what annotations claim and what code does become visible signals. This feeds directly into Phase 2 (the consistency auditor), creating a feedback loop where the system improves itself.

The proximity hypothesis is the enabler. Everything else follows from agents keeping annotations current because it's trivially easy — they're already there, in the docstring, in the context of the work.

## Problem

Documentation about code architecture and API surfaces is maintained separately from the code. This creates drift — the docs describe one thing, the code does another. Agents using `teleclaude__get_context` can discover policies, designs, and procedures, but not the code itself. When agents need to understand a module, class, or function, they must grep and read files manually rather than using the structured discovery they already know.

## Intended Outcome

A self-documenting codebase where source code docstrings contain `@context` annotations that a scraper extracts into documentation snippets. These snippets integrate into the existing `teleclaude__get_context` pipeline, making code discoverable through the same two-phase mechanism agents already use. Agents maintain annotations naturally because the annotations live in the code they're already touching.

## Requirements

### 1. Annotation Syntax

- Annotations live inside Python docstrings (extensible to other languages later).
- A `@context:` tag marks a docstring as scraper-eligible and assigns a snippet ID.
- Additional structured metadata (summary, category) can be provided via tags.
- The annotation format should be natural to read and write for both humans and AI.

### 2. Scraper

- Walks configured source directories (Python files first).
- Parses AST to extract annotated docstrings + code signatures (class/function/module).
- Generates markdown documentation snippets with proper frontmatter.
- Places generated snippets in a dedicated output directory (e.g., `docs/project/code-ref/`).
- Idempotent: running the scraper twice with the same source produces the same output.
- Stale detection: removes generated snippets for annotations that no longer exist.

### 3. Taxonomy Integration

- Introduces a new snippet type (`code-ref`) for generated code documentation.
- The schema supports code-specific sections (signature, module path, related code).
- Generated snippets appear in `teleclaude__get_context` Phase 1 index like any other snippet.
- Phase 2 content retrieval works identically to hand-written snippets.

### 4. Sync Integration

- The scraper runs as part of `telec sync`, before index generation.
- Generated snippets participate in `index.yaml` construction.
- No manual intervention required — annotate code, sync, snippets appear.

### 5. Agent Prompting and Hygiene

This is the most important part. The annotations only have value if agents actually write and maintain them. The prompting must make annotation feel like a natural, low-friction addition to the work agents are already doing.

- A procedure snippet documents when and how to add `@context:` annotations.
- The procedure is positioned in the builder workflow: after writing or modifying a public class or key module, add/update the annotation.
- The annotation itself acts as a prompt: when an agent reads an annotated docstring, the `@context` tag primes it with the module's declared responsibility. This subtly reinforces the design intent.
- Agents can discover what code is annotated and what isn't via `get_context(areas=["code-ref"])`.

## Success Criteria

- An annotated Python class/function/module produces a discoverable snippet via `get_context`.
- Modifying the docstring and re-syncing updates the snippet.
- Removing the annotation and re-syncing removes the stale snippet.
- Existing hand-written snippets continue to work unchanged.
- Agents can find code reference docs through Phase 1 discovery.
- The annotation procedure is naturally adopted — agents add annotations when creating/modifying key code.

## Constraints

- Python first. Other languages are future work.
- Must not break the existing snippet pipeline.
- Generated snippets must be clearly distinguishable from hand-authored ones (directory convention + frontmatter marker).
- The annotation format must not conflict with existing docstring conventions (Sphinx, Google-style, etc.).

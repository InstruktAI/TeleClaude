---
description: A generated, always-current explorer over the doc corpus and the code Blueprint — contexts, feature specs, use cases, doctrine, packages and modules as one navigable graph with containment, a detail view, provenance, and a switchable pending overlay — openable from file:// and as a published Artifact.
delivered_by:
  - architecture-map-explorer
---

# Architecture Map — Spec

## Required reads

- @docs/project/spec/domain/context-map.md

## What it is

The architecture map is a single self-contained page a human opens to explore
the architecture as it currently is. It is derived — never drawn — from facts
that already exist: the doc index and snippet corpus, and the code Blueprint
with its freshness manifest. The page renders the bounded contexts, the feature
specs and their use cases inside each context, the global and project doctrine
(principles, concepts, policies, procedures, designs, specs, ADRs) with their
cross-references, required reads and see-also links, and the code structure at
package and module level with its dependencies, as one navigable graph with
containment. A detail view shows the selected snippet's rendered text and its
embedded diagrams, or the selected module's path, dependents, dependencies, and
the Blueprint's own confidence and freshness for it.

Every element states where it came from. The page states which repository
revision, doc index, and Blueprint it was derived from, taken as one consistent
snapshot. Current truth is what renders by default; pending doc state
(undelivered snippets, planned blocks, companions) is a visibly separate overlay
the reader switches on.

The generator emits facts and provenance only. It judges, scores, classifies,
and narrates nothing; judgment stays with the reader.

The map is presentation: rendering policy over facts that the documentation
context and the Blueprint publish. It owns no published facts and never
regenerates the Blueprint. Generation is project-scoped and off by default
elsewhere; in a project that enables it, the page regenerates without an agent
asking whenever that project's doc index or Blueprint regenerates. The current
generation and a bounded set of recent generations live at a stable, documented
location outside the doc corpus, so the page is openable from file:// and can be
published as a Claude Code Artifact from any agent session.

## Canonical fields

### Use cases

#### UC-AMAP-1: The page opens from file:// with no network

```gherkin
Given a human has a current generation of the architecture map on local disk
And the machine has no network access
When the human opens the page from file://
Then the graph renders with its contexts, doctrine, and code structure navigable
And every embedded diagram in a selected snippet renders inside the detail view
```

#### UC-AMAP-2: The published Artifact shows the same graph as file://

```gherkin
Given a current generation of the architecture map
When an agent session publishes that page as a Claude Code Artifact
And a human opens the Artifact
Then the human sees the same graph, detail view, and provenance as the file:// page of the same generation
```

#### UC-AMAP-3: An over-budget generation fails loudly

```gherkin
Given a generation whose rendered page would exceed the Artifact size limit
When the generator runs
Then an agent inspecting the generation's recorded outcome finds it failed, with the overrun reported as the failure
And an agent inspecting the generation location finds no page that silently omits content to fit
```

#### UC-AMAP-4: The graph nests contexts, feature specs, use cases, packages, and modules

```gherkin
Given the page is open
When a human navigates the contract view
Then each bounded context contains its feature specs
And each feature spec contains its use cases
When the human navigates the code view
Then each package contains its modules
```

#### UC-AMAP-5: Every element and edge states its source

```gherkin
Given the page is open
When a human inspects any node or any edge
Then the element states which source it was derived from and where in that source
And a cross-reference, required-read, see-also, or module-dependency edge states its confidence
```

#### UC-AMAP-6: A context or feature directory without a matching anchor is shown as such

```gherkin
Given a bounded context declared in the context map has no feature directory or no domain anchor
Or a feature directory exists with no declared context behind it
When a human navigates the contract view
Then that context or directory is shown with its missing counterpart stated as missing
And nothing is inferred to fill the gap
```

#### UC-AMAP-7: Selecting a snippet renders its text and its diagrams

```gherkin
Given the page is open on either host
When a human selects a snippet node
Then the detail view renders the snippet's current text
And each mermaid diagram embedded in that snippet renders as a diagram
```

#### UC-AMAP-8: Selecting a module shows its Blueprint facts

```gherkin
Given the page is open
When a human selects a module node
Then the detail view shows the module's path, its dependents, its dependencies
And the Blueprint's own confidence for those edges and the Blueprint's freshness
```

#### UC-AMAP-9: An absent dependency reads as unknown and blind spots stay visible

```gherkin
Given the code view is open
When a human inspects a module for which the Blueprint reports no dependency edge
Then the absence reads as unknown rather than as no dependents
And the Blueprint's declared blind spots are visible on the code view
```

#### UC-AMAP-10: A stale Blueprint is shown as stale

```gherkin
Given the Blueprint the page was derived from is not fresh against the repository revision the page states
When a human opens the page
Then the page states that the Blueprint is stale and names the baseline it was built from
And the code view remains navigable
```

#### UC-AMAP-11: The full Blueprint is never rendered at once

```gherkin
Given the page is open on the code view
When a human has not expanded any module
Then only packages and modules are drawn
When the human expands a module
Then that module's symbols appear, bounded to the expanded module
```

#### UC-AMAP-12: The page states one consistent snapshot

```gherkin
Given the page is open
When a human reads the provenance
Then the page states the repository revision, the doc-index digest, the Blueprint baseline, and the generation time it was derived from
And all four describe one snapshot taken together
```

#### UC-AMAP-13: A mixed snapshot aborts generation

```gherkin
Given the doc index or the Blueprint changes while a generation is reading its sources
When the generator detects that the sources it read do not describe one snapshot
Then an agent inspecting the generation's recorded outcome finds it failed, with the inconsistency reported as the failure
And an agent inspecting the generation location finds the previously current generation still current
```

#### UC-AMAP-14: Recent generations remain openable from file://

```gherkin
Given several generations have been produced on this machine
When a human opens an earlier generation from file://
Then that generation renders with the provenance it was derived from
And the current generation is distinguishable from earlier ones
```

#### UC-AMAP-15: Pending doc state appears only as an overlay the reader switches on

```gherkin
Given the corpus carries undelivered snippets, planned blocks, or companions
When a human opens the page
Then the default view renders current truth only
When the human switches the pending overlay on
Then pending elements appear visibly distinct from current ones
And the current view is not altered by them
```

#### UC-AMAP-16: The page regenerates when the doc index regenerates

```gherkin
Given a project that has enabled the architecture map
When the project's doc index is rebuilt
Then an agent inspecting the generation location finds a new generation produced without any agent asking for it
And an agent reading that generation's provenance finds it names the rebuilt index
```

#### UC-AMAP-17: The page regenerates when the Blueprint regenerates, and never fails the Blueprint

```gherkin
Given a project that has enabled the architecture map
When the project's Blueprint is regenerated
Then an agent inspecting the generation location finds a new generation produced without any agent asking for it
And an agent reading the Blueprint's freshness manifest after a failed page generation finds the Blueprint refresh recorded as successful
```

#### UC-AMAP-18: Generation is project-scoped and off by default

```gherkin
Given a project that has not enabled the architecture map
When that project's doc index or Blueprint regenerates
Then an agent inspecting that project finds no architecture map generated for it
```

#### UC-AMAP-19: The page renders in both color themes on both hosts

```gherkin
Given the page is open from file:// or as an Artifact
When the viewer's color theme is light
Then the graph, detail view, and provenance are legible in light colors
When the viewer's color theme is dark
Then the graph, detail view, and provenance are legible in dark colors
```

### Cross-context references

- **context** — publishes the doc index and the snippet corpus the map is
  derived from, and owns the parsers that extract use cases, required reads,
  see-also links, and pending markers. The map reads those published facts and
  restates none of their rules.
- **Blueprint** (code intelligence substrate) — publishes the code graph, its
  edge confidence, its declared blind spots, and its freshness manifest. The map
  reads and displays them verbatim and never regenerates the Blueprint.

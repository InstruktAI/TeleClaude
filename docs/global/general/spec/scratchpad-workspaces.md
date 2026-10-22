---
description: "Route regular working material to the agent's own environment, shared exploratory material to indexed project scratchpads, and required workflow deliverables to their canonical artifact store."
---

# Scratchpad Workspaces — Spec

## What it is

A scratchpad workspace is a disposable, project-local directory for working
material shared in active collaboration or a concrete handoff. It gives the
participants a predictable place to inspect or resume that material while it
remains non-authoritative (`general/principle/attunement`).

## Canonical fields

- **Exclusive use, assessed per write.** A project scratchpad holds only
  identified material a human or another session needs as input to active
  collaboration or a concrete handoff. Any other use is forbidden. This boundary
  applies to every write, including updates in an existing shared workspace.
  Personal continuity, including preservation against context loss, does not
  establish a shared-input need. Regular planning, reasoning, notes, experiments
  and disposable probes stay in the agent's own environment, using its native
  planning and temporary-file facilities. Task length, complexity, human
  presence, or having a reviewer alone does not establish that need. For an
  implementation review, the shared input can be the commit, governing contract
  and necessary evidence; the agent's working notes remain local.
- **Required artifacts keep their owner.** Plans, diagnoses, review findings
  and other deliverables required by a workflow use that workflow's canonical
  artifact store, including while they are drafts. A shared scratchpad holds
  exploratory material; it is not a second copy of a required artifact.
- **Curate knowledge of the subject.** Shared material holds the evidence,
  findings, designs, alternatives, material decisions and unresolved questions
  another reader needs to understand or continue the work
  (`general/principle/intent-first-documentation`). Session coordination and
  execution bookkeeping stay in their session or workflow records. When an
  execution event changes the research or design, retain its substantive
  consequence and evidence, rather than a narrative of the agent's actions.
- Shared scratchpad workspaces live under `scratchpad/` at the root of the project's
  canonical checkout, which the adopting project excludes from version control.
- Harness-provided planning and temporary directories serve the agent's local
  work. When particular material becomes shared input, only that material is
  published to the shared workspace or the required artifact store; the local
  working directory stays local.
- Each activity owns one directory named
  `scratchpad/YYYYMMDD-HHMMSS-<topic>/`, using the host's local time and a short
  kebab-case topic.
- Every activity directory carries an `index.md` whose content
  `general/procedure/scratchpad-workspace` defines. The procedure using the
  workspace names the other files. Related source, notes, checkpoints, and
  temporary renders stay together in that directory.
- Scratchpad content is disposable and non-authoritative. Durable docs,
  implementation, and workflow artifacts never cite it as a source of current
  truth.
- Secrets, credentials, personal data, and irreplaceable source material never
  enter a scratchpad.
- Promotion is selective: the owning procedure distills the agreed material
  into its durable authority. It never copies the workspace wholesale.
- Cleanup may remove any scratchpad whose index shows the activity finished
  and its useful content promoted. Retention is convenience, not lifecycle state.

## Allowed values

- Directory timestamp: `YYYYMMDD-HHMMSS`, all fourteen digits.
- Topic: lowercase kebab-case naming the activity, not an agent or tool.
- Contents: any files required by the owning procedure, provided they obey the
  non-authoritative and secret-free contract above.

## Known caveats

- A human agreement does not itself make scratchpad content current truth.
  Documentation and delivery rules still determine where and when the agreed
  result becomes authoritative.

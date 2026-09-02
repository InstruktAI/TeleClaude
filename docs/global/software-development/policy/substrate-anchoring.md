---
description: Before new construction, identify the existing module whose contract covers the work or record grounded absence; the defect is the undeclared parallel, built in ignorance of what exists.
---

# Substrate Anchoring — Policy

## Rules

- **Before new construction, identify the existing module whose actual contract
  covers the work, or record that grounded discovery found none.** Extend an
  existing module when owner, invariant, and reason to change align; otherwise
  declare the justified divergence. A new, replacement, migration, or
  anti-corruption implementation is legitimate when those differ; where an
  existing module was found, it declares which one it stands beside and why,
  and where none was found, the recorded discovery result and its rationale are
  the declaration.
- **The defect is the undeclared parallel.** A second implementation of a
  capability that already exists, built without naming the first, is a defect
  even when its code is good. Declared divergence is design; undeclared
  divergence is ignorance of the substrate.
- **Anchoring is produced by the change description or RFC and checked by
  review.** It is never the input author's burden: a human states what they want
  without knowing how it fits, and the preparing agent grounds the work in what
  exists. Review verifies the anchor against the codebase, not against the
  author's claim.
- **Anchoring is verified, not asserted.** An anchor either names a module the
  agent has read with its actual contract, or records the discovery performed
  and why no existing contract covers the work. Memory, plausible filenames, or
  an unsupported "none found" are not anchors.

## Rationale

Agents build what they do not know exists. Dropped into a codebase with a task,
the cheapest path is a fresh implementation beside the old one, and nothing
downstream catches it: the new code is correct, tested against itself, and
reviewed on its own merits. The duplicate surfaces months later as two owners
of one behavior diverging. Naming the existing module first is the only moment
the parallel is cheap to prevent, and it is only enforceable when a specific
artifact carries the declaration and a specific gate checks it.

Placing the burden on the preparing agent rather than the input author keeps the
human contract intact: the human owns what, the agent owns how, and how begins
with what already exists.

## Scope

- All agents authoring a change description, RFC, architecture artifact, or
  implementation plan, in every project on the platform.

## Enforcement

- A change description or RFC without an anchoring declaration is incomplete and
  is returned before review proceeds.
- A reviewer who finds an existing module whose contract covers the work, where
  the artifact declares none, files a **Critical** finding: the work is an
  undeclared parallel.
- A declared divergence whose stated reason does not hold — same owner, same
  invariant, same reason to change — is **Important**: the extension path was
  available and not taken.

## Exceptions

- None.

## See Also

- ~/.teleclaude/docs/software-development/principle/module-depth.md — the one-sentence contract an anchor names.
- ~/.teleclaude/docs/software-development/principle/architectural-defaults.md — the ownership invariants that decide extend versus stand beside.
- ~/.teleclaude/docs/general/policy/human-contract.md — why the input author carries no anchoring burden.

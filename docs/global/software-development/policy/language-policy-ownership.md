---
description: Keeps language-neutral software-development contracts separate from language-owned syntax, libraries, tooling, test conventions, and enforcement mechanics.
---

# Language Policy Ownership — Policy

## Required reads

@~/.teleclaude/docs/software-development/policy/domain-ownership.md

## Rules

### Generic contracts own outcomes

- Generic software-development snippets own principles, outcomes, and invariants that remain true across implementation languages.
- A generic contract may require immutability, explicit state, structured observability, boundary validation, or scenario-bound verification. It does not select the language construct, library, runner, marker, filename, compiler feature, checker, or command that realizes that outcome.
- Generic examples use language-neutral notation. A concrete language example belongs in the applicable language policy when it teaches or directs a mechanism.

### Language policies own realization

- Each language policy owns its syntax, type constructs, standard-library choices, third-party libraries, package and task runners, file naming, test markers, compiler capabilities, checker configuration, and exact enforcement commands.
- Language-specific rules are stated once by their language owner. Generic policies and cross-language procedures reference that owner instead of copying its instructions.
- A language policy may depend on a generic contract and explain how that language realizes it. That dependency never transfers ownership of the language mechanics upward.
- When a project needs a language-specific exception or convention that is not portable to other repositories, the project owns it in project scope.

### Coordinators route without absorbing ownership

- A cross-language coordinator may detect a language, name the policy that applies, and route work to that policy's commands or conventions.
- A coordinator may list supported languages or map manifest files to their owners when routing is its subject. It does not restate the owners' behavioral rules.
- If no language policy covers a language-specific decision, author the missing language owner or a project-scoped declaration before prescribing the mechanism. A generic fallback never silently becomes the owner.

### Examples are part of the contract surface

- An agent-executable example is directive text. Its syntax and named tooling determine ownership exactly as prose instructions do.
- A concrete example may remain in a generic snippet only when the language is incidental, the example is explicitly non-normative, and replacing it with another language would not change the instruction. Otherwise it moves to the language owner.

## Rationale

Generic snippets are loaded across repositories and languages. When they prescribe one language's mechanism, that mechanism is primed as a universal default and can be applied in the wrong owner location. Keeping the generic layer outcome-focused lets language policies evolve independently while preserving one authoritative home for every concrete rule.

Routing documents necessarily see more than one language, but visibility is not ownership. Their job is to select the right owner, not to become a second copy of every rule they route to.

## Scope

- All global software-development snippets and every project-scoped extension of them.
- All authored prose, examples, tables, command lines, and review instructions that direct implementation or verification behavior.

## Enforcement

- Authors and reviewers reject a language-specific directive in a generic snippet as wrong-owner placement and require the language owner to carry it.
- Review of a changed language file loads that language's applicable core, testing, and tooling policies. Findings cite the owning language policy rather than a copied generic instruction.
- Review of a cross-language coordinator verifies that it routes to owners without restating their mechanics.
- Ownership is judged semantically. Keyword scanners and prose graders do not decide whether language specificity is legitimate.

## Exceptions

- A generic snippet may name languages, manifests, or tools when comparison, support discovery, or routing is the snippet's subject and no behavioral rule is duplicated.
- Descriptive migration examples may name source and target languages when the language transition itself is the subject.

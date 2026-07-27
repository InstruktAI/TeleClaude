---
description: 'Every dependency edge must be recoverable by a parser without running the code. The generating property behind all code-shape rules: what makes a rule legitimate, where it is enforced, and why tooling dies without it.'
visibility: 'public'
---

# Static Legibility — Principle

## Principle

Code is statically legible when every dependency edge — import, call, constant
reference, filesystem path, dispatch target, event route, config key — is
recoverable by a parser without executing the program.

The principle generates and bounds all code-shape rules:

- A code-shape rule is legitimate if and only if a parser can decide it **and**
  it either makes an invisible edge visible or makes an illegal state
  unrepresentable. A rule that does neither is not a shape rule and is not
  authored as one.
- Decidability routes enforcement; it never ranks bindingness. A
  parser-decidable rule is enforced by automated checks. A rule requiring
  judgment — boundary placement, design coherence, whether an abstraction is
  right — is enforced by reviewer intelligence. Both are equally binding; the
  split is who enforces, never how much it counts.

Dynamic boundary crossings are the canonical violation: an event emitted under
a string name and consumed by a handler registered under the same string is an
edge that exists only at runtime. Statically it is two unrelated statements.
Every dynamic crossing — events, channels, dispatch tables, config-keyed
routing — goes through a declared, parseable registry or a symbol-referenced
helper, so the runtime edge is also a static edge.

## Rationale

- Shape rules accreted as enumerations never terminate: each new rule is
  re-litigated by every fresh session because nothing states why the family
  exists. A named generating property ends the enumeration — rules are derived
  from it, and a proposed rule that serves no edge and no unrepresentable
  state is rejected by the property itself.
- Structural tooling — blast-radius computation, dependency graphs, impact
  analysis — is exactly as good as the edges it can see. Inline literals,
  ad-hoc paths, and string-named dispatch are edges the parser cannot see;
  they are precisely where dependency graphs go blind and blast-radius
  reports become wrong.
- Testability and graphability are one property viewed from two sides. Code
  that receives its world through explicit seams both declares its edges (a
  parser can graph them) and accepts a different world (a harness can inject
  one). Code that reaches for ambient globals hides its edges from the parser
  and welds itself to one world.
- Agents follow whatever the environment makes cheapest, not prose. A
  decidable rule enforced by an organ outside the constrained author's reach
  holds unconditionally; the same rule stated as guidance erodes one
  defensible commit at a time.
- Reviewer intelligence is scarce. Every mechanical defect a parser could
  have rejected is attention not spent on the judgment questions only a
  reviewer can answer. Automating the decidable layer is what makes judgment
  affordable, not what replaces it.

## Implications

- Constants, paths, and other shared values are referenced by symbol through
  their owning module or helper — never restated as inline literals. The
  symbol reference is the visible edge.
- Nothing touches the world at import time. Everything the world provides —
  paths, environment, sockets, clocks, processes — enters through an
  explicitly injected root or seam. The same seam yields testability,
  multi-instance capability, and bounded blast radius for free.
- Every dynamic dispatch surface declares its edges: registries and typed
  helpers over bare string names, so emit and handle sites resolve to the
  same statically visible declaration.
- A proposed shape rule must name the edge it makes visible or the illegal
  state it makes unrepresentable. If it cannot, it is advice about style, not
  a shape rule, and is not enforced as one.
- Rules have a lifecycle with a terminal state: a shape defect a reviewer
  catches recurring graduates into an automated check. Review lanes are the
  discovery organ for rules; the automated lane is where rules retire and
  become permanent.
- Enforcement placement matters as much as the rule: a check the constrained
  author can edit in the same change is a wall that moves. Automated shape
  checks live in an organ outside the changed code's commit scope.
- The property is nearly free when present from the first line and
  rewrite-shaped when retrofitted. It binds new projects at onboarding and
  new code at authoring; it is not a mandate to sweep existing codebases.

## Tensions

- **Legibility vs. dynamism.** Declared registries and symbol-routed dispatch
  add ceremony that dynamic-language idioms avoid. The ceremony is the price
  of computable blast radius; pay it at boundaries, not in every private
  helper.
- **Decidability vs. bindingness.** Routing enforcement by decidability
  tempts the misreading that judgment rules are lesser. They are not — the
  most binding rules (boundary purity, design coherence) are the least
  decidable. Judgment of free-text and design belongs to intelligence, never
  to code that grades it.
- **Born-in vs. bolted-on.** Applying the property to a codebase nearing
  retirement spends rewrite-scale effort for a dividend that dies with it.
  The cut is the codebase's remaining lifespan, decided deliberately — never
  by the enthusiasm of the session that discovered the principle.
- **Automation appetite.** The impulse to automate a rule that needs judgment
  produces validators that grade prose — the warning sign named by
  intelligence-boundaries. Only parser-decidable rules automate; the residue
  stays with reviewers by design.

## See Also

- ~/.teleclaude/docs/software-development/principle/externalized-structural-context.md — the
  consumption side of the same property: work reasons from explicit
  structural context; static legibility is what makes that context
  computable.
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md — why the judgment half of
  enforcement is never delegated to grading code.

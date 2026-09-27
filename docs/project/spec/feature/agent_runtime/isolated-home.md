---
description: Managed agents receive a temporary clone of the TeleClaude home repository through platform automation, with the home path injected before execution and live operations kept on their published boundary.
visibility: internal
delivered_by: [agent-home-clone-provisioning]
---

# Isolated Agent Home — Spec

## What it is

Every managed agent session that uses TeleClaude receives an isolated,
temporary Git clone of the TeleClaude home repository. The platform creates
the clone and injects its location through `TELECLAUDE_HOME` before the agent
starts. Delegated processes that need a home use that provisioned clone. The
agent does not construct a home, select individual files to copy, set the
variable, or remove the clone.

The clone contains the home repository's complete tracked configuration at
launch, including the project registry and the global, person, and company tier
documents. It reflects tracked edits present in the source working tree at
launch. Files outside that repository's tracked set are not part of the clone.
Changes made under the clone leave the source home untouched. The cloned
registry remains readable with its real project entries; it alone grants no
permission for undelivered code to modify those live repositories.

An agent's installed TeleClaude commands that operate live sessions, todos, or
other live platform state still reach that state through their published
operation boundary. The isolated home is the configuration substrate for
undelivered code, not a substitute for the live platform's database or daemon.
The platform retires the clone when its owning execution ends.

## Canonical fields

### Use cases

#### UC-IAH1: An agent receives a complete isolated home automatically

```gherkin
Given a managed TeleClaude agent session starts
When the agent first needs TeleClaude home configuration
Then its environment already names a temporary clone of the TeleClaude home repository
And the clone contains the tracked project registry and tier documents
And the agent did not have to create or select that home
```

#### UC-IAH2: The clone reflects current tracked configuration

```gherkin
Given a tracked home configuration document has an uncommitted change before an isolated agent execution starts
When the agent reads that document through its assigned home
Then it reads the current tracked working-tree content
And the source document is unchanged
```

#### UC-IAH3: Checkout grading uses the supplied home

```gherkin
Given an agent works in a checkout whose code differs from the installed checkout
When the agent runs the quality gate for that checkout
Then the checkout's code is graded with the tracked home configuration available in its isolated home
And no quality step needs the agent to assemble a separate partial home
And the live home is unchanged
```

#### UC-IAH4: Live platform operations retain their live authority

```gherkin
Given an agent has an isolated home for undelivered project code
When it invokes an installed command to operate a live session or todo
Then that command acts on the live platform record it addresses
And the agent does not change its home environment to make the command work
```

#### UC-IAH5: The platform retires the clone

```gherkin
Given a managed agent execution has an isolated home clone
When that execution ends
Then the platform removes the clone
And the source home repository is unchanged
```

#### UC-IAH6: Registry reads do not authorize live project writes

```gherkin
Given an agent's isolated home clone contains the real project registry
When undelivered checkout code invokes an operation that would update registered projects
Then the operation cannot change any live repository named by that cloned registry
And the registry remains available for configuration reads
```

## Known caveats

- A Git clone carries the repository's tracked material. The live databases,
  credential stores, and other untracked runtime files remain under their
  separate owners and are not reconstructed by this contract.

## See Also

- docs/project/spec/feature/agent_runtime/checkout-code-selection.md — which
  checkout's code executes and how its quality rules are selected.
- docs/project/design/architecture/home-repository.md — the retained set that
  determines what the home repository records.

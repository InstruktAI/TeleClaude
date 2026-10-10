---
description: Preparation-view lifecycle actions target the project the cursor's row
  belongs to, and report the submitted operation's terminal outcome rather than its
  acceptance.
visibility: internal
---

# Preparation Lifecycle Actions — Spec

## What it is

The TUI Preparation view turns a keypress on a todo row into a lifecycle
operation against the daemon — prepare, start work, freeze, and the artifact
actions. The properties below make that operation trustworthy.

**The cursor's row names its own project.** A slug is unique only within a
project, so slug alone never identifies a todo across the fleet. The project a
lifecycle action targets is the one the cursor's row belongs to — the project
header the row sits under, falling back to the project the row itself carries.
No resolution consults a fleet-wide index keyed by slug, because such an index
cannot distinguish two projects that hold the same slug and would silently
substitute one for the other.

**The cursor's row names its own todo.** One slug can name several todos in a
project at once: a removed or delivered todo keeps its slug while it is
retained, and a live todo may hold the same slug. A row stands for its todo's
durable identity. Everything done from the row — a lifecycle or artifact
action, opening one of its files, expanding or collapsing it — addresses that
identity and never another todo that shares the slug.

**A row offers only what its todo's state allows.** A live todo's row keeps
every action. A removed todo and its files offer expanding and collapsing,
viewing a file read-only, and reactivating the todo; a delivered todo and its
files offer expanding and collapsing and viewing a file read-only. The workflow
holds the same rule for every action addressed to a todo's durable identity: it
refuses an action the todo's state does not allow and names the way forward
(`local/projects/teleclaude/spec/feature/workflow/todo-management`). A row whose todo changed
state after the view drew it therefore reports that refusal and acts on no
other todo.

**Submission is not an outcome.** A lifecycle operation is durable and
asynchronous: the response to the submission is an acceptance receipt, and the
outcome exists only once the operation reaches a terminal state. A refusal does
not announce itself as one — a runner that is not dispatched, whether the target
is removed, delivered, iceboxed, or dependency-blocked, or another holder owns
the claim, terminates the operation _successfully_ and carries the refusal in
the operation's result. So does every other lifecycle operation that declines
the work it was handed.

<!-- planned-change:quiet-technical-faults -->

The view therefore follows every operation it submits to its terminal state and
reports what it finds. Any terminal refusal or failure — a non-successful
terminal state, a reported error, or a successful termination whose result
records a refusal — reaches the operator at error severity carrying the outcome
the operation reported, never as a success message.
<!-- change:quiet-technical-faults -->

The view follows every operation it submits to its terminal state. A deliberately
published work refusal reaches the operator at error severity with its work
explanation, whether the operation declined successfully or ended in failure.
Technical faults and observation failures retain their diagnostics and recorded
outcomes under the work-feedback boundary
(`local/projects/teleclaude/spec/feature/presentation/work-feedback`).
<!-- /planned-change:quiet-technical-faults -->

**The view decides nothing about the lifecycle.** A keypress is a request to
the workflow, never a verdict. Whether a todo may be prepared or start work, and
which lane it enters, are answered by the workflow from the todo's own data; the
view submits the operation and reports that answer. Nothing the view renders is
read back as state, per `sdlc/principle/architecture-boundary-purity`.

## Canonical fields

### Use cases

<!-- planned-change:quiet-technical-faults -->

#### UC-PLA-1: Start-work targets the cursor's project and reports the operation's real outcome

```gherkin
Given two projects each hold a todo with the same slug
And the todo in the project the cursor is not under is soft-removed
And the cursor sits on the live todo under its own project header
When the operator starts work on the cursor's row
Then the lifecycle operation is submitted against the cursor's project
When any lifecycle operation the view submitted reaches a terminal state reporting a refusal or a failure
Then the operator is notified at error severity
And the notification carries the outcome the operation reported
```

<!-- change:quiet-technical-faults -->

#### UC-PLA-1: Start-work targets the cursor's project and reports its declared work refusal

```gherkin
Given a human operator at the TUI sees two projects with todos that share a slug
And the todo outside the cursor's project is soft-removed
And the cursor sits on the live todo under its own project header
When the operator starts work on the cursor's row
Then the lifecycle operation is submitted against the cursor's project
When an operation the view submitted terminates with a deliberately published work refusal
Then the operator is notified at error severity with that work explanation
```

<!-- /planned-change:quiet-technical-faults -->

#### UC-PLA-3: Opening a trashed todo's artifact shows that removed todo's own content, read-only

```gherkin
Given a soft-removed todo inside its retention window holds stored artifacts
And a live todo in the same project holds the same slug and an artifact of the same name with different content
And the operator has revealed the project's Trashed section and expanded the removed todo
When the operator opens one of the removed todo's artifacts from the Trashed section
Then the viewer shows the content stored for that removed todo's artifact
And the viewer is read-only, so nothing done in it changes either todo's artifacts
```

#### UC-PLA-4: A removed or delivered todo's rows offer only what the todo's state allows

```gherkin
Scenario Outline: A retained todo's rows offer only what its state allows
  Given a human operator at the TUI has revealed a project's <section> section
  And a <state> todo is shown there, expanded to its files
  When the operator puts the cursor on that todo's <row>
  Then the actions the view offers on that todo are exactly <offered>
  And pressing the key of any other action on that todo changes no todo

  Examples:
    | section   | state     | row      | offered                                         |
    | Trashed   | removed   | own row  | expanding or collapsing it, and reactivating it |
    | Trashed   | removed   | file row | collapsing it, and viewing that file read-only  |
    | Delivered | delivered | own row  | expanding or collapsing it                      |
    | Delivered | delivered | file row | collapsing it, and viewing that file read-only  |
```

#### UC-PLA-5: Expanding a todo expands only that todo

```gherkin
Given a project holds a live todo, a delivered todo, and a removed todo that share one slug
And a human operator at the TUI has revealed the project's Delivered and Trashed sections
When the operator expands one of those todos
Then that todo's row alone shows its files
And the other todos that share the slug stay collapsed
And after the view rebuilds or the TUI restarts, that todo alone is still expanded
```

#### UC-PLA-6: Opening an artifact from a row shows that row's own todo's content

```gherkin
Given a delivered todo and a live todo in one project share a slug
And each holds an artifact of the same name with different content
And a human operator at the TUI has revealed the project's Delivered section and expanded both todos
When the operator opens the artifact from the delivered todo's row
Then the viewer shows the content stored for the delivered todo's artifact
And the viewer is read-only, so nothing done in it changes either todo's artifacts
When the operator opens the artifact from the live todo's row
Then the viewer shows the live todo's content
And saving an edit there changes only the live todo's artifact
```

#### UC-PLA-7: An action from a row whose todo has since been removed is refused, never retargeted

```gherkin
Given a human operator at the TUI sees a live todo's row in the Preparation view
And after the view drew it, that todo was removed and a new live todo took its slug
When the operator starts an action on the todo from that row before the view refreshes
Then the action is refused and the new todo is left unchanged
And the operator is notified at error severity with a refusal that names the removed state and reactivation as the way forward
```

#### UC-PLA-8: A todo created where nothing names a project belongs to the project the TUI was started from

```gherkin
Given a human operator started the TUI from inside a project, or from a subdirectory or slug worktree of it
And nothing under the cursor in the Preparation view names a project, as when the view lists no rows
When the operator creates a new todo or bug
Then the new item is created in the project the TUI was started from
And no item is created in any other project
```

#### UC-PLA-9: Start-work on a todo that is not ready reports the workflow's refusal

```gherkin
Given a human operator at the TUI has the cursor on a live todo that has not reached prepared
When the operator starts work on it
Then the view submits the work operation without judging readiness itself
And the operator is notified at error severity with the refusal the workflow reported
```

#### UC-PLA-10: Creating a todo from the TUI asks for its kind

```gherkin
Given a human operator at the TUI starts creating a new todo
When the view asks for the new todo's slug
Then it also asks the operator to choose its kind: feature, change, bug, or task
And the created todo carries the chosen kind and enters that kind's lane
And the view creates no todo until a kind is chosen
```

## See Also

- docs/local/design/architecture/tui-state-layout.md — the Preparation view's
  interaction mapping and state model.

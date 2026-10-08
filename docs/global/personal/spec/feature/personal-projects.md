---
description: What a person experiences when they ask their own assistant to build
  something new — taken up as new-project work from the first turn, shaped as any
  new build is, placed in their own space without the question being asked, and left
  as a project of their own.
---

# Personal Projects — Spec

## What it is

A personal project is a project a person's own assistant starts for them when
they ask for something new to be built — a tool, an automation, a small app. The
assistant recognises the request, shapes the build with the platform's new-build
intake, creates the project in the person's own projects area, scaffolds it and
converges it. The result is an ordinary TeleClaude project in every respect, and
it belongs to the person.

The person's own projects area is where the assistant creates the project,
without asking. A company project the person asks for is created in that
company's projects area. A project outside every home is a platform project
that only a platform administrator creates.

The assistant's part ends when the project exists. Building it out is ordinary
project work in that project, and a change to a project that already exists is
not project creation.

## Canonical fields

### Use cases

#### UC-PPROJ1: A request to build something new is new-project work from the first turn

```gherkin
Given a person in a conversation with their own assistant
When the person asks for a tool, an automation, or a small app to be built for them
Then the assistant takes the request up as starting a new project in that same session
And the person neither named it as such nor pointed the assistant at any procedure
```

#### UC-PPROJ2: The person meets the platform's new-build shaping

```gherkin
Given a person has asked their assistant to build something new
When the assistant shapes the build with them
Then the questions the person is asked are the ones the platform's new-build intake asks of any new build
```

#### UC-PPROJ3: The project lands in the person's own space without the question being asked

```gherkin
Given a person has asked their assistant to build something new and named no destination
When the assistant creates the project
Then the project appears in that person's own projects area
And the person was never asked where it should go
```

#### UC-PPROJ4: The assistant leaves a registered project, not merely a folder

```gherkin
Given a person's assistant has created a project in that person's own projects area
When an agent lists the projects on the person's machine
Then the new project is listed under its own identity
And the person's workspace is not listed in its place
```

#### UC-PPROJ5: The person owns the project their assistant created in their space

```gherkin
Given a person's assistant has created a project in that person's own space, at the default spot or one the person named
When an agent resolves that project's owner
Then the owner is that person
```

#### UC-PPROJ6: A destination outside the person's home follows the platform's creation rules

```gherkin
Given a person who is not a platform administrator
And they tell their assistant to put a new build in a folder outside every home
When the assistant tries to create the project there
Then no project is created
And the person is told the destination is not one they can create projects in
```

#### UC-PPROJ7: A change to an existing project is not project creation

```gherkin
Given a person asks their assistant to change something in a project that already exists
When the assistant takes the request up
Then no new project is created
```

---
argument-hint: '[slug]'
description: Present demo artifacts as conversational walkthrough
---

# Demo

You are now the Demo Presenter.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/demo.md

## Purpose

Walk the user through a delivered feature demo one step at a time.

## Inputs

- Slug (optional): "$ARGUMENTS"

## Outputs

No slug:

```
Available demos: {list}

Which demo would you like to see?
```

With slug:

```
DEMO PRESENTED: {slug}
```

## Steps

- **No slug:** Run `telec todo demo` to list demos, ask which to present.
- **With slug:** Follow the demo procedure's presentation phase.

## Discipline

You are the demo presenter. Your failure mode is narrating from memory instead of
executing the demo artifact. Follow the documented demo steps exactly — run the
validation commands, show the actual output, and let the evidence speak. Do not
improvise, skip steps, or substitute your own narrative for the artifact's.

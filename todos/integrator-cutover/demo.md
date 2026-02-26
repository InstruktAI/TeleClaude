# Demo: integrator-cutover

## Validation

```bash
telec todo validate integrator-cutover
```

```bash
rg -n "integrator|canonical `main`|rollback|feature branches" todos/integrator-cutover/requirements.md
```

## Guided Presentation

1. Show exclusive authority requirements for canonical `main`.
2. Show cutover preconditions and rollback containment requirements.
3. Show acceptance tests that prove blocked vs allowed push paths.

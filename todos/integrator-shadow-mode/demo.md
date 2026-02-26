# Demo: integrator-shadow-mode

## Validation

```bash
telec todo validate integrator-shadow-mode
```

```bash
rg -n "shadow|lease|queue|no canonical `main`" todos/integrator-shadow-mode/requirements.md
```

## Guided Presentation

1. Walk through singleton lease and durable FIFO queue requirements.
2. Show shadow-mode constraints that prevent canonical `main` push.
3. Show planned tests for lease collision and restart recovery.

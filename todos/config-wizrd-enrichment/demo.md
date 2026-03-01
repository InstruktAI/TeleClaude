# Demo: config-wizrd-enrichment

## Validation

```bash
# Verify guidance coverage — all env vars have entries
python -c "
from teleclaude.cli.tui.config_components.guidance import get_guidance_for_env
from teleclaude.cli.config_handlers import get_all_env_vars
missing = []
for group, vars in get_all_env_vars().items():
    for v in vars:
        if not get_guidance_for_env(v.name):
            missing.append(v.name)
print('Missing guidance:', missing or 'None — all covered')
"
```

```bash
# Run tests
make test
```

## Guided Presentation

1. Open the config wizard: `telec config wizard`
2. Navigate to the **Adapters** tab — you see env vars listed with set/unset indicators.
3. Use arrow keys to select an env var (e.g., TELEGRAM_BOT_TOKEN). Observe: guidance expands inline below it showing numbered steps, a clickable URL, format example, and validation hint.
4. Move cursor to a different var. Observe: previous guidance collapses, new var's guidance expands.
5. Press **g** to enter guided mode. Observe: wizard walks through adapters sequentially; the first unset var auto-expands its guidance so the user knows exactly what to do.
6. Select an already-set var. Observe: guidance still shows for verification — users can confirm they used the right source.
7. Navigate to the **Environment** tab — same inline guidance behavior across all env vars.

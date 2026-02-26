# Demo: config-wizard-whatsapp-wiring

## Validation

```bash
# Verify WhatsApp env vars are registered in the adapter registry
python -c "from teleclaude.cli.config_handlers import get_adapter_env_vars; vars = get_adapter_env_vars('whatsapp'); assert len(vars) == 7, f'Expected 7, got {len(vars)}'; print('OK: 7 WhatsApp env vars registered')"
```

```bash
# Verify config validation includes WhatsApp vars
telec config validate 2>&1 | grep -i whatsapp
```

```bash
# Verify config.sample.yml has whatsapp section
grep -A5 'whatsapp:' config.sample.yml
```

```bash
# Verify teleclaude-config spec lists WhatsApp env vars
grep 'WHATSAPP' docs/project/spec/teleclaude-config.md
```

## Guided Presentation

### Step 1: Open the config wizard

Open the TUI and navigate to the Configuration tab, then the Adapters sub-tab, then the WhatsApp tab.

**Observe:** The WhatsApp tab now shows all 7 environment variables with set/not-set status indicators. Previously this tab was empty.

### Step 2: Browse env var guidance

Use arrow keys to navigate through each WhatsApp env var in the list.

**Observe:** The guidance panel at the bottom shows a description and format example for each variable. For `WHATSAPP_PHONE_NUMBER_ID`, you see the Meta Business dashboard steps.

### Step 3: Run config validation

```bash
telec config validate
```

**Observe:** WhatsApp env vars appear in the validation output alongside Telegram, Discord, and other adapter variables. Missing vars are flagged.

### Step 4: Check sample config

```bash
grep -A10 'whatsapp:' config.sample.yml
```

**Observe:** A complete `whatsapp:` section with all config keys and `${VAR}` interpolation for secrets, matching the Discord/Redis pattern.

**Why it matters:** The config wizard is the primary configuration interface. With this wiring complete, users no longer need to manually edit YAML to set up WhatsApp — the wizard provides the same guided experience as Telegram and Discord.

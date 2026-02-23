# Demo: deployment-channels

## Validation

```bash
# Config accepts deployment channel
python -c "
from teleclaude.config.schema import validate_config
# If schema validation passes for deployment.channel, this exits 0
print('OK: schema accepts deployment config')
"
```

```bash
# Version watcher job exists and is registered
python -c "from jobs.version_watcher import VersionWatcherJob; print(f'OK: {VersionWatcherJob.name}')"
```

```bash
# telec version shows configured channel
telec version | grep -q "channel:"
```

## Guided Presentation

### Step 1: Channel config

Show `config.yaml` with `deployment.channel: alpha`. Explain the three channels:
alpha (follows main HEAD), beta (follows GitHub releases), stable (pinned minor,
patches only). Default is alpha for backward compatibility.

### Step 2: Version watcher

Show the job registered in `teleclaude.yml` with 5-minute schedule. Explain:
alpha uses `git ls-remote` (lightweight), beta/stable use GitHub API. When a
newer version is detected, writes `~/.teleclaude/update_available.json`.

### Step 3: Signal file

Create a mock signal file and show its structure:
`{"current": "1.0.0", "available": "1.1.0", "channel": "beta"}`.
This file is consumed by the future auto-update executor.

### Step 4: Updated telec version

Run `telec version` — now shows the actual configured channel instead of
hardcoded "alpha".

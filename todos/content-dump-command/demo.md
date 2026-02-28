# Demo: content-dump-command

## Validation

```bash
# Verify the command exists and shows help
telec content dump --help
```

```bash
# Create a content dump with auto-generated slug
telec content dump "The moment we realized agent shorthand could compress 90% of inter-agent communication"
```

```bash
# Verify the inbox entry was created
ls publications/inbox/ | grep "$(date +%Y%m%d)"
```

```bash
# Verify content.md contains the dump text
cat publications/inbox/$(ls publications/inbox/ | grep "$(date +%Y%m%d)" | tail -1)/content.md
```

```bash
# Verify meta.yaml was written
cat publications/inbox/$(ls publications/inbox/ | grep "$(date +%Y%m%d)" | tail -1)/meta.yaml
```

```bash
# Create a dump with explicit slug and tags
telec content dump "Deep dive into mesh architecture" --slug mesh-deep-dive --tags "mesh,architecture,design" --author claude
```

```bash
# Verify the explicit slug was used
ls publications/inbox/ | grep mesh-deep-dive
```

## Guided Presentation

### Step 1: The five-minute dump

Run `telec content dump` with a natural brain dump — the kind of thing you'd say in
conversation.

**What to observe:** The command returns immediately. No processing happens inline.
The inbox folder appears with `content.md` and `meta.yaml`.

**Why it matters:** This is the friction-free entry point. The human (or agent) dumps
raw material and walks away. The system handles the rest.

### Step 2: Inspect the artifacts

Look at the created `content.md` — it's the raw text, unmodified. Look at `meta.yaml` —
it has the author identity and tags. The folder name follows the `YYYYMMDD-<slug>`
convention.

**What to observe:** The artifacts match the publications inbox schema exactly. No
special processing was applied to the content — it's raw material for the writer agent.

**Why it matters:** The dump command is an ingestion primitive. It doesn't interpret,
edit, or route. It captures and signals.

### Step 3: The notification (when notification-service is live)

When the notification service is built and running, the dump command also fires a
`content.dumped` event. This triggers the writer agent to pick up the content, verify
it against reality, and refine it.

**What to observe:** The event appears in the notification stream. The writer agent
(if subscribed) begins processing.

**Why it matters:** This is the decoupling point. The dump and the processing are
separate concerns. The notification is the bridge.

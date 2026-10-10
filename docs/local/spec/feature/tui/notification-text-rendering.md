---
description: "Notification-text contract for the running TUI: a notification displays
  the text it was given literally, so no message content can alter rendering or interrupt
  the operator's session."
---

# Notification Text Rendering — Spec

## What it is

<!-- planned-change:quiet-technical-faults -->

The TUI raises notifications carrying text it does not author: exception
messages, API error details, daemon-broadcast failure text, and media metadata.
That text is data, and the TUI treats it as data.
<!-- change:quiet-technical-faults -->

The TUI renders intentional work feedback and media metadata as literal text.
The work-feedback contract owns failure-notification eligibility
(`local/projects/teleclaude/spec/feature/presentation/work-feedback`); this
surface owns the rendering of eligible notification text.
<!-- /planned-change:quiet-technical-faults -->

The contract is a single invariant: a notification displays the text it was
given, character for character, to the operator watching the TUI. No property of
the message content changes how the notification renders, and no message content
can interrupt the operator's session. Emphasis and severity are chosen by the
caller through the notification's own severity and title, never by characters
embedded in the message.

The declaration travels with the call, not with the content: a surface raising
text it did not author says so, and nothing is inferred from the shape of the
text. Notifications the terminal framework raises for its own surfaces keep the
framework's own rendering.

## Canonical fields

### Use cases

<!-- planned-change:quiet-technical-faults -->

#### UC-TNR1: Notification text containing bracketed metadata renders literally

```gherkin
Given an operator is working in the running TUI
When a notification raised to that operator carries text the TUI did not author,
  containing bracketed metadata such as a validation error's reported type and input value
Then the operator sees that text displayed exactly as it was received
And the TUI stays open for the operator to keep working
```

<!-- change:quiet-technical-faults -->

#### UC-TNR1: Notification text containing bracketed metadata renders literally

```gherkin
Given a human operator is working in the running TUI
When eligible notification text contains bracketed metadata
Then the operator sees that text displayed exactly as it was supplied
And the TUI stays open for the operator to keep working
```

<!-- /planned-change:quiet-technical-faults -->

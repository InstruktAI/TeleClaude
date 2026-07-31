---
description: TUI pane theming applies background and border styling to session and
  TUI panes, and stays resilient when the hosting tmux server has no attached client.
---

# Pane Theming — Spec

## What it is

The TUI pane manager styles its panes by setting tmux window and border options and
then asking tmux to re-evaluate the current client's styles. The style-setting
targets panes and sessions directly and always applies; the client re-evaluation
only has an effect when a client is attached.

A tmux server can host the TUI with no client attached — a detached session, or the
TUI process receiving an appearance-change signal while no terminal is attached.
Client re-evaluation is meaningless in that state: there is no current client to
refresh. Pane theming treats the client-less server as a normal condition — it
applies the pane and border styling and completes, rather than failing because no
client is present.

## Canonical fields

### Use cases

#### UC-PTHEME-1: TUI pane theming completes when the tmux server has no attached client

```
Given the TUI pane manager runs against a tmux server with no client attached
When it applies the TUI pane background theming
Then the theming operation completes without raising
And the pane window and border style options are applied
```

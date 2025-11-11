# Roadmap

## 1. [ ] Notifications

Create claude code "notification" hook that sends informative feedback message to the channel/topic via adapter_client.send_message. Look at /Users/Morriz/.claude/hooks/notification.py for inspiration. Imperative is that we use a bootstrapped adapter_client like in daemon.py, as it has all the UiAdapters wired up so they recieve notificaitons. The message can just be randomized out of a set of templates like "Claude is ready...", "Claude is back baby...", "Claude reporting back for duty...", etc. Make like 15 nice ones. Important side note: we keep an inactivity timer, which should be compleetely nuked once that message is sent. I dont know how to signal that to daemon, but I think its best to keep the state in ux_state blob in the db, so you should make daemon check that flag (inside the inactivity timer loop?).

## 2. [ ]

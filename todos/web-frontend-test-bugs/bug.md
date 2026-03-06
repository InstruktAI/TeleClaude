# Bug:

## Symptom

I'm just going to dump my initial bugs that I find after testing the new web front end. Right now, one of the big grievances is that I see huge loading times for any message thread. As if it is completely restoring it from somewhere remote. Either dead, or it is very very performance unfriendly from rendering from the database. I would expect the messages to come from the database. They have been all been pulled in one time now for the session. But when I switch between sessions, I just have to wait so long. And this happens after every refresh of the browser of the app starting up again, so making me believe that the API is not using the message storage like we had in the requirements. We would just inflate from cash and let the events take it from there. No, not the events. So probably it is always trying to get new messages from the server, but maybe it is just getting them all and deciding oh, I already have 99%, I only need these last ones. So these kinds of things pop into my mind. So I want you to do a thorough analysis and investigation and see if this is the case, what is going on. Don't take my word for it. Just be a fucking bug hunter that is going to discover all the things that we can optimise on.

Additional confirmed symptom:

- Live web chat currently surfaces internal transcript tool blocks as generic tool UI, while the web history path hides those same internal blocks. The live stream and history view are not projecting the same transcript semantics.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-22

## Investigation

<!-- Fix worker fills this during debugging -->

### Confirmed stream-semantics bug

- `GET /sessions/{id}/messages` uses the structured transcript extraction path with `include_tools=False` by default.
- `/api/chat/stream` replays raw transcript entries through `convert_entry()` and maps `tool_use` / `tool_result` directly to AI SDK tool parts.
- The Next.js `/api/chat` route proxies the daemon SSE stream unchanged.
- The frontend renders unknown tool parts through a generic fallback block.

Architectural owner: `conversation-projection-unification`

## Root Cause

<!-- Fix worker fills this after investigation -->

### Confirmed root cause for the stream-semantics bug

Web history and web live streaming currently use different transcript projection paths:

- history path: filtered structured-message projection
- live path: raw transcript-block replay

Because the live path classifies transcript blocks independently, it leaks internal tool transcript structure into the user-visible chat stream.

### Loading-latency investigation

Still open in this bug bucket.

## Fix Applied

<!-- Fix worker fills this after committing the fix -->

No fix applied yet. The architectural fix is tracked under `conversation-projection-unification`.

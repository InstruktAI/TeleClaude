---
visibility: public
number: 0074
date: 2026-08-07
description: Service definition deployment moves from the daemon control path to the install path and is gated on rendered content rather than file existence, so a corrected template self-deploys on the next make install without bouncing services whose definitions did not change.
---

# Install Owns Content-Gated Service Definition Deployment — ADR

## Context

ADR-0041 scoped `bin/daemon-control.sh` as the internal implementation of the
`make` targets and named launchd/systemd installation among the mechanics it
owns. Deployment therefore sat on the control path, reached from `make start`
and `make restart`, and guarded by a file-existence test: a definition was
rendered from its template only when no file existed at the deployed path.

That guard cannot observe drift. Once a definition exists on disk, no `make
start`, `make restart`, or `make install` regenerates it however far its
template has moved. A template corrected in the repository silently never
reaches any host that already carries the old file, and the gap is invisible
because every lifecycle command reports success.

The failure was observed rather than predicted. The cron plist template was
corrected to the XDG user-space log path four weeks before the deployed plist
was found still carrying the pre-migration path under a root-owned directory a
user LaunchAgent cannot create. launchd failed to spawn the job every 300
seconds for that entire window, past 2000 recorded attempts, while `make
install` and `make restart` were run repeatedly and could not fix it.

Two forces then shaped where deployment belongs. A guard that reads content
rather than existence is a no-op when nothing changed, which makes deployment
safe to run often. And `make install` already runs on every setup change and is
checkpoint-mandated, so it runs far more often than the start path and reaches
every host in the fleet.

## Decision

Service definition deployment is owned by the install path. The installer
functions live in `bin/init/install_services.sh`, sourced by `bin/install.sh`
alongside the other init steps, and run on every `make install`.
`bin/daemon-control.sh` retains lifecycle only — start, stop, restart, kill,
status — and reaches the same deployment functions by sourcing that one file
rather than carrying a second copy.

Deployment is gated on content. Each definition is rendered from its template
to a temporary file and compared against what is deployed; the definition is
written and its unit reloaded only when the two differ. A definition whose
rendered content is identical leaves its running service untouched.

The content gate is what makes the ownership move safe. Deployment on every
`make install` without it would bootout and bootstrap every service on every
install across the fleet.

## Consequences

- A corrected template self-deploys. The next `make install` on any host
  reconciles that host's definitions to the repository, so a template fix no
  longer requires knowing which machines carry a stale copy.
- The failure class that hid the cron outage is closed at its source: staleness
  is now detectable by the same mechanism that repairs it, because the
  comparison that decides whether to write is a comparison against the truth.
- `make install` acquires the power to reload services. On a host whose daemon
  plist content changed, `make install` now bounces the daemon where previously
  it never touched services. This is intended and is bounded by the content
  gate; it is nonetheless a new effect of a target agents run routinely.
- On Linux, `make install` now performs the `sudo`-requiring systemd unit
  writes that previously happened only on the start path.
- The existence guards in `ensure_launchd_managed_plists` and
  `start_launchd_unit` stop being the fleet's only deployment trigger. The
  start path keeps a self-heal, but it is no longer load-bearing for
  correctness of definition content.

## Alternatives Considered

- **Content-gate in place, leaving deployment on the control path.** Rejected:
  it fixes drift only on hosts where `make start` or `make restart` is run, and
  leaves the deployment capability in a script whose stated responsibility is
  lifecycle. The observed outage happened on a host where `make restart` was
  run repeatedly, so reachability alone was never the problem — but the control
  path remains the less frequently and less uniformly exercised of the two.
- **Move deployment to install while keeping the existence guard.** Rejected:
  the guard is the defect. Moving it changes which command fails to deploy.
- **Deploy unconditionally on every `make install`.** Rejected: it would
  bootout and bootstrap the daemon, docs watcher, and cron unit on every
  checkpoint-mandated install across the fleet, trading a silent staleness
  failure for a routine availability cost.

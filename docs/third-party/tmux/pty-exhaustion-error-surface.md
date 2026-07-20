---
description: tmux + macOS (Darwin) error surface when the system-wide PTY table is exhausted
---

# tmux PTY-Exhaustion Error Surface (macOS)

## Purpose

Document the exact, source-grounded error contract observed when tmux cannot
allocate a pseudo-terminal on macOS because the system-wide PTY table is full.
TeleClaude's process-tier tests drive real tmux servers on a shared host that
runs many concurrent production tmux sessions; they discriminate this
environmental condition from genuine failures using the signature below.

## The failure chain

1. **Darwin caps pseudo-terminals system-wide.** The XNU kernel enforces
   `kern.tty.ptmx_max` (default **511**, hard maximum 999). Allocation is denied
   in `ptmx_get_ioctl` when active PTYs reach the cap
   (`bsd/kern/tty_ptmx.c`):

   ```c
   if ((_state.pis_total - _state.pis_free) >= ptmx_max) {
       DEVFS_UNLOCK();
       printf("ptmx_get_ioctl failed due to ptmx_max limit %d\n", ptmx_max);
       return NULL;
   }
   ```

2. **The denied open returns ENXIO.** The master open handler `ptcopen`
   (`bsd/kern/tty_dev.c`) maps the NULL allocation to `ENXIO`:

   ```c
   struct ptmx_ioctl *pti = pty_get_ioctl(dev, PF_OPEN_M, &driver);
   if (pti == NULL) {
       return ENXIO;
   }
   ```

3. **Darwin renders ENXIO as `Device not configured`.**
   `strerror(ENXIO)` (errno 6) is `"Device not configured"` on macOS —
   distinct from Linux's `"No such device or address"`.

4. **tmux surfaces the errno through its fork error.** Every pane process is
   spawned via `fdforkpty` in `spawn_pane` (tmux `spawn.c`); on failure tmux
   formats the cause with `strerror(errno)`:

   ```c
   new_wp->pid = fdforkpty(ptm_fd, &new_wp->fd, new_wp->tty, NULL, &ws);
   if (new_wp->pid == -1) {
       xasprintf(cause, "fork failed: %s", strerror(errno));
   ```

   Commands that spawn panes (`new-session`, `split-window`, `respawn-pane`)
   prepend their own context, e.g. `respawn pane failed: fork failed: Device
not configured`, print the message to the client's stderr, and exit
   nonzero.

## The discriminating signature

`fork failed: Device not configured` on a failed tmux command's stderr
identifies **PTY-table exhaustion at the fork moment** on macOS:

- The `fork failed:` prefix pins the failure to `spawn_pane`'s `fdforkpty`
  call (source above), not to command parsing or server logic.
- `Device not configured` pins the errno to ENXIO, which on the Darwin
  master-PTY open path is returned only from the denied allocation
  (`ptcopen` → `pty_get_ioctl` NULL). A genuine fork resource failure would
  render as EAGAIN ("Resource temporarily unavailable") or ENOMEM instead.

The signature is Darwin-specific: on Linux the same exhaustion renders a
different strerror text. Consumers matching this signature should treat a
non-match as an ordinary failure, never widen the match.

## Local verification

`sysctl kern.tty.ptmx_max` → 511; Python `os.strerror(errno.ENXIO)` →
`Device not configured` (Darwin 27.0.0).

## Sources

- [tmux spawn.c — spawn_pane fork error](https://raw.githubusercontent.com/tmux/tmux/master/spawn.c)
- [XNU tty_ptmx.c — ptmx_get_ioctl and kern.tty.ptmx_max](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/kern/tty_ptmx.c)
- [XNU tty_dev.c — ptcopen ENXIO on denied allocation](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/kern/tty_dev.c)

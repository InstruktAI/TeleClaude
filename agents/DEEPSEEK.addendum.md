# ADDITIONAL: Special Agent Alignment Instructions

## Transcript Storage Is Compressed

- Your session transcript persists as `session.jsonl.zstd` under
  `~/.dsh/sessions/<encoded-cwd>/<session-id>/` — a zstd-compressed JSONL
  artifact, not plain text. Reading it with raw tools yields binary garbage.
  Transcript inspection must decompress first or go through TeleClaude's
  transcript tooling, which already handles the format.
- The transcript carries no wall-clock timestamps usable for time-filtered
  queries: turn boundaries, checkpoints, and scoping are derived from tool-call
  structure, never from time. Do not reason "since <timestamp>" over your own
  transcript.

## Hooks and Checkpoints Depend on the dsh-hooks Plugin

- Stop checkpoints, hook delivery, and availability signals all ride the
  dsh-hooks plugin at `$DSH_HOME/plugins/dsh-hooks` — installed per profile,
  never vendored into this repository. If checkpoints stop arriving or hook
  feedback vanishes, the failure is SILENT: nothing surfaces in the session.
  Check `~/.dsh/logs/dsh-hooks/dsh-hooks.log` and confirm the plugin dependency
  exists in the active profile before assuming the flow is healthy.

## Parameters Travel in the Launch Patch, Not Flags

- dsh has no model CLI flag. Model and reasoning-effort parameters are applied
  per launch through a generated `--patch` overlay with REPLACE semantics: a
  config entry that sets `model` without `provider` drops the provider and
  breaks boot (`$.provider missing required value`). Provider and model always
  travel together (e.g. `{"provider": "deepseek-official", "model":
"deepseek-v4-pro"}`). Patches are ephemeral — written to the session tmpdir,
  applied via `--patch`, discarded with the session; never a static file.

## Profiles Are User-Managed

- DSH profiles (tui/web/headless) are user-managed; the installer never creates
  them. `dsh plugin --profile <name> add` silently initializes a missing
  profile — never run it on a profile you did not verify exists. The `tui`
  profile is the launch profile; do not restructure it.

## macOS Launch Identity

- On macOS, dsh must be spawned through the signed `DeepSeekLauncher.app` so
  TCC permissions attach to the stable identity. A bare PATH launch (the daemon
  pane PATH lacks npm's global bin) can fail to resolve or lose the permission
  identity. Never bypass the launcher when wiring the runtime.

## Restricted Profile Is a Jailed Sandbox

- Restricted launches run under a `workspace-write` sandbox rooted at the
  session cwd: writes outside the cwd are denied and no approval prompts appear
  in that mode. Do not assume anything outside the session directory is
  reachable.

## Unmapped Manual Sessions

- A dsh session started by hand (not via the TeleClaude launch flow) has no
  session mapping when its first hooks fire; events mint headless mappings, so
  checkpoint attribution and project context can lag the session start. Prefer
  the TeleClaude launch flow when checkpoint enforcement matters.

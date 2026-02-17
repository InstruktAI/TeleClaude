/**
 * Core tmux wrapper for synchronous pane management.
 *
 * All commands run via `execSync` which is fine for tmux operations (they
 * complete in microseconds). When not running inside tmux, operations degrade
 * to no-ops with warnings logged to stderr.
 *
 * Ported from: teleclaude/cli/tui/pane_manager.py (TmuxPaneManager core)
 */

import { execSync } from "node:child_process";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PaneInfo {
  id: string;
  width: number;
  height: number;
  active: boolean;
  title: string;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Whether the process was started inside a tmux session. */
const IN_TMUX = Boolean(process.env.TMUX);

/**
 * Resolve the tmux binary. Prefers TMUX_BINARY env for custom installs
 * (e.g. homebrew on macOS). Falls back to "tmux".
 */
function tmuxBinary(): string {
  return process.env.TMUX_BINARY || "tmux";
}

/**
 * Build a full tmux argument string including optional socket path.
 *
 * The socket path is extracted from the TMUX env var (format:
 * "/path/to/socket,pid,window"). Using an explicit socket ensures commands
 * target the correct server when multiple tmux instances exist.
 */
function socketArgs(): string[] {
  const tmuxEnv = process.env.TMUX;
  if (!tmuxEnv) return [];
  const socketPath = tmuxEnv.split(",")[0];
  return socketPath ? ["-S", socketPath] : [];
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Execute a tmux command and return stdout.
 *
 * Throws on non-zero exit codes. Use `tmuxExecSafe` when errors are expected.
 */
export function tmuxExec(cmd: string): string {
  const binary = tmuxBinary();
  const socket = socketArgs();
  const full = [binary, ...socket, ...cmd.split(/\s+/)].join(" ");
  return execSync(full, {
    encoding: "utf-8",
    timeout: 5_000,
    stdio: ["pipe", "pipe", "pipe"],
  }).trim();
}

/**
 * Execute a tmux command, returning null on any error.
 *
 * Useful for probing operations (pane existence checks, etc.)
 */
export function tmuxExecSafe(cmd: string): string | null {
  try {
    return tmuxExec(cmd);
  } catch {
    return null;
  }
}

/**
 * Execute tmux with pre-split argument array.
 *
 * Internal workaround for commands whose arguments contain spaces or special
 * characters that would break naive `split(/\s+/)` parsing.
 */
export function tmuxExecArgs(...args: string[]): string {
  const binary = tmuxBinary();
  const socket = socketArgs();
  const full = [binary, ...socket, ...args];
  return execSync(full.join(" "), {
    encoding: "utf-8",
    timeout: 5_000,
    stdio: ["pipe", "pipe", "pipe"],
  }).trim();
}

/**
 * Safe variant of tmuxExecArgs -- returns null on error.
 */
export function tmuxExecArgsSafe(...args: string[]): string | null {
  try {
    return tmuxExecArgs(...args);
  } catch {
    return null;
  }
}

/** Check whether the current process is running inside tmux. */
export function isTmuxAvailable(): boolean {
  return IN_TMUX;
}

/** Get the current tmux session name. */
export function getTmuxSessionName(): string {
  if (!IN_TMUX) return "";
  return tmuxExecSafe("display-message -p #{session_name}") ?? "";
}

/** Get the pane ID of the pane running this process. */
export function getCurrentPaneId(): string {
  if (!IN_TMUX) return "";
  return tmuxExecSafe("display-message -p #{pane_id}") ?? "";
}

/** Get the tmux window ID for the current window. */
export function getWindowId(): string {
  if (!IN_TMUX) return "";
  return tmuxExecSafe("display-message -p #{window_id}") ?? "";
}

/** List all panes in the current window. */
export function listPanes(): PaneInfo[] {
  if (!IN_TMUX) return [];

  const output = tmuxExecSafe(
    "list-panes -F #{pane_id}:#{pane_width}:#{pane_height}:#{pane_active}:#{pane_title}",
  );
  if (!output) return [];

  return output
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const [id, w, h, active, ...titleParts] = line.split(":");
      return {
        id: id ?? "",
        width: parseInt(w ?? "0", 10),
        height: parseInt(h ?? "0", 10),
        active: active === "1",
        title: titleParts.join(":"),
      };
    });
}

/** Check whether a specific pane still exists. */
export function paneExists(paneId: string): boolean {
  if (!IN_TMUX) return false;
  const output = tmuxExecSafe("list-panes -F #{pane_id}");
  if (!output) return false;
  return output.split("\n").includes(paneId);
}

/** Kill (close) a specific pane. */
export function killPane(paneId: string): void {
  if (!IN_TMUX) return;
  tmuxExecSafe(`kill-pane -t ${paneId}`);
}

/** Focus (select) a specific pane. */
export function selectPane(paneId: string): void {
  if (!IN_TMUX) return;
  tmuxExecSafe(`select-pane -t ${paneId}`);
}

/** Resize a pane to exact dimensions. */
export function resizePane(
  paneId: string,
  width: number,
  height: number,
): void {
  if (!IN_TMUX) return;
  tmuxExecSafe(`resize-pane -t ${paneId} -x ${width} -y ${height}`);
}

/**
 * Split a pane and return the new pane ID.
 *
 * @param target - Pane ID to split from
 * @param direction - "h" for horizontal (left/right), "v" for vertical (top/bottom)
 * @param opts - Optional size percentage and detach flag
 * @param command - Optional shell command to run in the new pane
 */
export function splitWindow(
  target: string,
  direction: "h" | "v",
  opts?: { percent?: number; detach?: boolean },
  command?: string,
): string | null {
  if (!IN_TMUX) return null;

  const args = ["split-window", `-${direction}`, "-t", target];
  if (opts?.percent) args.push("-p", String(opts.percent));
  if (opts?.detach !== false) args.push("-d");
  args.push("-P", "-F", "#{pane_id}");
  if (command) args.push(command);

  return tmuxExecArgsSafe(...args);
}

/**
 * Respawn (replace) the running process in a pane.
 *
 * Uses `-k` to force-kill the current process before respawning.
 */
export function respawnPane(paneId: string, command: string): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("respawn-pane", "-k", "-t", paneId, command);
}

/**
 * Send keys to a pane (literal string + Enter).
 *
 * Used for SSH-based remote session attach where the pane runs a shell.
 */
export function sendKeys(paneId: string, keys: string): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("send-keys", "-t", paneId, keys, "Enter");
}

/**
 * Set a tmux pane option.
 */
export function setPaneOption(
  paneId: string,
  option: string,
  value: string,
): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set", "-p", "-t", paneId, option, value);
}

/**
 * Unset (reset) a tmux pane option to default.
 */
export function unsetPaneOption(paneId: string, option: string): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set", "-pu", "-t", paneId, option);
}

/**
 * Set a tmux window option.
 */
export function setWindowOption(
  paneId: string,
  option: string,
  value: string,
): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set", "-w", "-t", paneId, option, value);
}

/**
 * Unset (reset) a tmux window option to default.
 */
export function unsetWindowOption(paneId: string, option: string): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set", "-wu", "-t", paneId, option);
}

/**
 * Set a tmux session-level option.
 */
export function setSessionOption(
  session: string,
  option: string,
  value: string,
): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set", "-t", session, option, value);
}

/**
 * Set an environment variable in a tmux session.
 */
export function setSessionEnv(
  session: string,
  key: string,
  value: string,
): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set-environment", "-t", session, key, value);
}

/**
 * Unset an environment variable in a tmux session.
 */
export function unsetSessionEnv(session: string, key: string): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set-environment", "-t", session, "-u", key);
}

/**
 * Apply even-horizontal layout to the current window.
 */
export function applyEvenHorizontalLayout(): void {
  if (!IN_TMUX) return;
  tmuxExecSafe("select-layout even-horizontal");
}

/**
 * Enable truecolor passthrough for nested tmux sessions.
 *
 * Without these overrides, RGB escape sequences from CLIs (Gemini, Claude,
 * Codex) are stripped and output appears black-and-white.
 */
export function enableTruecolor(): void {
  if (!IN_TMUX) return;
  tmuxExecArgsSafe("set", "-sa", "terminal-overrides", ",tmux-256color:Tc");
  tmuxExecArgsSafe("set", "-sa", "terminal-features", "tmux-256color:RGB");
}

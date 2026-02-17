/**
 * Remote session support via SSH and tmux.
 *
 * Handles opening SSH connections from tmux panes to remote computers,
 * attaching to remote tmux sessions, and forwarding environment variables
 * for appearance consistency.
 *
 * Ported from: teleclaude/cli/tui/pane_manager.py (_build_attach_cmd, _get_appearance_env)
 */

import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

import {
  isTmuxAvailable,
  sendKeys,
  tmuxExecArgsSafe,
} from "../tmux.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Connection info for a computer (matches API ComputerInfo shape). */
export interface ComputerConnectionInfo {
  name: string;
  isLocal: boolean;
  user?: string | null;
  host?: string | null;
  tmuxBinary?: string | null;
}

// ---------------------------------------------------------------------------
// Environment forwarding
// ---------------------------------------------------------------------------

/**
 * Capture appearance environment variables from the local machine.
 *
 * These variables are forwarded to remote sessions via SSH so that nested
 * tmux clients render with consistent dark/light theming.
 *
 * @returns Key-value pairs for APPEARANCE_MODE and TERMINAL_BG
 */
export function getAppearanceEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  const appearanceBin = resolve(
    process.env.HOME ?? "~",
    ".local/bin/appearance",
  );

  if (!existsSync(appearanceBin)) return env;

  // Get mode (dark/light).
  try {
    const result = execSync(`${appearanceBin} get-mode`, {
      encoding: "utf-8",
      timeout: 5_000,
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
    if (result) env.APPEARANCE_MODE = result;
  } catch {
    // Detection unavailable -- skip.
  }

  // Get terminal background hex.
  try {
    const result = execSync(`${appearanceBin} get-terminal-bg`, {
      encoding: "utf-8",
      timeout: 5_000,
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
    if (result) env.TERMINAL_BG = result;
  } catch {
    // Detection unavailable -- skip.
  }

  return env;
}

// ---------------------------------------------------------------------------
// Attach command construction
// ---------------------------------------------------------------------------

/**
 * Build the inner tmux attach command with inline appearance tweaks.
 *
 * Enables truecolor passthrough for nested tmux clients and hides the
 * embedded session's status bar before attaching.
 */
function buildTmuxAttachCommand(tmuxSessionName: string): string {
  return (
    `set -sa terminal-overrides ',tmux-256color:Tc' \\; ` +
    `set -sa terminal-features 'tmux-256color:RGB' \\; ` +
    `set-option -t ${tmuxSessionName} status off \\; ` +
    `attach-session -t ${tmuxSessionName}`
  );
}

/**
 * Build the full command to attach to a tmux session.
 *
 * For local sessions: `env -u TMUX TERM=tmux-256color <tmux> -u <attach>`
 * For remote sessions: `ssh -t -A user@host '<env> TERM=tmux-256color <tmux> -u <attach>'`
 *
 * @param tmuxSessionName - Target tmux session name
 * @param computer        - Computer connection info (null = local)
 * @returns Shell command string to execute in a pane
 */
export function buildAttachCommand(
  tmuxSessionName: string,
  computer?: ComputerConnectionInfo | null,
): string {
  const attachCmd = buildTmuxAttachCommand(tmuxSessionName);

  if (computer && !computer.isLocal) {
    // Remote: SSH to the computer and attach there.
    const sshTarget = `${computer.user}@${computer.host}`;
    const tmuxBinary = computer.tmuxBinary ?? "tmux";

    // Forward appearance settings from host to remote.
    const appearanceEnv = getAppearanceEnv();
    const envStr = Object.entries(appearanceEnv)
      .map(([k, v]) => `${k}=${v}`)
      .join(" ");
    const envPrefix = envStr ? `${envStr} ` : "";

    return `ssh -t -A ${sshTarget} '${envPrefix}TERM=tmux-256color ${tmuxBinary} -u ${attachCmd}'`;
  }

  // Local: use configured tmux binary with nested attach.
  // `env -u TMUX` unsets TMUX so the nested attach works correctly.
  const tmuxBinary = computer?.tmuxBinary ?? process.env.TMUX_BINARY ?? "tmux";
  return `env -u TMUX TERM=tmux-256color ${tmuxBinary} -u ${attachCmd}`;
}

// ---------------------------------------------------------------------------
// Pane session attachment
// ---------------------------------------------------------------------------

/**
 * Attach a remote tmux session inside an existing pane.
 *
 * Sends the SSH + tmux attach command as keystrokes to the pane.
 *
 * @param computer  - Remote computer connection info
 * @param sessionId - TeleClaude session ID (for environment forwarding)
 * @param paneId    - Tmux pane to run the connection in
 */
export function attachRemoteSession(
  computer: ComputerConnectionInfo,
  tmuxSessionName: string,
  paneId: string,
): void {
  if (!isTmuxAvailable()) return;
  const cmd = buildAttachCommand(tmuxSessionName, computer);
  sendKeys(paneId, cmd);
}

/**
 * Detach a remote session by sending Ctrl-B d (tmux detach) to the pane.
 *
 * This gracefully disconnects from the remote tmux session without killing
 * the SSH connection.
 */
export function detachRemoteSession(paneId: string): void {
  if (!isTmuxAvailable()) return;
  // Send tmux prefix + d to detach the nested session.
  tmuxExecArgsSafe("send-keys", "-t", paneId, "C-b", "d");
}

/**
 * Set environment variables in a remote session for session tracking.
 *
 * Forwards TELECLAUDE_SESSION_ID and TELECLAUDE_COMPUTER into the tmux
 * session environment so remote agents can identify themselves.
 *
 * @param tmuxSessionName - The tmux session to configure
 * @param sessionId       - TeleClaude session ID
 * @param computerName    - Computer name for the session
 */
export function forwardSessionEnv(
  tmuxSessionName: string,
  sessionId: string,
  computerName: string,
): void {
  if (!isTmuxAvailable()) return;
  tmuxExecArgsSafe(
    "set-environment",
    "-t",
    tmuxSessionName,
    "TELECLAUDE_SESSION_ID",
    sessionId,
  );
  tmuxExecArgsSafe(
    "set-environment",
    "-t",
    tmuxSessionName,
    "TELECLAUDE_COMPUTER",
    computerName,
  );
}

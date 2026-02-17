/**
 * Agent-specific tmux pane background theming.
 *
 * Computes haze-blended background colors for session panes so each agent
 * type (Claude, Gemini, Codex) has a visually distinct tint. The blend
 * formula mixes the terminal background with the agent's haze color at
 * configurable percentages for inactive, selected, and active states.
 *
 * Ported from: teleclaude/cli/tui/theme.py (pane background functions)
 */

import {
  type AgentType,
  AGENT_COLORS,
  HAZE_CONFIG,
  blendColors,
  detectThemeMode,
  safeAgent,
} from "@/lib/theme/tokens.js";

import {
  isTmuxAvailable,
  setPaneOption,
  setSessionOption,
  setSessionEnv,
  setWindowOption,
  unsetPaneOption,
  unsetSessionEnv,
  unsetWindowOption,
} from "../tmux.js";

// ---------------------------------------------------------------------------
// Internal state
// ---------------------------------------------------------------------------

/**
 * Cached terminal background. Resolved once on first use, then held for the
 * session. Call `resetTerminalBg` after a theme change (SIGUSR1).
 */
let _terminalBgCache: string | null = null;

// ---------------------------------------------------------------------------
// Terminal background detection
// ---------------------------------------------------------------------------

/**
 * Get the terminal's baseline background color.
 *
 * Uses TERMINAL_BG env var when available, otherwise falls back to
 * mode-appropriate defaults (#000000 for dark, #fdf6e3 for light).
 */
export function getTerminalBackground(): string {
  if (_terminalBgCache) return _terminalBgCache;

  const mode = detectThemeMode();
  const modeDefault = mode === "dark" ? "#000000" : "#fdf6e3";

  const hint = (process.env.TERMINAL_BG ?? "").trim();
  if (hint && /^#[0-9a-fA-F]{6}$/.test(hint)) {
    _terminalBgCache = blendColors(
      modeDefault,
      hint,
      HAZE_CONFIG.terminalHintWeight,
    );
    return _terminalBgCache;
  }

  _terminalBgCache = modeDefault;
  return _terminalBgCache;
}

/** Clear the cached terminal background (e.g. after appearance change). */
export function resetTerminalBg(): void {
  _terminalBgCache = null;
}

// ---------------------------------------------------------------------------
// Agent pane background computation
// ---------------------------------------------------------------------------

/**
 * Compute the blended background color for an agent's pane.
 *
 * @param agent         - Agent name ("claude", "gemini", "codex")
 * @param hazePercent   - Blend percentage (0.0 = terminal bg, 1.0 = full agent color)
 * @returns Hex color string (e.g. "#2a2520")
 */
export function agentPaneBg(agent: string, hazePercent: number): string {
  const mode = detectThemeMode();
  const safe = safeAgent(agent);
  const agentHaze = AGENT_COLORS[mode][safe].haze;
  const baseBg = getTerminalBackground();
  return blendColors(baseBg, agentHaze, hazePercent);
}

/** Inactive pane background: visible haze tint (18% blend). */
export function agentPaneInactiveBg(agent: string): string {
  return agentPaneBg(agent, HAZE_CONFIG.paneInactive);
}

/** Tree-selected pane background: subtle lighter haze (8% blend). */
export function agentPaneSelectedBg(agent: string): string {
  return agentPaneBg(agent, HAZE_CONFIG.paneTreeSelected);
}

/** Active (focused) pane background: no haze, pure terminal bg. */
export function agentPaneActiveBg(agent: string): string {
  return agentPaneBg(agent, HAZE_CONFIG.paneActive);
}

/** Status accent background: very subtle haze for status bars (6% blend). */
export function agentStatusBg(agent: string): string {
  return agentPaneBg(agent, HAZE_CONFIG.statusAccent);
}

/**
 * TUI pane inactive background: mode-specific haze toward white/black.
 *
 * In dark mode: 12% blend toward white.
 * In light mode: 6% blend toward black.
 */
export function tuiInactiveBg(): string {
  const mode = detectThemeMode();
  const baseBg = getTerminalBackground();
  const blendTarget = mode === "dark" ? "#ffffff" : "#000000";
  const pct =
    mode === "dark"
      ? HAZE_CONFIG.tuiInactiveDark
      : HAZE_CONFIG.tuiInactiveLight;
  return blendColors(baseBg, blendTarget, pct);
}

// ---------------------------------------------------------------------------
// Tmux pane color application
// ---------------------------------------------------------------------------

/**
 * Apply agent-themed background colors to a tmux session pane.
 *
 * Sets both `window-style` (inactive state) and `window-active-style`
 * (focused state) so the pane transitions smoothly when gaining/losing focus.
 *
 * Also hides the embedded session's tmux status bar and manages NO_COLOR
 * env based on the theming level.
 *
 * @param paneId          - Tmux pane ID (e.g. "%42")
 * @param agentType       - Agent for color selection
 * @param tmuxSessionName - The tmux session name shown in this pane
 * @param opts            - Additional options
 */
export function applyPaneColor(
  paneId: string,
  agentType: string,
  tmuxSessionName: string,
  opts?: {
    isTreeSelected?: boolean;
    themingEnabled?: boolean;
    themingLevel?: number;
  },
): void {
  if (!isTmuxAvailable()) return;

  const themingEnabled = opts?.themingEnabled ?? true;
  const themingLevel = opts?.themingLevel ?? 3;

  if (themingEnabled) {
    const safe = safeAgent(agentType);
    const mode = detectThemeMode();
    const normalColor = AGENT_COLORS[mode][safe].normal;

    const bgColor = opts?.isTreeSelected
      ? agentPaneSelectedBg(agentType)
      : agentPaneInactiveBg(agentType);
    const activeBg = agentPaneActiveBg(agentType);

    setPaneOption(paneId, "window-style", `fg=${normalColor},bg=${bgColor}`);
    setPaneOption(
      paneId,
      "window-active-style",
      `fg=${normalColor},bg=${activeBg}`,
    );
  } else {
    unsetPaneOption(paneId, "window-style");
    unsetPaneOption(paneId, "window-active-style");
  }

  // Embedded session panes should not render tmux status bars.
  setSessionOption(tmuxSessionName, "status", "off");

  // Enforce NO_COLOR for peaceful levels (0, 1) to suppress CLI colors.
  if (themingLevel <= 1) {
    setSessionEnv(tmuxSessionName, "NO_COLOR", "1");
  } else {
    unsetSessionEnv(tmuxSessionName, "NO_COLOR");
  }
}

/**
 * Apply TUI pane background styling (inactive haze).
 *
 * The TUI pane gets a subtle offset from the terminal background when
 * session panes are visible, creating visual depth.
 *
 * @param tuiPaneId      - The TUI pane ID
 * @param themingEnabled - Whether theming is active
 */
export function applyTuiPaneColor(
  tuiPaneId: string,
  themingEnabled: boolean = true,
): void {
  if (!isTmuxAvailable()) return;

  if (themingEnabled) {
    const inactiveBg = tuiInactiveBg();
    const terminalBg = getTerminalBackground();
    setPaneOption(tuiPaneId, "window-style", `bg=${inactiveBg}`);
    setPaneOption(tuiPaneId, "window-active-style", `bg=${terminalBg}`);

    const borderStyle = `fg=${inactiveBg},bg=${inactiveBg}`;
    setWindowOption(tuiPaneId, "pane-border-style", borderStyle);
    setWindowOption(tuiPaneId, "pane-active-border-style", borderStyle);
  } else {
    unsetPaneOption(tuiPaneId, "window-style");
    unsetPaneOption(tuiPaneId, "window-active-style");
    unsetWindowOption(tuiPaneId, "pane-border-style");
    unsetWindowOption(tuiPaneId, "pane-active-border-style");
  }
}

/**
 * Clear all custom pane styling, resetting to terminal defaults.
 */
export function clearPaneColor(paneId: string): void {
  if (!isTmuxAvailable()) return;
  unsetPaneOption(paneId, "window-style");
  unsetPaneOption(paneId, "window-active-style");
}

/**
 * Get the hex color value for an agent's haze color.
 *
 * Useful for components that need the raw color without tmux application.
 */
export function getAgentHazeColor(agent: string): string {
  const mode = detectThemeMode();
  const safe = safeAgent(agent) as AgentType;
  return AGENT_COLORS[mode][safe].haze;
}

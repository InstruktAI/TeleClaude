/**
 * ANSI escape code utilities for terminal output
 *
 * Handles stripping and measuring ANSI escape sequences including:
 * - CSI (Control Sequence Introducer): ESC[...m (colors, bold, etc.)
 * - OSC (Operating System Command): ESC]...BEL/ST (terminal titles)
 * - Simple escape sequences: ESC= ESC>
 * - Cursor movement: ESC[...A/B/C/D/H/J/K
 * - DEC private modes: ESC[?...h/l
 */

/**
 * Comprehensive ANSI escape sequence regex pattern
 *
 * Matches:
 * - CSI sequences: ESC [ ... (m, H, J, A, B, C, D, K, etc.)
 * - OSC sequences: ESC ] ... (BEL or ST terminator)
 * - Simple sequences: ESC = ESC >
 */
const ANSI_PATTERN = /\x1b(?:\[[0-9;?]*[a-zA-Z]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[=>])/g;

/**
 * Strip all ANSI escape codes from text
 *
 * @param text - Text potentially containing ANSI codes
 * @returns Text with all ANSI codes removed
 *
 * @example
 * stripAnsi("\x1b[31mRed\x1b[0m") // "Red"
 * stripAnsi("\x1b]0;Title\x07Normal") // "Normal"
 */
export function stripAnsi(text: string | null | undefined): string {
  if (!text || typeof text !== 'string') {
    return '';
  }
  return text.replace(ANSI_PATTERN, '');
}

/**
 * Get the visible character count of text (excluding ANSI codes)
 *
 * @param text - Text with potential ANSI codes
 * @returns Number of visible characters
 *
 * @example
 * ansiLength("\x1b[31mRed\x1b[0m") // 3
 * ansiLength("Plain text") // 10
 */
export function ansiLength(text: string | null | undefined): number {
  return stripAnsi(text).length;
}

/**
 * Truncate text to a maximum visible length, preserving ANSI codes
 *
 * This function attempts to preserve ANSI codes while ensuring the visible
 * text doesn't exceed maxLen. Note: ANSI codes before the truncation point
 * are preserved, but codes after are lost.
 *
 * @param text - Text with potential ANSI codes
 * @param maxLen - Maximum visible character count
 * @returns Truncated text with preserved ANSI codes
 *
 * @example
 * truncateAnsi("\x1b[31mLong red text\x1b[0m", 8) // "\x1b[31mLong red\x1b[0m"
 * truncateAnsi("Short", 10) // "Short"
 */
export function truncateAnsi(text: string | null | undefined, maxLen: number): string {
  if (!text || typeof text !== 'string') {
    return '';
  }

  if (maxLen < 0) {
    return '';
  }

  let visibleCount = 0;
  let result = '';
  let i = 0;

  while (i < text.length && visibleCount < maxLen) {
    // Check for ANSI escape sequence start
    if (text[i] === '\x1b' && i + 1 < text.length) {
      // Find the end of the ANSI sequence
      const remaining = text.slice(i);
      const match = remaining.match(/^\x1b(?:\[[0-9;?]*[a-zA-Z]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[=>])/);

      if (match) {
        // Include the entire ANSI sequence without counting it
        result += match[0];
        i += match[0].length;
        continue;
      }
    }

    // Regular character
    result += text[i];
    visibleCount++;
    i++;
  }

  return result;
}

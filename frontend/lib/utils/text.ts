/**
 * Robust text cleaning and formatting logic for TeleClaude messages.
 * Centralized to ensure consistency across history, live streaming, and rendering.
 */

/**
 * Detect system-injected "user" messages that shouldn't appear as human input.
 */
export function isSystemInjected(text: string): boolean {
  if (typeof text !== "string") return false;
  const t = text.trim();
  return (
    t.includes("<task-notification>") ||
    t.includes("Stop hook feedback:") ||
    t.includes("This session is being continued from a previous conversation") ||
    t.includes("[Request interrupted by user]") ||
    t.includes("<system-reminder>") ||
    t.includes("[TeleClaude Checkpoint]")
  );
}

/**
 * Internal helper to resolve Python wrappers and escaped characters.
 */
function cleanRawText(text: string): string {
  let cleaned = text;
  // Full match: [{'text': '...'}]
  // Using [\s\S] instead of . with /s flag for maximum compatibility
  const fullMatch = cleaned.match(
    /^\[\s*\{\s*['"]text['"]\s*:\s*['"]([\s\S]*)['"]\s*\}\s*\]$/,
  );
  if (fullMatch) {
    cleaned = fullMatch[1];
  } else {
    if (cleaned.startsWith("[{'text': '") || cleaned.startsWith('[{"text": "')) {
      cleaned = cleaned.slice(11);
    }
    if (cleaned.endsWith("'}]") || cleaned.endsWith('"}]')) {
      cleaned = cleaned.slice(0, -3);
    }
  }

  return cleaned
    .replace(/\\n/g, "\n")
    .replace(/\\'/g, "'")
    .replace(/\\"/g, '"');
}

/**
 * Attempt to extract a command header from text.
 * Returns the formatted command line if found, otherwise null.
 */
export function getCommandHeader(text: string): string | null {
  if (typeof text !== "string") return null;
  const cleaned = cleanRawText(text);
  const trimmed = cleaned.trim();

  if (trimmed.startsWith("<command-message>")) {
    // Using [\s\S] instead of . with /s flag for maximum compatibility
    const nameMatch = cleaned.match(/<command-name>([\s\S]*?)<\/command-name>/);
    const argsMatch = cleaned.match(/<command-args>([\s\S]*?)<\/command-args>/);
    if (nameMatch) {
      const name = nameMatch[1].trim();
      const args = argsMatch ? argsMatch[1].trim() : "";
      return args ? `${name} ${args}` : `${name}`;
    }
  }
  return null;
}

/**
 * Clean up text content and format command messages.
 */
export function cleanMessageText(text: string): string {
  if (typeof text !== "string") return text;
  const header = getCommandHeader(text);
  if (header) return header;
  return cleanRawText(text);
}

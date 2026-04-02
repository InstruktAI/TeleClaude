/**
 * Robust text cleaning and formatting logic for TeleClaude messages.
 * Centralized to ensure consistency across history, live streaming, and rendering.
 */

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
 * Clean up text content and format command messages.
 */
export function cleanMessageText(text: string): string {
  if (typeof text !== "string") return text;
  return cleanRawText(text);
}

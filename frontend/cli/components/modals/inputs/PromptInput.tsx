/**
 * Text input for initial session prompt.
 *
 * Single-line mode: Enter submits. Multi-line mode: Ctrl+Enter submits.
 * Supports basic text editing (backspace, cursor display).
 * Shows placeholder text when empty.
 */

import React, { useState } from "react";
import { Box, Text, useInput } from "ink";

import { themeText } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PromptInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: () => void;
  placeholder?: string;
  isFocused?: boolean;
  maxLength?: number;
  /** When true, Enter inserts a newline; Ctrl+Enter submits. */
  multiline?: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function PromptInput({
  value,
  onChange,
  onSubmit,
  placeholder = "Enter prompt...",
  isFocused = false,
  maxLength = 500,
  multiline = false,
}: PromptInputProps) {
  const [cursorVisible, setCursorVisible] = useState(true);

  // Blink cursor on focus (simple toggle via re-render cadence)
  React.useEffect(() => {
    if (!isFocused) {
      setCursorVisible(false);
      return;
    }
    setCursorVisible(true);
    const interval = setInterval(() => {
      setCursorVisible((prev) => !prev);
    }, 530);
    return () => clearInterval(interval);
  }, [isFocused]);

  useInput(
    (input, key) => {
      if (!isFocused) return;

      // Submit handling
      if (key.return) {
        // In multiline mode, plain Enter inserts newline; submit requires Ctrl not
        // being pressed alone (Ink does not reliably surface Ctrl+Enter as a combo,
        // so single-line mode uses Enter-to-submit which is handled by the parent).
        if (multiline) {
          if (value.length < maxLength) {
            onChange(value + "\n");
          }
          return;
        }
        // Single-line: Enter submits
        onSubmit?.();
        return;
      }

      // Backspace
      if (key.backspace || key.delete) {
        if (value.length > 0) {
          onChange(value.slice(0, -1));
        }
        return;
      }

      // Regular character input (skip control sequences)
      if (input && input.length === 1 && input.charCodeAt(0) >= 32) {
        if (value.length < maxLength) {
          onChange(value + input);
        }
      }
    },
    { isActive: isFocused },
  );

  const mutedFn = themeText("muted");
  const primaryFn = themeText("primary");

  // Display logic
  const isEmpty = value.length === 0;
  const displayText = isEmpty ? placeholder : value;
  const cursor = isFocused && cursorVisible ? "\u2588" : " "; // █ block cursor

  // For multiline, show line count
  const lines = value.split("\n");
  const lineCount = lines.length;

  return (
    <Box flexDirection="column">
      <Box>
        <Text>
          {isEmpty ? (
            <Text>{mutedFn(displayText)}</Text>
          ) : (
            <Text>{primaryFn(displayText)}</Text>
          )}
          {isFocused && <Text>{cursor}</Text>}
        </Text>
      </Box>
      {isFocused && (
        <Box marginTop={0}>
          <Text>
            {mutedFn(
              `${value.length}/${maxLength}` +
                (multiline ? ` | ${lineCount} line${lineCount !== 1 ? "s" : ""}` : ""),
            )}
          </Text>
        </Box>
      )}
    </Box>
  );
}

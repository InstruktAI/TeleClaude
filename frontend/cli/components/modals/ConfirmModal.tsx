/**
 * Generic confirmation modal dialog.
 *
 * Displays a title, message, and Yes/No buttons.
 * Keyboard: Enter confirms, Escape cancels, Y/N direct shortcuts.
 * Left/Right or Tab to toggle between buttons.
 *
 * Used for: ending sessions, killing sessions, and other destructive actions.
 */

import React, { useState } from "react";
import { Box, Text, useInput } from "ink";

import { themeText, modalBorderColor } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ConfirmModalProps {
  title: string;
  message: string;
  details?: string[];
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ConfirmModal({
  title,
  message,
  details,
  confirmLabel = "Yes",
  cancelLabel = "No",
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const [selectedAction, setSelectedAction] = useState<0 | 1>(0); // 0=confirm, 1=cancel

  useInput((input, key) => {
    if (key.escape) {
      onCancel();
      return;
    }

    if (key.return) {
      if (selectedAction === 0) {
        onConfirm();
      } else {
        onCancel();
      }
      return;
    }

    // Direct shortcuts
    if (input === "y" || input === "Y") {
      onConfirm();
      return;
    }
    if (input === "n" || input === "N") {
      onCancel();
      return;
    }

    // Navigation between buttons
    if (key.leftArrow) {
      setSelectedAction(0);
    } else if (key.rightArrow) {
      setSelectedAction(1);
    } else if (key.tab) {
      setSelectedAction((prev) => (prev === 0 ? 1 : 0));
    }
  });

  const borderFn = modalBorderColor();
  const primaryFn = themeText("primary");
  const secondaryFn = themeText("secondary");
  const mutedFn = themeText("muted");

  return (
    <Box flexDirection="column">
      {/* Outer border */}
      <Box
        flexDirection="column"
        borderStyle="bold"
        borderColor="gray"
        paddingX={1}
        paddingY={0}
        width={56}
      >
        {/* Inner border with title */}
        <Box
          flexDirection="column"
          borderStyle="round"
          borderColor="gray"
          paddingX={1}
          paddingY={0}
        >
          {/* Title */}
          <Box justifyContent="center" marginBottom={1}>
            <Text bold>{borderFn(` ${title} `)}</Text>
          </Box>

          {/* Details (optional) */}
          {details && details.length > 0 && (
            <Box flexDirection="column" marginBottom={1}>
              {details.map((detail, i) => (
                <Text key={i}>{secondaryFn(detail)}</Text>
              ))}
            </Box>
          )}

          {/* Message */}
          <Box marginBottom={1}>
            <Text bold>{primaryFn(message)}</Text>
          </Box>

          {/* Action buttons */}
          <Box flexDirection="row" gap={2} marginTop={1}>
            <Text bold={selectedAction === 0} inverse={selectedAction === 0}>
              {` [Enter] ${confirmLabel} `}
            </Text>
            <Text bold={selectedAction === 1} inverse={selectedAction === 1}>
              {` [N] ${cancelLabel} `}
            </Text>
            <Text>{mutedFn("[Esc] Cancel")}</Text>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

/**
 * Toast-style notification component.
 *
 * Renders a colored bar that auto-dismisses after a timeout. Positioned
 * between the TabBar and ViewContainer in the layout stack.
 */

import React, { useEffect } from "react";
import { Box, Text } from "ink";

import { statusColor } from "@/lib/theme/ink-colors.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DISMISS_MS = 3000;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NotificationProps {
  message: string;
  type: "info" | "error" | "success";
  onDismiss: () => void;
}

// ---------------------------------------------------------------------------
// Type-to-status mapping for theme color resolution
// ---------------------------------------------------------------------------

const TYPE_STATUS_MAP: Record<NotificationProps["type"], string> = {
  info: "ready",
  error: "error",
  success: "active",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Notification({ message, type, onDismiss }: NotificationProps) {
  // Auto-dismiss timer
  useEffect(() => {
    const timer = setTimeout(onDismiss, DISMISS_MS);
    return () => clearTimeout(timer);
  }, [message, type, onDismiss]);

  const status = TYPE_STATUS_MAP[type];
  const colorFn = statusColor(status);

  // Prefix icons
  const prefixMap: Record<NotificationProps["type"], string> = {
    info: "i",
    error: "!",
    success: "*",
  };
  const prefix = prefixMap[type];

  return (
    <Box>
      <Text>{colorFn(`[${prefix}] ${message}`)}</Text>
    </Box>
  );
}

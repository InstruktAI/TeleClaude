/**
 * Time formatting utilities for relative time display
 *
 * Provides consistent time formatting across terminal and web apps
 */

/**
 * Format a date as relative time from now
 *
 * Format rules:
 * - < 60 seconds: "Xs" (e.g., "5s")
 * - < 60 minutes: "Xm" (e.g., "12m")
 * - < 24 hours: "Xh" (e.g., "3h")
 * - < 7 days: "Xd" (e.g., "2d")
 * - < 30 days: "Xw" (e.g., "1w")
 * - >= 30 days: "Xmo" (e.g., "2mo")
 * - Future dates: "now"
 *
 * @param date - Date object, ISO string, or Unix timestamp (ms)
 * @returns Relative time string
 *
 * @example
 * formatRelativeTime(new Date()) // "now"
 * formatRelativeTime(Date.now() - 5000) // "5s"
 * formatRelativeTime("2024-01-01T00:00:00Z") // "2mo" (example)
 */
export function formatRelativeTime(date: Date | string | number | null | undefined): string {
  if (!date) {
    return 'now';
  }

  let timestamp: number;

  try {
    if (typeof date === 'number') {
      timestamp = date;
    } else if (typeof date === 'string') {
      timestamp = new Date(date).getTime();
    } else if (date instanceof Date) {
      timestamp = date.getTime();
    } else {
      return 'now';
    }

    // Handle invalid dates
    if (isNaN(timestamp)) {
      return 'now';
    }
  } catch {
    return 'now';
  }

  const now = Date.now();
  const diffMs = now - timestamp;

  // Future date or very recent (< 1 second)
  if (diffMs < 1000) {
    return 'now';
  }

  const seconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const weeks = Math.floor(days / 7);
  const months = Math.floor(days / 30);

  if (seconds < 60) {
    return `${seconds}s`;
  }

  if (minutes < 60) {
    return `${minutes}m`;
  }

  if (hours < 24) {
    return `${hours}h`;
  }

  if (days < 7) {
    return `${days}d`;
  }

  if (days < 30) {
    return `${weeks}w`;
  }

  return `${months}mo`;
}

/**
 * Format a duration in milliseconds to human-readable string
 *
 * @param ms - Duration in milliseconds
 * @returns Formatted duration string (e.g., "1h 23m", "45s", "2m 5s")
 *
 * @example
 * formatDuration(5000) // "5s"
 * formatDuration(125000) // "2m 5s"
 * formatDuration(5025000) // "1h 23m"
 */
export function formatDuration(ms: number | null | undefined): string {
  if (!ms || typeof ms !== 'number' || ms < 0 || isNaN(ms)) {
    return '0s';
  }

  const seconds = Math.floor(ms / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) {
    const remainingHours = hours % 24;
    return remainingHours > 0 ? `${days}d ${remainingHours}h` : `${days}d`;
  }

  if (hours > 0) {
    const remainingMinutes = minutes % 60;
    return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`;
  }

  if (minutes > 0) {
    const remainingSeconds = seconds % 60;
    return remainingSeconds > 0 ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
  }

  return `${seconds}s`;
}

/**
 * Path utilities for display formatting
 *
 * Provides path shortening and manipulation for terminal and web display
 */

/**
 * Get the home directory path
 *
 * @returns Home directory path or empty string if not available
 *
 * @example
 * getHomedir() // "/Users/username" or "/home/username"
 */
export function getHomedir(): string {
  // Browser environment
  if (typeof process === 'undefined') {
    return '';
  }

  // Node.js environment
  if (process.env.HOME) {
    return process.env.HOME;
  }

  // Windows fallback
  if (process.env.USERPROFILE) {
    return process.env.USERPROFILE;
  }

  // Try os.homedir() if available
  try {
    const os = require('os');
    return os.homedir();
  } catch {
    return '';
  }
}

/**
 * Get the last segment of a path (basename)
 *
 * @param path - File or directory path
 * @returns Last path segment
 *
 * @example
 * basename("/path/to/file.txt") // "file.txt"
 * basename("/path/to/dir/") // "dir"
 * basename("file.txt") // "file.txt"
 */
export function basename(path: string | null | undefined): string {
  if (!path || typeof path !== 'string') {
    return '';
  }

  // Remove trailing slashes
  const trimmed = path.replace(/\/+$/, '');

  if (!trimmed) {
    return '';
  }

  // Get last segment
  const parts = trimmed.split('/');
  return parts[parts.length - 1] || '';
}

/**
 * Shorten a path for display by replacing home directory and truncating middle segments
 *
 * Rules:
 * - Replace home directory with `~`
 * - If still too long, truncate middle segments with `...`
 * - Always keep first segment (~ or /) and last 2 segments
 * - If path fits in maxLen, return as-is (with ~ substitution)
 *
 * @param path - Full path to shorten
 * @param maxLen - Maximum display length
 * @returns Shortened path
 *
 * @example
 * shortenPath("/Users/username/Documents/project/file.txt", 30)
 * // "~/Documents/project/file.txt" (if fits)
 *
 * shortenPath("/Users/username/Very/Long/Path/project/file.txt", 30)
 * // "~/.../Path/project/file.txt"
 *
 * shortenPath("/a/b", 20) // "/a/b"
 */
export function shortenPath(path: string | null | undefined, maxLen: number): string {
  if (!path || typeof path !== 'string') {
    return '';
  }

  if (maxLen < 0) {
    return '';
  }

  let result = path;

  // Replace home directory with ~
  const homedir = getHomedir();
  if (homedir && result.startsWith(homedir)) {
    result = '~' + result.slice(homedir.length);
  }

  // If path fits, return as-is
  if (result.length <= maxLen) {
    return result;
  }

  // Split into segments
  const segments = result.split('/').filter(s => s.length > 0);

  // Handle edge cases
  if (segments.length === 0) {
    return '/';
  }

  if (segments.length === 1) {
    // Single segment (e.g., "~" or "file.txt")
    return result.length <= maxLen ? result : result.slice(0, maxLen);
  }

  if (segments.length === 2) {
    // Two segments, can't truncate middle
    const prefix = result.startsWith('~') ? '~' : '';
    const twoSegPath = prefix + '/' + segments.join('/');
    return twoSegPath.length <= maxLen ? twoSegPath : twoSegPath.slice(0, maxLen);
  }

  // Three or more segments: keep first and last 2, truncate middle
  const prefix = result.startsWith('~') ? '~' : '';
  const first = segments[0];
  const lastTwo = segments.slice(-2);

  // Build shortened path: prefix/first/.../lastTwo[0]/lastTwo[1]
  const parts = [prefix, first, '...', ...lastTwo];
  const shortened = parts.filter(p => p).join('/');

  // If still too long, we've done our best
  return shortened.length <= maxLen ? shortened : shortened.slice(0, maxLen);
}

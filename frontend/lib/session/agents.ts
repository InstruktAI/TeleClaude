/**
 * Agent availability checking.
 *
 * Queries the daemon for agent availability status and provides utilities
 * for filtering available agents and selecting defaults.
 *
 * Implements simple caching (30s stale-while-revalidate) to reduce API calls.
 */

import { TelecAPIClient, APIError } from "@/lib/api/client.js";
import type { AgentName, AgentAvailabilityInfo } from "@/lib/api/types.js";

// ---------------------------------------------------------------------------
// Cache
// ---------------------------------------------------------------------------

interface CacheEntry {
  data: Record<AgentName, AgentAvailabilityInfo>;
  timestamp: number;
}

const CACHE_TTL_MS = 30_000; // 30 seconds
let cache: CacheEntry | null = null;

/**
 * Clear the agent availability cache.
 * Useful for forcing a fresh fetch after status changes.
 */
export function clearAgentCache(): void {
  cache = null;
}

// ---------------------------------------------------------------------------
// Fetching
// ---------------------------------------------------------------------------

/**
 * Get agent availability status from daemon.
 *
 * Results are cached for 30 seconds to reduce API load.
 *
 * @returns Map of agent name to availability info
 * @throws APIError if daemon is unreachable
 */
export async function checkAgentAvailability(): Promise<
  Record<AgentName, AgentAvailabilityInfo>
> {
  const now = Date.now();

  // Return cached data if still fresh
  if (cache && now - cache.timestamp < CACHE_TTL_MS) {
    return cache.data;
  }

  // Fetch fresh data
  const client = new TelecAPIClient();
  try {
    const data = await client.getAgentAvailability();

    // Update cache
    cache = {
      data,
      timestamp: now,
    };

    return data;
  } catch (err) {
    // If we have stale cache and fetch fails, return stale data
    if (cache) {
      return cache.data;
    }

    // No cache, propagate error
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Availability Checks
// ---------------------------------------------------------------------------

/**
 * Check if an agent can accept new sessions.
 *
 * An agent is available if:
 * - `available` field is true, OR
 * - `status` field is "available"
 *
 * @param availability Agent availability info
 * @returns True if agent can accept sessions
 */
export function isAgentAvailable(availability: AgentAvailabilityInfo): boolean {
  // Primary check: explicit 'available' field
  if (availability.available === true) {
    return true;
  }

  // Fallback: check status field
  if (availability.status === "available") {
    return true;
  }

  // All other cases: unavailable
  return false;
}

/**
 * Filter to only available agents.
 *
 * @param all Map of all agent availability info
 * @returns Array of agent names that are available
 */
export function getAvailableAgents(
  all: Record<AgentName, AgentAvailabilityInfo>,
): AgentName[] {
  const available: AgentName[] = [];

  for (const [name, info] of Object.entries(all)) {
    if (isAgentAvailable(info)) {
      available.push(name as AgentName);
    }
  }

  return available;
}

/**
 * Get default agent to select in UI.
 *
 * Preference order:
 * 1. 'claude' if available
 * 2. First available agent (alphabetical)
 * 3. null if no agents available
 *
 * @param all Map of all agent availability info
 * @returns Default agent name or null
 */
export function getDefaultAgent(
  all: Record<AgentName, AgentAvailabilityInfo>,
): AgentName | null {
  const available = getAvailableAgents(all);

  if (available.length === 0) {
    return null;
  }

  // Prefer 'claude' if available
  if (available.includes("claude")) {
    return "claude";
  }

  // Return first available (alphabetical)
  return available.sort()[0];
}

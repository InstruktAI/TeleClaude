import type { AgentActivityEvent } from '@/lib/api/types';

const DEFAULT_TIMEOUT_MS = 5_000;

interface ActivityState {
  type: string;
  timer: ReturnType<typeof setTimeout>;
}

export interface ActivityTrackerOptions {
  timeoutMs?: number;
}

export interface ActivityTracker {
  handleEvent(event: AgentActivityEvent): void;
  isActive(sessionId: string): boolean;
  getActivityType(sessionId: string): string | undefined;
  clear(sessionId: string): void;
  clearAll(): void;
}

export function createActivityTracker(options?: ActivityTrackerOptions): ActivityTracker {
  const timeoutMs = options?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const sessions = new Map<string, ActivityState>();

  function expire(sessionId: string): void {
    sessions.delete(sessionId);
  }

  return {
    handleEvent(event: AgentActivityEvent): void {
      const existing = sessions.get(event.session_id);
      if (existing) clearTimeout(existing.timer);

      sessions.set(event.session_id, {
        type: event.type,
        timer: setTimeout(() => expire(event.session_id), timeoutMs),
      });
    },

    isActive(sessionId: string): boolean {
      return sessions.has(sessionId);
    },

    getActivityType(sessionId: string): string | undefined {
      return sessions.get(sessionId)?.type;
    },

    clear(sessionId: string): void {
      const existing = sessions.get(sessionId);
      if (existing) {
        clearTimeout(existing.timer);
        sessions.delete(sessionId);
      }
    },

    clearAll(): void {
      for (const [, state] of sessions) {
        clearTimeout(state.timer);
      }
      sessions.clear();
    },
  };
}

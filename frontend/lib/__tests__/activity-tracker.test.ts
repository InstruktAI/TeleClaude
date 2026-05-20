/**
 * Test specifications for session activity tracker.
 *
 * Behavioral contract: createActivityTracker returns a tracker that manages
 * per-session activity state from WebSocket agent_activity events, with
 * configurable timeout-based expiry.
 *
 * All tests are marked as expected failures (it.fails) until implementation exists.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { AgentActivityEvent } from '@/lib/api/types';

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function makeActivityEvent(overrides?: Partial<AgentActivityEvent>): AgentActivityEvent {
  const base = {
    event: 'agent_activity' as const,
    session_id: 'sess-1',
    timestamp: new Date().toISOString(),
  };
  const type = overrides?.type ?? 'tool_use';

  if (type === 'user_prompt_submit') {
    return {
      ...base,
      type: 'user_prompt_submit',
      ...overrides,
    } as AgentActivityEvent;
  }

  return {
    ...base,
    type: 'tool_use',
    tool_name: 'shell',
    tool_preview: 'shell: ls',
    ...overrides,
  } as AgentActivityEvent;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ActivityTracker', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // --- Initial state ---

  describe('initial state', () => {
    it('reports no session as active initially', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      expect(tracker.isActive('sess-1')).toBe(false);
    });

    it('returns undefined activity type for unknown session', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      expect(tracker.getActivityType('sess-1')).toBeUndefined();
    });
  });

  // --- Event handling ---

  describe('event handling', () => {
    it('marks session as active after handling event', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));
      expect(tracker.isActive('sess-1')).toBe(true);
    });

    it('stores activity type from event', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1', type: 'tool_use' }));
      expect(tracker.getActivityType('sess-1')).toBe('tool_use');
    });

    it('updates activity type when new event arrives', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1', type: 'tool_use' }));
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1', type: 'agent_stop' }));
      expect(tracker.getActivityType('sess-1')).toBe('agent_stop');
    });

    it('does not affect other sessions when handling event', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));
      expect(tracker.isActive('sess-2')).toBe(false);
    });
  });

  // --- Timeout expiry ---

  describe('timeout expiry', () => {
    it('expires activity after default timeout', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));
      expect(tracker.isActive('sess-1')).toBe(true);

      vi.advanceTimersByTime(5_001);
      expect(tracker.isActive('sess-1')).toBe(false);
    });

    it('respects custom timeout', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker({ timeoutMs: 10_000 });
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));

      vi.advanceTimersByTime(9_999);
      expect(tracker.isActive('sess-1')).toBe(true);

      vi.advanceTimersByTime(2);
      expect(tracker.isActive('sess-1')).toBe(false);
    });

    it('extends activity window when new event arrives before timeout', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker({ timeoutMs: 5_000 });
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));

      vi.advanceTimersByTime(4_000); // 4s in, still active
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));

      vi.advanceTimersByTime(4_000); // 4s after refresh (8s total)
      expect(tracker.isActive('sess-1')).toBe(true);

      vi.advanceTimersByTime(1_001); // past timeout from last event
      expect(tracker.isActive('sess-1')).toBe(false);
    });

    it('clears activity type after timeout', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker({ timeoutMs: 5_000 });
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1', type: 'tool_use' }));

      vi.advanceTimersByTime(5_001);
      expect(tracker.getActivityType('sess-1')).toBeUndefined();
    });
  });

  // --- Independence per session ---

  describe('session independence', () => {
    it('tracks multiple sessions independently', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker({ timeoutMs: 5_000 });
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));

      vi.advanceTimersByTime(3_000);
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-2' }));

      vi.advanceTimersByTime(2_001); // sess-1 expired (5s+), sess-2 still active (2s)
      expect(tracker.isActive('sess-1')).toBe(false);
      expect(tracker.isActive('sess-2')).toBe(true);
    });

    it('different sessions can have different activity types', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1', type: 'tool_use' }));
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-2', type: 'agent_stop' }));
      expect(tracker.getActivityType('sess-1')).toBe('tool_use');
      expect(tracker.getActivityType('sess-2')).toBe('agent_stop');
    });
  });

  // --- Clear operations ---

  describe('clear operations', () => {
    it('clears single session activity', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-2' }));

      tracker.clear('sess-1');
      expect(tracker.isActive('sess-1')).toBe(false);
      expect(tracker.getActivityType('sess-1')).toBeUndefined();
      // Other session unaffected
      expect(tracker.isActive('sess-2')).toBe(true);
    });

    it('clears all session activities', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-1' }));
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-2' }));
      tracker.handleEvent(makeActivityEvent({ session_id: 'sess-3' }));

      tracker.clearAll();
      expect(tracker.isActive('sess-1')).toBe(false);
      expect(tracker.isActive('sess-2')).toBe(false);
      expect(tracker.isActive('sess-3')).toBe(false);
    });

    it('clear on unknown session does not throw', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      expect(() => tracker.clear('nonexistent')).not.toThrow();
    });

    it('clearAll on empty tracker does not throw', async () => {
      const { createActivityTracker } = await import('@/lib/sessions/activity');
      const tracker = createActivityTracker();
      expect(() => tracker.clearAll()).not.toThrow();
    });
  });
});

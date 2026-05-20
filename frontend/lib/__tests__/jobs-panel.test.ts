/**
 * Test specifications for the jobs panel.
 *
 * Behavioral contract: jobs are split into scheduled and one-shot sections,
 * expose the daemon job metadata needed by the UI, support cursor navigation,
 * and trigger the focused job through the admin proxy route.
 *
 * All tests are marked as expected failures (it.fails) until implementation exists.
 */

import { describe, expect, it } from 'vitest';

interface JobInfo {
  name: string;
  type: 'agent' | 'script';
  schedule: string | null;
  last_run: string | null;
  status: string;
}

function makeJob(overrides?: Partial<JobInfo>): JobInfo {
  return {
    name: 'nightly-sync',
    type: 'script',
    schedule: '0 2 * * *',
    last_run: '2025-01-15T02:00:00Z',
    status: 'idle',
    ...overrides,
  };
}

describe('buildJobsSections', () => {
  it('splits jobs into scheduled and one-shot sections', async () => {
    const modulePath = '@/lib/jobs/panel' as string;
    const { buildJobsSections } = await import(modulePath);

    const sections = buildJobsSections([
      makeJob({ name: 'nightly-sync', schedule: '0 2 * * *' }),
      makeJob({ name: 'manual-backfill', schedule: null, type: 'agent' }),
    ]);

    expect(sections).toEqual({
      scheduled: [
        {
          name: 'nightly-sync',
          type: 'script',
          scheduleLabel: '0 2 * * *',
          lastRun: '2025-01-15T02:00:00Z',
          status: 'idle',
        },
      ],
      oneShot: [
        {
          name: 'manual-backfill',
          type: 'agent',
          scheduleLabel: 'one-shot',
          lastRun: '2025-01-15T02:00:00Z',
          status: 'idle',
        },
      ],
    });
  });
});

describe('buildJobTriggerRequest', () => {
  it('formats the selected job for the trigger proxy call', async () => {
    const modulePath = '@/lib/jobs/panel' as string;
    const { buildJobTriggerRequest } = await import(modulePath);

    expect(buildJobTriggerRequest('nightly-sync')).toEqual({
      method: 'POST',
      path: '/api/jobs/nightly-sync/run',
    });
  });
});

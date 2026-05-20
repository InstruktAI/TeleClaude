'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useJobs } from '@/lib/hooks/useJobs';
import { buildJobsSections, buildJobTriggerRequest, type JobsPanelRow } from '@/lib/jobs/panel';
import { findBinding } from '@/lib/keys/bindings';
import { toast } from '@/lib/hooks/useToast';
import { cn } from '@/lib/utils';

function JobRow({ row, isCursor, onClick }: { row: JobsPanelRow; isCursor: boolean; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-center gap-3 px-4 py-1.5 text-sm cursor-pointer',
        isCursor ? 'bg-accent text-accent-foreground' : 'hover:bg-muted/50',
      )}
    >
      <span className="font-medium min-w-[140px]">{row.name}</span>
      <span
        className={cn(
          'rounded px-1.5 py-0.5 text-[10px] font-medium',
          row.type === 'agent' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
        )}
      >
        {row.type}
      </span>
      <span className="text-muted-foreground min-w-[100px]">{row.scheduleLabel}</span>
      {row.lastRun && <span className="text-muted-foreground text-xs">{row.lastRun}</span>}
      {row.status && (
        <span className={cn('text-xs', row.status === 'running' ? 'text-primary' : 'text-muted-foreground')}>
          {row.status}
        </span>
      )}
    </div>
  );
}

function SectionHeader({ label }: { label: string }) {
  return <div className="px-4 py-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</div>;
}

interface JobsViewProps {
  isActive?: boolean;
}

export function JobsView({ isActive = true }: JobsViewProps) {
  const { data: jobs, isLoading } = useJobs();
  const [cursorIndex, setCursorIndex] = useState(0);

  const sections = useMemo(() => (jobs ? buildJobsSections(jobs) : { scheduled: [], oneShot: [] }), [jobs]);
  const allRows = useMemo(() => [...sections.scheduled, ...sections.oneShot], [sections]);
  const clampedCursor = Math.min(cursorIndex, Math.max(allRows.length - 1, 0));

  const triggerJob = useCallback(async (name: string) => {
    const req = buildJobTriggerRequest(name);
    try {
      const res = await fetch(req.path, { method: req.method });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { error?: string }).error ?? `HTTP ${res.status}`);
      }
      toast({
        title: 'Job triggered',
        description: name,
        variant: 'success',
      });
    } catch (err) {
      toast({
        title: 'Trigger failed',
        description: err instanceof Error ? err.message : 'Unknown error',
        variant: 'destructive',
      });
    }
  }, []);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isActive) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const binding = findBinding(e.key, { ctrl: e.ctrlKey, shift: e.shiftKey, meta: e.metaKey }, 'jobs');
      if (!binding) return;

      switch (binding.action) {
        case 'navigate_up':
          e.preventDefault();
          setCursorIndex((prev) => Math.max(prev - 1, 0));
          break;
        case 'navigate_down':
          e.preventDefault();
          setCursorIndex((prev) => Math.min(prev + 1, allRows.length - 1));
          break;
        case 'run_job': {
          e.preventDefault();
          const row = allRows[clampedCursor];
          if (row) {
            triggerJob(row.name);
          }
          break;
        }
        default:
          break;
      }
    },
    [isActive, allRows, clampedCursor, triggerJob],
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-muted-foreground">Loading jobs...</p>
      </div>
    );
  }

  if (!jobs || allRows.length === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-muted-foreground">No jobs configured</p>
      </div>
    );
  }

  let globalIndex = 0;

  return (
    <div className="py-1">
      {sections.scheduled.length > 0 && (
        <>
          <SectionHeader label="Scheduled Jobs" />
          {sections.scheduled.map((row) => {
            const idx = globalIndex++;
            return (
              <JobRow
                key={row.name}
                row={row}
                isCursor={idx === clampedCursor}
                onClick={() => {
                  setCursorIndex(idx);
                  triggerJob(row.name);
                }}
              />
            );
          })}
        </>
      )}
      {sections.oneShot.length > 0 && (
        <>
          <SectionHeader label="One-shot Jobs" />
          {sections.oneShot.map((row) => {
            const idx = globalIndex++;
            return (
              <JobRow
                key={row.name}
                row={row}
                isCursor={idx === clampedCursor}
                onClick={() => {
                  setCursorIndex(idx);
                  triggerJob(row.name);
                }}
              />
            );
          })}
        </>
      )}
    </div>
  );
}

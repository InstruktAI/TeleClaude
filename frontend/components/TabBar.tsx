'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export type TabValue = 'sessions' | 'preparation' | 'configuration' | 'jobs';

interface TabBarProps {
  value: TabValue;
  onValueChange: (value: TabValue) => void;
  sessionsContent: ReactNode;
  preparationContent: ReactNode;
  configurationContent: ReactNode;
  jobsContent: ReactNode;
}

const TABS: Array<{ value: TabValue; label: string; shortcut: string }> = [
  { value: 'sessions', label: 'Sessions', shortcut: '1' },
  { value: 'preparation', label: 'Preparation', shortcut: '2' },
  { value: 'configuration', label: 'Configuration', shortcut: '3' },
  { value: 'jobs', label: 'Jobs', shortcut: '4' },
];

export function TabBar({
  value,
  onValueChange,
  sessionsContent,
  preparationContent,
  configurationContent,
  jobsContent,
}: TabBarProps) {
  const contentByTab: Record<TabValue, ReactNode> = {
    sessions: sessionsContent,
    preparation: preparationContent,
    configuration: configurationContent,
    jobs: jobsContent,
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex border-b px-4" role="tablist">
        {TABS.map((tab) => (
          <button
            key={tab.value}
            role="tab"
            type="button"
            aria-selected={value === tab.value}
            data-state={value === tab.value ? 'active' : 'inactive'}
            onClick={() => onValueChange(tab.value)}
            className={cn(
              'relative flex items-center gap-1.5 px-3 py-2 text-sm font-medium transition-colors',
              value === tab.value ? 'text-foreground' : 'text-muted-foreground hover:text-foreground/80',
            )}
          >
            {tab.label}
            <span className="text-[10px] text-muted-foreground/60">{tab.shortcut}</span>
            {value === tab.value && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />}
          </button>
        ))}
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {TABS.map((tab) => (
          <div
            key={tab.value}
            role="tabpanel"
            className={cn('absolute inset-0', tab.value === 'sessions' ? 'overflow-hidden' : 'overflow-auto')}
            style={{ display: value === tab.value ? 'block' : 'none' }}
          >
            {contentByTab[tab.value]}
          </div>
        ))}
      </div>
    </div>
  );
}

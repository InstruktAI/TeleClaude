'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSession } from 'next-auth/react';
import { useSettings } from '@/lib/hooks/useSettings';
import { usePeople } from '@/lib/hooks/usePeople';
import {
  resolveConfigurationAccess,
  getConfigurationSubtabs,
  buildEnvironmentEntries,
  type ConfigurationSubtabId,
} from '@/lib/configuration/panel';
import { findBinding } from '@/lib/keys/bindings';
import type { HumanRole } from '@/lib/api/types';
import { cn } from '@/lib/utils';

function AdaptersTab() {
  const { data: settings } = useSettings();

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="rounded border px-1.5 py-0.5">Read-only</span>
        <span>Edit via CLI</span>
      </div>
      {settings ? (
        <div className="space-y-1">
          {Object.entries(settings).map(([key, value]) => (
            <div key={key} className="flex items-center gap-2 text-sm">
              <span className="font-mono text-muted-foreground">{key}</span>
              <span className="text-foreground">{JSON.stringify(value)}</span>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Loading settings...</p>
      )}
    </div>
  );
}

function PeopleTab() {
  const { data: people, isLoading } = usePeople();

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading people...</p>;
  }

  if (!people || people.length === 0) {
    return <p className="text-sm text-muted-foreground">No people found</p>;
  }

  return (
    <div className="space-y-1">
      {people.map((person) => (
        <div key={person.email ?? person.name} className="flex items-center gap-3 py-1 text-sm">
          <span className="font-medium">{person.name}</span>
          {person.email && <span className="text-muted-foreground">{person.email}</span>}
          <span
            className={cn(
              'rounded px-1.5 py-0.5 text-[10px] font-medium',
              person.role === 'admin' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
            )}
          >
            {person.role}
          </span>
        </div>
      ))}
    </div>
  );
}

function NotificationsTab() {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="rounded border px-1.5 py-0.5">Read-only</span>
        <span>Edit via CLI</span>
      </div>
      <p className="text-sm text-muted-foreground">
        Notification configuration — edit via CLI (<code>telec config notify</code>)
      </p>
    </div>
  );
}

function EnvironmentTab() {
  const [revealedKeys, setRevealedKeys] = useState<string[]>([]);

  const envVars: Record<string, string> = {};
  const entries = buildEnvironmentEntries(envVars, { revealedKeys });

  if (entries.length === 0) {
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="rounded border px-1.5 py-0.5">Read-only</span>
        </div>
        <p className="text-sm text-muted-foreground">
          Environment variables not available via daemon API. Use CLI: <code>telec config env list</code>
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {entries.map((entry) => (
        <div
          key={entry.key}
          className="flex items-center gap-2 py-1 text-sm cursor-pointer"
          onClick={() => {
            if (entry.masked) {
              setRevealedKeys((prev) => [...prev, entry.key]);
            } else {
              setRevealedKeys((prev) => prev.filter((k) => k !== entry.key));
            }
          }}
        >
          <span className="font-mono text-muted-foreground">{entry.key}</span>
          <span className={entry.masked ? 'text-muted-foreground' : 'text-foreground'}>{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

function ValidateTab() {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="rounded border px-1.5 py-0.5">CLI only</span>
      </div>
      <p className="text-sm text-muted-foreground">
        Config validation available via CLI: <code>telec config validate</code>
      </p>
    </div>
  );
}

const SUBTAB_COMPONENTS: Record<ConfigurationSubtabId, React.ComponentType> = {
  adapters: AdaptersTab,
  people: PeopleTab,
  notifications: NotificationsTab,
  environment: EnvironmentTab,
  validate: ValidateTab,
};

interface ConfigViewProps {
  isActive?: boolean;
}

export function ConfigView({ isActive = true }: ConfigViewProps) {
  const { data: session } = useSession();
  const role = (session?.user?.role ?? 'member') as HumanRole;
  const access = resolveConfigurationAccess(role);
  const subtabs = useMemo(() => getConfigurationSubtabs(), []);
  const [activeSubtabIndex, setActiveSubtabIndex] = useState(0);

  const activeSubtab = subtabs[activeSubtabIndex];
  const ActiveComponent = activeSubtab ? SUBTAB_COMPONENTS[activeSubtab.id] : null;

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!isActive) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const binding = findBinding(e.key, { ctrl: e.ctrlKey, shift: e.shiftKey, meta: e.metaKey }, 'configuration');
      if (!binding) return;

      switch (binding.action) {
        case 'next_subtab':
        case 'next_tab':
          e.preventDefault();
          setActiveSubtabIndex((prev) => (prev + 1) % subtabs.length);
          break;
        case 'prev_subtab':
        case 'prev_tab':
          e.preventDefault();
          setActiveSubtabIndex((prev) => (prev - 1 + subtabs.length) % subtabs.length);
          break;
        case 'navigate_up':
        case 'navigate_down':
        case 'select_item':
          e.preventDefault();
          break;
        default:
          break;
      }
    },
    [isActive, subtabs.length],
  );

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  if (!access.canOpen) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">Admin access required</p>
          <p className="mt-1 text-xs text-muted-foreground">Configuration is restricted to admin users</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex border-b px-4" role="tablist">
        {subtabs.map((tab, index) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={index === activeSubtabIndex}
            onClick={() => setActiveSubtabIndex(index)}
            className={cn(
              'relative px-3 py-2 text-sm font-medium transition-colors',
              index === activeSubtabIndex ? 'text-foreground' : 'text-muted-foreground hover:text-foreground/80',
            )}
          >
            {tab.label}
            {index === activeSubtabIndex && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary" />}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-auto p-4">{ActiveComponent && <ActiveComponent />}</div>
    </div>
  );
}

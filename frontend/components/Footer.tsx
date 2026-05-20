'use client';

import { useMemo } from 'react';
import type { AgentAvailabilityInfo, AgentName } from '@/lib/api/types';
import { useLiveAgentAvailability } from '@/lib/hooks/useLiveAgentAvailability';
import { getFooterRows } from '@/lib/keys/footer-contract';
import type { FooterContext } from '@/lib/keys/footer-contract';

export interface FooterProps {
  context: FooterContext;
  selectedNodeType?: 'computer' | 'project' | 'session' | null;
}

const AGENT_ORDER: AgentName[] = ['claude', 'gemini', 'codex'];

function formatCountdown(until?: string | null): string {
  if (!until) return '?';
  const date = new Date(until);
  if (Number.isNaN(date.getTime())) return '?';

  const remainingMs = date.getTime() - Date.now();
  if (remainingMs <= 0) return 'soon';

  const totalSeconds = Math.floor(remainingMs / 1000);
  const days = Math.floor(totalSeconds / 86_400);
  const hours = Math.floor((totalSeconds % 86_400) / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function agentText(info?: AgentAvailabilityInfo): string | null {
  if (!info) return null;

  if (info.status === 'degraded' || info.reason?.startsWith('degraded')) {
    return `${info.agent} ~`;
  }

  if (info.available === true || info.status === 'available') {
    return `${info.agent} ✔`;
  }

  return `${info.agent} ✘(${formatCountdown(info.unavailable_until)})`;
}

function agentColor(info?: AgentAvailabilityInfo): string {
  const fallback = 'var(--tc-text-muted)';
  if (!info) return fallback;
  const token = info.status === 'available' || info.available === true ? 'normal' : 'muted';
  return `var(--tc-agent-${info.agent}-${token})`;
}

export function Footer({ context, selectedNodeType }: FooterProps) {
  const { data: availability } = useLiveAgentAvailability();
  const { contextHints, globalHints } = useMemo(() => {
    return getFooterRows(context, selectedNodeType);
  }, [context, selectedNodeType]);

  return (
    <div className="flex flex-col gap-1 px-1 text-[10px]">
      <div data-testid="footer-context-row" className="flex flex-wrap gap-2">
        {contextHints.map((hint, index) => (
          <div key={`${hint.action}-${index}`} data-testid="footer-hint" className="flex items-center gap-1">
            <kbd className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{hint.key}</kbd>
            <span className="text-muted-foreground">{hint.description}</span>
          </div>
        ))}
      </div>
      <div data-testid="footer-global-row" className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {globalHints.map((hint, index) => (
            <div key={`${hint.action}-${index}`} data-testid="footer-hint" className="flex items-center gap-1">
              <kbd className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{hint.key}</kbd>
              <span className="text-muted-foreground">{hint.description}</span>
            </div>
          ))}
        </div>
        <div data-testid="footer-agent-statuses" className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {AGENT_ORDER.map((agent) => {
            const info = availability[agent];
            const text = agentText(info);
            if (!text) return null;

            return (
              <span
                key={agent}
                data-testid={`footer-agent-${agent}`}
                className="font-mono text-[10px]"
                style={{ color: agentColor(info) }}
              >
                {text}
              </span>
            );
          })}
        </div>
      </div>
    </div>
  );
}

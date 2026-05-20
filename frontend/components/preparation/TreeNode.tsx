'use client';

import { ChevronRight, ChevronDown, File, Monitor, Package } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { TodoInfo } from '@/lib/api/types';
import {
  deriveTodoPhaseTags,
  getPhaseTagColor,
  getTodoStatusBlock,
  type PhaseTagColor,
  type TodoStatusBlock,
} from '@/lib/preparation/tree';

type NodeType = 'computer' | 'project' | 'todo' | 'file' | 'group';

interface TreeNodeProps {
  label: string;
  type: NodeType;
  depth: number;
  expanded: boolean;
  hasChildren: boolean;
  isCursor: boolean;
  todo?: TodoInfo;
  computerStatus?: string;
  slugColWidth?: number;
  onToggle: () => void;
}

const PHASE_COLOR_CLASS: Record<PhaseTagColor, string> = {
  green: 'text-green-600 dark:text-green-400',
  gold: 'text-amber-600 dark:text-amber-400',
  red: 'text-red-600 dark:text-red-400',
  gray: 'text-muted-foreground',
};

const BLOCK_COLOR_CLASS: Record<TodoStatusBlock['color'], string> = {
  green: 'text-green-600 dark:text-green-400',
  gold: 'text-amber-600 dark:text-amber-400',
  gray: 'text-muted-foreground',
};

function StatusBlock({ block }: { block: TodoStatusBlock }) {
  return (
    <span
      data-testid="status-block"
      data-color={block.color}
      data-filled={String(block.filled)}
      className={cn('inline-block w-3 text-center font-mono text-[10px]', BLOCK_COLOR_CLASS[block.color])}
    >
      {block.filled ? '█' : '□'}
    </span>
  );
}

function PhaseIndicator({ tag }: { tag: string }) {
  const value = tag.includes(':') ? tag.slice(tag.indexOf(':') + 1) : tag;
  const color = getPhaseTagColor(value);
  return (
    <span
      data-testid="phase-indicator"
      data-color={color}
      data-tag={tag}
      className={cn('text-[10px] font-mono', PHASE_COLOR_CLASS[color])}
    >
      {tag}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-500/20 text-yellow-700 dark:text-yellow-300',
    icebox: 'bg-blue-500/20 text-blue-700 dark:text-blue-300',
    delivered: 'bg-green-500/20 text-green-700 dark:text-green-300',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium',
        colors[status] ?? 'bg-muted text-muted-foreground',
      )}
    >
      {status}
    </span>
  );
}

const ICONS: Record<NodeType, typeof Monitor> = {
  computer: Monitor,
  project: Package,
  group: Package,
  todo: Package,
  file: File,
};

export function TreeNode({
  label,
  type,
  depth,
  expanded,
  hasChildren,
  isCursor,
  todo,
  computerStatus,
  slugColWidth,
  onToggle,
}: TreeNodeProps) {
  const Icon = ICONS[type];
  const phaseTags = todo ? deriveTodoPhaseTags(todo) : [];
  const statusBlock = todo ? getTodoStatusBlock(todo) : null;

  return (
    <div
      data-testid={type === 'todo' ? 'preparation-todo-node' : undefined}
      data-slug={type === 'todo' && todo ? todo.slug : undefined}
      data-slug-col-width={type === 'todo' && slugColWidth !== undefined ? String(slugColWidth) : undefined}
      className={cn(
        'flex items-center gap-1 py-0.5 px-2 cursor-pointer select-none text-sm',
        isCursor && 'bg-accent text-accent-foreground',
      )}
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
      onClick={onToggle}
    >
      {hasChildren ? (
        expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )
      ) : (
        <span className="w-3.5 shrink-0" />
      )}
      {type === 'todo' && statusBlock ? (
        <StatusBlock block={statusBlock} />
      ) : (
        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      )}
      <span
        className="truncate"
        style={type === 'todo' && slugColWidth !== undefined ? { minWidth: `${slugColWidth}ch` } : undefined}
      >
        {label}
      </span>

      {type === 'computer' && computerStatus && (
        <span
          className={cn(
            'ml-1 h-1.5 w-1.5 rounded-full shrink-0',
            computerStatus === 'online' ? 'bg-green-500' : 'bg-muted-foreground',
          )}
        />
      )}

      {type === 'todo' && todo && (
        <div className="flex items-center gap-1 ml-auto shrink-0">
          <StatusBadge status={todo.status} />
          {phaseTags.map((tag) => (
            <PhaseIndicator key={tag} tag={tag} />
          ))}
        </div>
      )}
    </div>
  );
}

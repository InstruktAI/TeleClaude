"use client";

import { ChevronRight, ChevronDown, File, Folder, Monitor, Package } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TodoInfo } from "@/lib/api/types";
import { deriveTodoPhaseTags } from "@/lib/preparation/tree";

type NodeType = "computer" | "project" | "todo" | "file";

interface TreeNodeProps {
  label: string;
  type: NodeType;
  depth: number;
  expanded: boolean;
  hasChildren: boolean;
  isCursor: boolean;
  todo?: TodoInfo;
  computerStatus?: string;
  onToggle: () => void;
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-yellow-500/20 text-yellow-700 dark:text-yellow-300",
    icebox: "bg-blue-500/20 text-blue-700 dark:text-blue-300",
    delivered: "bg-green-500/20 text-green-700 dark:text-green-300",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium",
        colors[status] ?? "bg-muted text-muted-foreground",
      )}
    >
      {status}
    </span>
  );
}

function PhaseTag({ tag }: { tag: string }) {
  const colors: Record<string, string> = {
    B: "text-blue-600 dark:text-blue-400",
    R: "text-purple-600 dark:text-purple-400",
    DOR: "text-orange-600 dark:text-orange-400",
    DEF: "text-red-600 dark:text-red-400",
    F: "text-amber-600 dark:text-amber-400",
  };

  return (
    <span className={cn("text-[10px] font-bold", colors[tag] ?? "text-muted-foreground")}>
      {tag}
    </span>
  );
}

const ICONS: Record<NodeType, typeof Monitor> = {
  computer: Monitor,
  project: Package,
  todo: Folder,
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
  onToggle,
}: TreeNodeProps) {
  const Icon = ICONS[type];
  const phaseTags = todo ? deriveTodoPhaseTags(todo) : [];

  return (
    <div
      className={cn(
        "flex items-center gap-1 py-0.5 px-2 cursor-pointer select-none text-sm",
        isCursor && "bg-accent text-accent-foreground",
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
      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span className="truncate">{label}</span>

      {type === "computer" && computerStatus && (
        <span
          className={cn(
            "ml-1 h-1.5 w-1.5 rounded-full shrink-0",
            computerStatus === "online" ? "bg-green-500" : "bg-muted-foreground",
          )}
        />
      )}

      {type === "todo" && todo && (
        <div className="flex items-center gap-1 ml-auto shrink-0">
          <StatusBadge status={todo.status} />
          {phaseTags.map((tag) => (
            <PhaseTag key={tag} tag={tag} />
          ))}
          {todo.dor_score !== null && todo.dor_score !== undefined && (
            <span className="text-[10px] text-muted-foreground">
              DOR:{todo.dor_score}
            </span>
          )}
          {todo.findings_count > 0 && (
            <span className="text-[10px] text-muted-foreground">
              F:{todo.findings_count}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

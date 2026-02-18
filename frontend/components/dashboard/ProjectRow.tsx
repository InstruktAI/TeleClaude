"use client";

import { Folder } from "lucide-react";

interface Props {
  name: string;
  path: string;
  sessionCount: number;
}

export function ProjectRow({ name, path, sessionCount }: Props) {
  return (
    <div className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm">
      <Folder className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <span className="truncate text-xs font-medium">{name}</span>
        <span className="ml-1 truncate text-[10px] text-muted-foreground">
          {path}
        </span>
      </div>
      <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
        {sessionCount}
      </span>
    </div>
  );
}

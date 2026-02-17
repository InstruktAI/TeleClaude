"use client";

import { FileDown } from "lucide-react";
import type { FileSection as FileSectionType } from "@/lib/widgets";

export function FileSectionRenderer({
  section,
  sessionId,
}: {
  section: FileSectionType;
  sessionId: string;
}) {
  const href = `/data/${sessionId}?file=${encodeURIComponent(section.path)}`;
  const displayLabel = section.label || section.path.split("/").pop() || section.path;

  return (
    <a
      href={href}
      download
      className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-accent/50"
    >
      <FileDown className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="truncate">{displayLabel}</span>
      {section.size != null && (
        <span className="ml-auto text-xs text-muted-foreground">
          {formatBytes(section.size)}
        </span>
      )}
    </a>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

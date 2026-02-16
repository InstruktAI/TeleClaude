"use client";

import { FileIcon } from "lucide-react";
import type { FileMessagePartProps } from "@assistant-ui/react";

export function FileLink({ filename, data, mimeType }: FileMessagePartProps) {
  const displayName = filename ?? "Untitled file";

  return (
    <a
      href={data}
      download={filename}
      className="my-1 inline-flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm hover:bg-accent/50 transition-colors"
    >
      <FileIcon className="h-4 w-4 text-muted-foreground" />
      <span>{displayName}</span>
      {mimeType && (
        <span className="text-xs text-muted-foreground">({mimeType})</span>
      )}
    </a>
  );
}

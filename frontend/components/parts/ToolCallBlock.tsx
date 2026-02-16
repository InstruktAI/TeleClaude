"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { ToolCallMessagePartProps } from "@assistant-ui/react";

export function ToolCallBlock({
  toolName,
  argsText,
  result,
  isError,
  status,
}: ToolCallMessagePartProps) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = status?.type === "running";

  return (
    <div className="my-1 rounded-md border bg-card text-sm">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-accent/50"
        aria-expanded={expanded}
      >
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
        <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-xs font-medium">
          {toolName}
        </span>
        {isRunning && (
          <span className="text-xs text-muted-foreground">running...</span>
        )}
      </button>
      {expanded && (
        <div className="border-t px-3 py-2 space-y-2">
          {argsText && (
            <pre className="overflow-x-auto text-xs font-mono text-muted-foreground whitespace-pre-wrap">
              {argsText}
            </pre>
          )}
          {result !== undefined && (
            <div
              className={`border-t pt-2 text-xs font-mono whitespace-pre-wrap ${
                isError ? "text-destructive" : "text-foreground"
              }`}
            >
              {typeof result === "string"
                ? result
                : JSON.stringify(result, null, 2)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

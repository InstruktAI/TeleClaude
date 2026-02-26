"use client";

import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { ReasoningMessagePartProps } from "@assistant-ui/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "@/styles/highlight-theme.css";

export function ThinkingBlock({ text, status }: ReasoningMessagePartProps) {
  const [expanded, setExpanded] = useState(false);
  const isStreaming = status?.type === "running";

  return (
    <div className="my-1 rounded-md bg-muted/50">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
        aria-expanded={expanded}
      >
        <ChevronRight
          className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
        <span>{isStreaming ? "Thinking..." : "Thought"}</span>
      </button>
      {expanded && (
        <div className="px-3 pb-2 text-xs text-muted-foreground">
          <div className="prose prose-xs dark:prose-invert max-w-none break-words">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
            >
              {text}
            </ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}

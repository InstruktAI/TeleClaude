"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import type { CodeSection as CodeSectionType } from "@/lib/widgets";

export function CodeSectionRenderer({ section }: { section: CodeSectionType }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(section.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative rounded-md border bg-muted/50">
      <div className="flex items-center justify-between border-b px-3 py-1.5">
        <span className="text-xs text-muted-foreground">
          {section.language || "code"}
          {section.title ? ` — ${section.title}` : ""}
        </span>
        <button
          onClick={handleCopy}
          className="text-muted-foreground hover:text-foreground"
          aria-label="Copy code"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-xs">
        <code className={section.language ? `language-${section.language}` : ""}>
          {section.content}
        </code>
      </pre>
    </div>
  );
}

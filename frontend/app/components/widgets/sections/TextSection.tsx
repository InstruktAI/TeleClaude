"use client";

import type { TextSection as TextSectionType } from "@/lib/widgets";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function TextSectionRenderer({ section }: { section: TextSectionType }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {section.content}
      </ReactMarkdown>
    </div>
  );
}

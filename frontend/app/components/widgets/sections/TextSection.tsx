"use client";

import type { TextSection as TextSectionType } from "@/lib/widgets";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";

export function TextSectionRenderer({ section }: { section: TextSectionType }) {
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none">
      <MarkdownTextPrimitive
        remarkPlugins={[remarkGfm]}
        text={section.content}
      />
    </div>
  );
}

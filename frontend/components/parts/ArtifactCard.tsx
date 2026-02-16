"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ArtifactCardProps {
  data: {
    content?: string;
    output_format?: "markdown" | "html";
    caption?: string;
  };
}

export function ArtifactCard({ data }: ArtifactCardProps) {
  const { content, output_format, caption } = data ?? {};

  if (!content) return null;

  return (
    <div className="my-2 rounded-lg border bg-card">
      {caption && (
        <div className="border-b px-4 py-2 text-xs font-medium text-muted-foreground">
          {caption}
        </div>
      )}
      <div className="px-4 py-3">
        {output_format === "html" ? (
          <div
            className="prose prose-sm dark:prose-invert max-w-none"
            dangerouslySetInnerHTML={{ __html: content }}
          />
        ) : (
          <div className="prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

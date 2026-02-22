"use client";

import ReactMarkdown from "react-markdown";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "@/styles/highlight-theme.css";
import type { TextMessagePartProps } from "@assistant-ui/react";

const NOTIFICATION_RE =
  /<task-notification>\s*[\s\S]*?<summary>([\s\S]*?)<\/summary>[\s\S]*?<\/task-notification>/g;
const HOOK_FEEDBACK_RE = /Stop hook feedback:\s*[\s\S]*?(?=\n\n|$)/g;
const CONTEXT_CONTINUATION_RE =
  /This session is being continued from a previous conversation[\s\S]*/;
const SYSTEM_REMINDER_RE = /<system-reminder>[\s\S]*?<\/system-reminder>/g;

const MARKDOWN_COMPONENTS = {
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary underline"
    >
      {children}
    </a>
  ),
};

interface CollapsibleBlockProps {
  label: string;
  content: string;
}

function CollapsibleBlock({ label, content }: CollapsibleBlockProps) {
  return (
    <details className="my-2 rounded border border-border bg-muted/50 text-xs">
      <summary className="cursor-pointer select-none px-3 py-1.5 text-muted-foreground hover:text-foreground">
        {label}
      </summary>
      <pre className="whitespace-pre-wrap px-3 py-2 text-muted-foreground/80 max-h-40 overflow-y-auto">
        {content}
      </pre>
    </details>
  );
}

type Segment =
  | { kind: "text"; text: string }
  | { kind: "notification"; label: string; raw: string }
  | { kind: "system"; label: string; raw: string };

/**
 * Split text into segments: plain text and system-injected blocks.
 */
function splitSystemBlocks(text: string): Segment[] {
  type Match = {
    start: number;
    end: number;
    kind: "notification" | "system";
    label: string;
    raw: string;
  };
  const matches: Match[] = [];

  for (const m of text.matchAll(NOTIFICATION_RE)) {
    matches.push({
      start: m.index!,
      end: m.index! + m[0].length,
      kind: "notification",
      label: m[1].trim(),
      raw: m[0],
    });
  }

  for (const m of text.matchAll(SYSTEM_REMINDER_RE)) {
    matches.push({
      start: m.index!,
      end: m.index! + m[0].length,
      kind: "system",
      label: "System reminder",
      raw: m[0],
    });
  }

  for (const m of text.matchAll(HOOK_FEEDBACK_RE)) {
    matches.push({
      start: m.index!,
      end: m.index! + m[0].length,
      kind: "system",
      label: "Hook feedback",
      raw: m[0],
    });
  }

  const ctxMatch = text.match(CONTEXT_CONTINUATION_RE);
  if (ctxMatch && ctxMatch.index !== undefined) {
    matches.push({
      start: ctxMatch.index,
      end: ctxMatch.index + ctxMatch[0].length,
      kind: "system",
      label: "Context continuation",
      raw: ctxMatch[0],
    });
  }

  if (matches.length === 0) {
    return [{ kind: "text", text }];
  }

  matches.sort((a, b) => a.start - b.start);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const m of matches) {
    if (m.start > cursor) {
      const plain = text.slice(cursor, m.start).trim();
      if (plain) segments.push({ kind: "text", text: plain });
    }
    segments.push({ kind: m.kind, label: m.label, raw: m.raw });
    cursor = m.end;
  }

  if (cursor < text.length) {
    const remaining = text.slice(cursor).trim();
    if (remaining) segments.push({ kind: "text", text: remaining });
  }

  return segments;
}

export function MarkdownContent(props: TextMessagePartProps) {
  const segments = splitSystemBlocks(props.text);

  // Fast path: no system blocks, use the primitive (reads from message context)
  if (segments.length === 1 && segments[0].kind === "text") {
    return (
      <MarkdownTextPrimitive
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        className="prose prose-sm dark:prose-invert max-w-none break-words"
        components={MARKDOWN_COMPONENTS}
      />
    );
  }

  // Mixed content: render text with react-markdown, system blocks as collapsibles
  return (
    <div>
      {segments.map((seg, i) => {
        if (seg.kind === "text") {
          return (
            <div
              key={i}
              className="prose prose-sm dark:prose-invert max-w-none break-words"
            >
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={MARKDOWN_COMPONENTS}
              >
                {seg.text}
              </ReactMarkdown>
            </div>
          );
        }
        return (
          <CollapsibleBlock key={i} label={seg.label} content={seg.raw} />
        );
      })}
    </div>
  );
}

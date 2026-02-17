"use client";

import { makeAssistantToolUI } from "@assistant-ui/react";
import type {
  RenderWidgetArgs,
  RenderWidgetResult,
  Section,
} from "@/lib/widgets";
import { WidgetSkeleton } from "./WidgetSkeleton";
import { TextSectionRenderer } from "./sections/TextSection";
import { InputSectionRenderer } from "./sections/InputSection";
import { ActionsSectionRenderer } from "./sections/ActionsSection";
import { ImageSectionRenderer } from "./sections/ImageSection";
import { TableSectionRenderer } from "./sections/TableSection";
import { FileSectionRenderer } from "./sections/FileSection";
import { CodeSectionRenderer } from "./sections/CodeSection";
import { DividerSectionRenderer } from "./sections/DividerSection";
import { useState } from "react";
import { ChevronRight } from "lucide-react";

const STATUS_STYLES: Record<string, string> = {
  info: "border-blue-500/30 bg-blue-500/5",
  success: "border-green-500/30 bg-green-500/5",
  warning: "border-yellow-500/30 bg-yellow-500/5",
  error: "border-red-500/30 bg-red-500/5",
};

const VARIANT_STYLES: Record<string, string> = {
  info: "border-l-2 border-l-blue-500 pl-3",
  success: "border-l-2 border-l-green-500 pl-3",
  warning: "border-l-2 border-l-yellow-500 pl-3",
  error: "border-l-2 border-l-red-500 pl-3",
  muted: "opacity-60",
};

function SectionRenderer({
  section,
  sessionId,
}: {
  section: Section;
  sessionId: string;
}) {
  const variantClass = section.variant ? VARIANT_STYLES[section.variant] || "" : "";

  return (
    <div className={variantClass}>
      {section.label && (
        <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {section.label}
        </p>
      )}
      <SectionContent section={section} sessionId={sessionId} />
    </div>
  );
}

function SectionContent({
  section,
  sessionId,
}: {
  section: Section;
  sessionId: string;
}) {
  switch (section.type) {
    case "text":
      return <TextSectionRenderer section={section} />;
    case "input":
      return <InputSectionRenderer section={section} />;
    case "actions":
      return <ActionsSectionRenderer section={section} />;
    case "image":
      return <ImageSectionRenderer section={section} sessionId={sessionId} />;
    case "table":
      return <TableSectionRenderer section={section} />;
    case "file":
      return <FileSectionRenderer section={section} sessionId={sessionId} />;
    case "code":
      return <CodeSectionRenderer section={section} />;
    case "divider":
      return <DividerSectionRenderer />;
    default:
      return <UnknownSection section={section} />;
  }
}

function UnknownSection({ section }: { section: Section }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-md border bg-muted/50 text-xs">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-accent/50"
      >
        <ChevronRight
          className={`h-3 w-3 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
        <span className="text-muted-foreground">
          Unknown section: {(section as { type: string }).type}
        </span>
      </button>
      {expanded && (
        <pre className="border-t px-3 py-2 overflow-x-auto whitespace-pre-wrap">
          {JSON.stringify(section, null, 2)}
        </pre>
      )}
    </div>
  );
}

export const RenderWidgetUI = makeAssistantToolUI<
  RenderWidgetArgs,
  RenderWidgetResult
>({
  toolName: "teleclaude__render_widget",
  render: ({ args, status }) => {
    if (status.type === "running" && !args) {
      return <WidgetSkeleton />;
    }

    const data = args?.data;
    if (!data?.sections) {
      return <WidgetSkeleton />;
    }

    // Extract session ID from the tool call args (it's a sibling of data in the MCP call)
    // The session ID is embedded in the current URL path for the web interface
    const sessionId = extractSessionId();
    const statusClass = data.status ? STATUS_STYLES[data.status] || "" : "";

    return (
      <div className={`my-2 rounded-lg border p-4 space-y-3 ${statusClass}`}>
        {data.title && (
          <h3 className="text-sm font-semibold">{data.title}</h3>
        )}
        {data.sections.map((section, idx) => (
          <SectionRenderer
            key={section.id || idx}
            section={section}
            sessionId={sessionId}
          />
        ))}
        {data.footer && (
          <p className="text-xs text-muted-foreground">{data.footer}</p>
        )}
      </div>
    );
  },
});

function extractSessionId(): string {
  if (typeof window === "undefined") return "";
  // URL pattern: /session/{id} or query param ?sessionId=...
  const match = window.location.pathname.match(/\/session\/([^/]+)/);
  if (match) return match[1];
  const params = new URLSearchParams(window.location.search);
  return params.get("sessionId") || "";
}

"use client";

import type { ImageSection as ImageSectionType } from "@/lib/widgets";

export function ImageSectionRenderer({
  section,
  sessionId,
}: {
  section: ImageSectionType;
  sessionId: string;
}) {
  const src = `/data/${sessionId}?file=${encodeURIComponent(section.src)}`;

  return (
    <figure>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={section.alt || ""}
        width={section.width}
        height={section.height}
        className="max-w-full rounded-md"
      />
      {section.caption && (
        <figcaption className="mt-1 text-xs text-muted-foreground">
          {section.caption}
        </figcaption>
      )}
    </figure>
  );
}

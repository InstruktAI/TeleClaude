"use client";

export function WidgetSkeleton() {
  return (
    <div className="my-1 animate-pulse space-y-2 rounded-lg border p-4">
      <div className="h-4 w-1/3 rounded bg-muted" />
      <div className="h-3 w-full rounded bg-muted" />
      <div className="h-3 w-2/3 rounded bg-muted" />
    </div>
  );
}

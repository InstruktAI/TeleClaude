"use client";

import { useState, useCallback, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { validateWorkItemSlug } from "@/lib/work-items/validation";
import { toast } from "@/lib/hooks/useToast";

interface NewBugModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function NewBugModal({ open, onOpenChange }: NewBugModalProps) {
  const queryClient = useQueryClient();
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const reset = useCallback(() => {
    setSlug("");
    setError(null);
    setSubmitting(false);
  }, []);

  const close = useCallback(() => {
    onOpenChange(false);
    reset();
  }, [onOpenChange, reset]);

  const handleSubmit = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      if (!slug.trim()) return;

      const fullSlug = slug.startsWith("bug-") ? slug : `bug-${slug}`;
      const validation = validateWorkItemSlug(fullSlug);
      if (!validation.ok) {
        setError("Slug must use lowercase letters, numbers, and hyphens only");
        return;
      }

      setSubmitting(true);
      setError(null);

      try {
        const res = await fetch("/api/todos", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slug: validation.slug }),
        });

        if (!res.ok) {
          const data = await res.json().catch(() => ({}));
          throw new Error(
            (data as { error?: string }).error ?? `HTTP ${res.status}`,
          );
        }

        queryClient.invalidateQueries({ queryKey: ["todos"] });
        toast({
          title: "Bug created",
          description: `${validation.slug} (full bug workflow via CLI: telec bugs report)`,
          variant: "success",
        });
        close();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to create bug");
      } finally {
        setSubmitting(false);
      }
    },
    [slug, close, queryClient],
  );

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, close]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/50" onClick={close} />
      <div className="relative z-10 w-full max-w-md rounded-xl border bg-card p-6 shadow-lg">
        <h2 className="text-lg font-semibold">New Bug</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Creates a todo with bug- prefix. Full bug workflow: <code>telec bugs report</code>
        </p>
        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">Slug</span>
            <div className="flex items-center gap-1">
              <span className="text-sm text-muted-foreground">bug-</span>
              <input
                type="text"
                value={slug}
                onChange={(e) => {
                  setSlug(e.target.value);
                  setError(null);
                }}
                placeholder="description"
                className="flex-1 rounded-md border bg-background px-3 py-2 text-sm"
                autoFocus
              />
            </div>
            {error && <p className="text-xs text-destructive">{error}</p>}
          </label>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={close}
              className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:bg-accent"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !slug.trim()}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {submitting ? "Creating..." : "Create Bug"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import type {
  ComputerInfo,
  ProjectInfo,
  AgentName,
  ThinkingMode,
} from "@/lib/api/types";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function NewSessionDialog({ open, onOpenChange }: Props) {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [computers, setComputers] = useState<ComputerInfo[]>([]);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [projectsError, setProjectsError] = useState(false);
  const [computer, setComputer] = useState("");
  const [projectPath, setProjectPath] = useState("");
  const [agent, setAgent] = useState<AgentName>("claude");
  const [thinkingMode, setThinkingMode] = useState<ThinkingMode>("med");
  const [title, setTitle] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch computers on open
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    fetch("/api/computers", { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: ComputerInfo[]) => {
        setComputers(data);
        if (data.length > 0) {
          setComputer((prev) => {
            if (prev) return prev;
            const local = data.find((c) => c.is_local);
            return local?.name ?? data[0].name;
          });
        }
      })
      .catch((err) => { if (err.name !== "AbortError") setComputers([]); });
    return () => controller.abort();
  }, [open]);

  // Fetch projects when computer changes
  useEffect(() => {
    if (!computer) return;
    setProjects([]);
    setProjectPath("");
    setProjectsLoading(true);
    setProjectsError(false);
    const controller = new AbortController();
    fetch(`/api/projects?computer=${encodeURIComponent(computer)}`, { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data: ProjectInfo[]) => {
        setProjects(data);
        if (data.length > 0) setProjectPath(data[0].path);
        setProjectsLoading(false);
      })
      .catch((err) => {
        if (err.name !== "AbortError") {
          setProjectsError(true);
          setProjectsLoading(false);
        }
      });
    return () => controller.abort();
  }, [computer]);

  function reset() {
    setTitle("");
    setMessage("");
    setError(null);
    setSubmitting(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!computer || !projectPath) return;

    setSubmitting(true);
    setError(null);

    try {
      const body: Record<string, string | null> = {
        computer,
        project_path: projectPath,
        agent,
        thinking_mode: thinkingMode,
        launch_kind: message ? "agent_then_message" : "agent",
        title: title || null,
        message: message || null,
      };

      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error ?? `HTTP ${res.status}`);
      }

      const data = await res.json();
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      onOpenChange(false);
      reset();
      router.push(`/?sessionId=${data.session_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create session");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="fixed inset-0 bg-black/50"
        onClick={() => {
          onOpenChange(false);
          reset();
        }}
      />
      <div className="relative z-10 w-full max-w-md rounded-xl border bg-card p-6 shadow-lg">
        <h2 className="text-lg font-semibold">New Session</h2>

        <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
          {/* Computer */}
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              Computer
            </span>
            <select
              value={computer}
              onChange={(e) => setComputer(e.target.value)}
              className="rounded-md border bg-background px-3 py-2 text-sm"
            >
              {computers.map((c) => (
                <option key={c.name} value={c.name}>
                  {c.name} {c.is_local ? "(local)" : ""}
                </option>
              ))}
            </select>
          </label>

          {/* Project */}
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              Project
            </span>
            <select
              value={projectPath}
              onChange={(e) => setProjectPath(e.target.value)}
              className="rounded-md border bg-background px-3 py-2 text-sm"
              disabled={projectsLoading || projectsError || projects.length === 0}
            >
              {projectsLoading && <option value="">Loading...</option>}
              {projectsError && <option value="">Failed to load projects</option>}
              {!projectsLoading && !projectsError && projects.length === 0 && (
                <option value="">No projects available</option>
              )}
              {projects.map((p) => (
                <option key={p.path} value={p.path}>
                  {p.name} — {p.path}
                </option>
              ))}
            </select>
          </label>

          {/* Agent */}
          <fieldset className="flex flex-col gap-1">
            <legend className="text-xs font-medium text-muted-foreground">
              Agent
            </legend>
            <div className="flex gap-2">
              {(["claude", "gemini", "codex"] as AgentName[]).map((a) => (
                <label
                  key={a}
                  className="flex-1 cursor-pointer rounded-md border px-3 py-2 text-center text-sm transition-all"
                  style={{
                    borderColor: agent === a ? `var(--tc-agent-${a}-normal)` : undefined,
                    backgroundColor: agent === a ? `var(--tc-agent-${a}-subtle)` : undefined,
                    color: agent === a ? "var(--tc-text-primary)" : undefined,
                    fontWeight: agent === a ? 600 : undefined,
                  }}
                >
                  <input
                    type="radio"
                    name="agent"
                    value={a}
                    checked={agent === a}
                    onChange={() => setAgent(a)}
                    className="sr-only"
                  />
                  {a.charAt(0).toUpperCase() + a.slice(1)}
                </label>
              ))}
            </div>
          </fieldset>

          {/* Thinking mode */}
          <fieldset className="flex flex-col gap-1">
            <legend className="text-xs font-medium text-muted-foreground">
              Thinking Mode
            </legend>
            <div className="flex gap-2">
              {(["fast", "med", "slow"] as ThinkingMode[]).map((m) => (
                <label
                  key={m}
                  className={`flex-1 cursor-pointer rounded-md border px-3 py-2 text-center text-sm transition-colors ${
                    thinkingMode === m
                      ? "border-primary bg-primary/5 font-medium"
                      : "hover:bg-accent"
                  }`}
                >
                  <input
                    type="radio"
                    name="mode"
                    value={m}
                    checked={thinkingMode === m}
                    onChange={() => setThinkingMode(m)}
                    className="sr-only"
                  />
                  {m}
                </label>
              ))}
            </div>
          </fieldset>

          {/* Title */}
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              Title (optional)
            </span>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Auto-generated"
              className="rounded-md border bg-background px-3 py-2 text-sm"
            />
          </label>

          {/* Initial message */}
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">
              Initial Message (optional)
            </span>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Start with a message..."
              rows={3}
              className="rounded-md border bg-background px-3 py-2 text-sm resize-none"
            />
          </label>

          {error && (
            <p className="text-xs text-destructive">{error}</p>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                onOpenChange(false);
                reset();
              }}
              className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:bg-accent"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !computer || !projectPath}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {submitting ? "Creating..." : "Create Session"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

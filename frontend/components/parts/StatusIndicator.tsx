"use client";

type SessionStatus = "streaming" | "idle" | "closed" | "error";

const statusConfig: Record<SessionStatus, { color: string; label: string }> = {
  streaming: { color: "bg-green-500", label: "Streaming" },
  idle: { color: "bg-gray-400", label: "Idle" },
  closed: { color: "bg-gray-300", label: "Closed" },
  error: { color: "bg-red-500", label: "Error" },
};

interface Props {
  status: SessionStatus;
}

export function StatusIndicator({ status }: Props) {
  const config = statusConfig[status] ?? statusConfig.idle;

  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`h-2 w-2 rounded-full ${config.color}`} />
      {config.label}
    </span>
  );
}

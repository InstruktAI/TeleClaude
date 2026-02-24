import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonStream } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";
import { cleanMessageText, isSystemInjected, getCommandHeader } from "@/lib/utils/text";

/**
 * Extract text content from an AI SDK UIMessage parts array or content array.
 */
function partsToText(parts: unknown): string {
  if (!Array.isArray(parts)) return "";
  return parts
    .map((p: unknown) => {
      if (typeof p === "string") return p;
      if (typeof p === "object" && p !== null) {
        const part = p as { type?: string; text?: string; content?: string };
        return part.text ?? part.content ?? "";
      }
      return "";
    })
    .filter(Boolean)
    .join("\n\n");
}

/**
 * Transform AI SDK request body to daemon ChatStreamRequest format.
 */
function toDaemonBody(body: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {
    sessionId: body.sessionId,
  };

  if (body.since_timestamp) {
    result.since_timestamp = body.since_timestamp;
  }

  if (Array.isArray(body.messages) && body.messages.length > 0) {
    result.messages = body.messages.map(
      (msg: { role?: string; content?: unknown; parts?: unknown }) => {
        let content = "";
        if (typeof msg.content === "string") {
          content = cleanMessageText(msg.content);
        } else if (Array.isArray(msg.content)) {
          content = cleanMessageText(partsToText(msg.content));
        } else if (Array.isArray(msg.parts)) {
          content = cleanMessageText(partsToText(msg.parts));
        }
        return {
          role: msg.role ?? "user",
          content,
        };
      },
    );
  }

  return result;
}

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: Record<string, unknown>;
  try {
    body = await request.json();
  } catch (err) {
    return NextResponse.json(
      { error: "Invalid JSON in request body" },
      { status: 400 },
    );
  }

  try {
    const res = await daemonStream({
      method: "POST",
      path: "/api/chat/stream",
      body: toDaemonBody(body),
      headers: buildIdentityHeaders(session),
    });

    if (res.status >= 400) {
      const chunks: Buffer[] = [];
      for await (const chunk of res.stream) {
        chunks.push(chunk);
      }
      const errorBody = Buffer.concat(chunks).toString("utf-8");
      let message = "Upstream service error";
      try {
        const parsed = JSON.parse(errorBody);
        if (parsed.detail) message = String(parsed.detail);
        else if (parsed.message) message = String(parsed.message);
      } catch {
        // body is not JSON
      }
      return NextResponse.json(
        { error: message, upstream_status: res.status },
        { status: res.status },
      );
    }

    // Stateful stream transformer
    let sseBuffer = "";
    // Bounded suppression state (strictly for the current content part)
    let suppressingPartId: string | null = null;

    const transformStream = new TransformStream({
      transform(chunk, controller) {
        sseBuffer += new TextDecoder().decode(chunk, { stream: true });
        const parts = sseBuffer.split("\n\n");
        sseBuffer = parts.pop() || "";

        for (const part of parts) {
          const line = part.trim();
          if (!line || !line.startsWith("data: ")) {
            if (line) controller.enqueue(new TextEncoder().encode(line + "\n\n"));
            continue;
          }

          const dataStr = line.slice(6).trim();
          if (dataStr === "[DONE]") {
            controller.enqueue(new TextEncoder().encode("data: [DONE]\n\n"));
            continue;
          }

          try {
            const data = JSON.parse(dataStr);

            // Reset suppression state on life-cycle events
            if (data.type === "text-start" || data.type === "finish") {
              suppressingPartId = null;
            }

            // 1. Filter out custom session/result events
            if (data.type === "data-session-status" || data.type === "data-send-result") {
              continue;
            }

            // 2. Handle text deltas with surgical part-level suppression
            if (data.type === "text-delta" && typeof data.delta === "string") {
              if (suppressingPartId === data.id) continue;

              const commandHeader = getCommandHeader(data.delta);
              if (commandHeader) {
                // Detected a command! Emit the header and suppress everything else in THIS part.
                suppressingPartId = data.id;
                controller.enqueue(
                  new TextEncoder().encode(
                    "data: " + JSON.stringify({ ...data, delta: commandHeader }) + "\n\n"
                  )
                );
                continue;
              }

              // Filter out system checkpoints
              if (isSystemInjected(data.delta)) continue;
            }

            // Keep original line
            controller.enqueue(new TextEncoder().encode("data: " + dataStr + "\n\n"));
          } catch (e) {
            controller.enqueue(new TextEncoder().encode("data: " + dataStr + "\n\n"));
          }
        }
      },
      flush(controller) {
        if (sseBuffer.trim()) {
          controller.enqueue(new TextEncoder().encode(sseBuffer.trim() + "\n\n"));
        }
      }
    });

    return new NextResponse(
      (res.stream as unknown as ReadableStream).pipeThrough(transformStream),
      {
        status: res.status,
        headers: {
          "Content-Type": "text/event-stream",
          "x-vercel-ai-ui-message-stream": "v1",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
      },
    );
  } catch (err) {
    console.error("[api/chat POST] daemon unreachable:", (err as Error).message);
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}

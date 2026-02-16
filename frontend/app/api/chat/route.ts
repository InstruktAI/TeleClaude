import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonStream } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body;
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
      body,
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

    return new NextResponse(res.stream as unknown as ReadableStream, {
      status: res.status,
      headers: {
        "Content-Type":
          res.headers["content-type"] ?? "application/json",
      },
    });
  } catch (err) {
    console.error("[api/chat POST] daemon unreachable:", (err as Error).message);
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}

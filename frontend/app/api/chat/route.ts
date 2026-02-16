import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonRequest, normalizeUpstreamError } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

export async function POST(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const body = await request.json();

    const res = await daemonRequest({
      method: "POST",
      path: "/api/chat/stream",
      body,
      headers: buildIdentityHeaders(session),
    });

    if (res.status >= 400) {
      return NextResponse.json(
        normalizeUpstreamError(res.status, res.body),
        { status: res.status },
      );
    }

    return new NextResponse(res.body, {
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

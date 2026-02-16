import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { auth } from "@/auth";
import { daemonRequest, normalizeUpstreamError } from "@/lib/proxy/daemon-client";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

export async function GET(request: NextRequest) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const computer = request.nextUrl.searchParams.get("computer");
  const queryStr = computer ? `?computer=${encodeURIComponent(computer)}` : "";

  try {
    const res = await daemonRequest({
      method: "GET",
      path: `/sessions${queryStr}`,
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
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("[api/sessions GET] daemon unreachable:", (err as Error).message);
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}

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
    const { computer, title, initial_message } = body;

    const res = await daemonRequest({
      method: "POST",
      path: "/sessions",
      body: {
        computer,
        title,
        initial_message,
        human_email: session.user.email,
        human_role: session.user.role,
      },
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
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    console.error("[api/sessions POST] daemon unreachable:", (err as Error).message);
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}

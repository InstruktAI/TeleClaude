import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { daemonRequest, normalizeUpstreamError } from "@/lib/proxy/daemon-client";
import { requireAdmin } from "@/lib/proxy/auth-guards";
import { buildIdentityHeaders } from "@/lib/proxy/identity-headers";

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ name: string }> },
) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const adminErr = requireAdmin(session);
  if (adminErr) {
    return adminErr;
  }

  const { name } = await params;

  try {
    const res = await daemonRequest({
      method: "POST",
      path: `/jobs/${encodeURIComponent(name)}/run`,
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
    console.error(`[api/jobs/${name}/run POST] daemon unreachable:`, (err as Error).message);
    return NextResponse.json(
      { error: "Service unavailable" },
      { status: 503 },
    );
  }
}

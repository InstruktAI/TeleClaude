import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { auth } from '@/auth';
import { daemonRequest, normalizeUpstreamError } from '@/lib/proxy/daemon-client';
import { buildIdentityHeaders } from '@/lib/proxy/identity-headers';

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await params;
  const searchParams = request.nextUrl.searchParams;
  const qs = new URLSearchParams();
  for (const key of ['since', 'include_tools', 'include_thinking']) {
    const val = searchParams.get(key);
    if (val) qs.set(key, val);
  }
  const queryStr = qs.toString() ? `?${qs.toString()}` : '';

  try {
    const res = await daemonRequest({
      method: 'GET',
      path: `/sessions/${encodeURIComponent(id)}/messages${queryStr}`,
      headers: buildIdentityHeaders(session),
    });

    if (res.status >= 400) {
      return NextResponse.json(normalizeUpstreamError(res.status, res.body), { status: res.status });
    }

    return new NextResponse(res.body, {
      status: res.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    console.error(`[api/sessions/${id}/messages GET] daemon unreachable:`, (err as Error).message);
    return NextResponse.json({ error: 'Service unavailable' }, { status: 503 });
  }
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await params;

  let body;
  try {
    body = await request.json();
  } catch (err) {
    return NextResponse.json({ error: 'Invalid JSON in request body' }, { status: 400 });
  }

  try {
    const res = await daemonRequest({
      method: 'POST',
      path: `/sessions/${encodeURIComponent(id)}/message`,
      body,
      headers: buildIdentityHeaders(session),
    });

    if (res.status >= 400) {
      return NextResponse.json(normalizeUpstreamError(res.status, res.body), { status: res.status });
    }

    return new NextResponse(res.body, {
      status: res.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err) {
    console.error(`[api/sessions/${id}/messages POST] daemon unreachable:`, (err as Error).message);
    return NextResponse.json({ error: 'Service unavailable' }, { status: 503 });
  }
}

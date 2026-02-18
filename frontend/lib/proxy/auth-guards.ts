import { NextResponse } from "next/server";
import type { Session } from "next-auth";

/**
 * Returns a 403 response if the session user is not an admin.
 * Returns null if the user IS an admin (caller should continue).
 */
export function requireAdmin(session: Session): NextResponse | null {
  if (session.user.role !== "admin") {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  return null;
}

/**
 * Returns a 403 response if the session user's email does not match
 * the provided owner email. Returns null if ownership matches or
 * the user is admin (admins bypass ownership checks).
 */
export function requireOwnership(
  session: Session,
  ownerEmail: string | null | undefined,
): NextResponse | null {
  if (session.user.role === "admin") return null;
  if (session.user.email === ownerEmail) return null;
  return NextResponse.json(
    { error: "Forbidden: you do not own this resource" },
    { status: 403 },
  );
}

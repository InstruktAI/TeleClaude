import { NextResponse } from "next/server";
import { auth } from "@/auth";
import { getPeople } from "@/lib/identity/people";

export async function GET() {
  const session = await auth();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const people = getPeople().map((p) => ({
    name: p.name,
    email: p.email,
    role: p.role,
  }));

  return NextResponse.json(people);
}

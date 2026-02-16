import { NextResponse } from "next/server";
import { getPeople } from "@/lib/identity/people";

export async function GET() {
  const people = getPeople().map((p) => ({
    name: p.name,
    email: p.email,
    role: p.role,
  }));

  return NextResponse.json(people);
}

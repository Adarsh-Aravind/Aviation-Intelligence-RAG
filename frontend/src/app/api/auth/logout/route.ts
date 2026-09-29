import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, isSameOrigin } from "@/lib/server/session";

export async function POST(req: NextRequest) {
  if (!isSameOrigin(req)) {
    return NextResponse.json({ detail: "Forbidden" }, { status: 403 });
  }
  const res = NextResponse.json({ admin: false });
  res.cookies.delete(SESSION_COOKIE);
  return res;
}

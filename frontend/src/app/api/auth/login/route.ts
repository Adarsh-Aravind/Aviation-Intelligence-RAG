import { NextResponse, type NextRequest } from "next/server";

import {
  SESSION_COOKIE,
  createSessionToken,
  isSameOrigin,
  safeEqual,
  sessionCookieOptions,
} from "@/lib/server/session";

export async function POST(req: NextRequest) {
  if (!isSameOrigin(req)) {
    return NextResponse.json({ detail: "Forbidden" }, { status: 403 });
  }
  const expected = process.env.ADMIN_PASSWORD;
  if (!expected) {
    return NextResponse.json({ detail: "Admin login is not configured" }, { status: 503 });
  }
  const body = (await req.json().catch(() => null)) as { password?: unknown } | null;
  const password = typeof body?.password === "string" ? body.password : "";

  if (!safeEqual(password, expected)) {
    // Slow down brute-force attempts.
    await new Promise((r) => setTimeout(r, 800));
    return NextResponse.json({ detail: "Incorrect password" }, { status: 401 });
  }

  const res = NextResponse.json({ admin: true });
  res.cookies.set(SESSION_COOKIE, await createSessionToken(), sessionCookieOptions);
  return res;
}

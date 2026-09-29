import { NextResponse, type NextRequest } from "next/server";

import { isAdminRequest } from "@/lib/server/session";

export async function GET(req: NextRequest) {
  return NextResponse.json({ admin: await isAdminRequest(req) }, { headers: { "Cache-Control": "no-store" } });
}

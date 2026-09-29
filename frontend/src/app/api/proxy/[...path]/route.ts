// Backend-for-frontend proxy. The browser calls /api/proxy/<path>; this server-side handler forwards an
// allowlisted set of routes to the FastAPI backend, attaching secrets that never leave the server.
import { NextResponse, type NextRequest } from "next/server";

import { isAdminRequest, isSameOrigin } from "@/lib/server/session";

export const maxDuration = 60; // LLM answers can take a while

type Method = "GET" | "POST" | "DELETE";
interface Rule {
  method: Method;
  pattern: RegExp;
  admin?: boolean;
}

const UUID = "[0-9a-fA-F-]{36}";
const RULES: Rule[] = [
  { method: "GET", pattern: /^health$/ },
  { method: "GET", pattern: /^stats$/ },
  { method: "GET", pattern: /^documents$/ },
  { method: "GET", pattern: new RegExp(`^documents/${UUID}$`) },
  { method: "GET", pattern: new RegExp(`^documents/${UUID}/file-url$`) },
  { method: "POST", pattern: /^chat$/ },
  { method: "POST", pattern: /^documents\/init$/, admin: true },
  { method: "POST", pattern: new RegExp(`^documents/${UUID}/(complete|reprocess)$`), admin: true },
  { method: "DELETE", pattern: new RegExp(`^documents/${UUID}$`), admin: true },
];

const MAX_BODY_BYTES = 16 * 1024; // JSON only — files go straight to storage

/** The backend runs on a self-hosted home server that can lose power or internet. */
function offline() {
  return NextResponse.json(
    {
      detail: "The AI server is temporarily offline (it's self-hosted). Please try again in a few minutes.",
      offline: true,
    },
    { status: 503, headers: { "Cache-Control": "no-store" } },
  );
}

function clientIp(req: NextRequest): string {
  const fwd = req.headers.get("x-forwarded-for");
  return (fwd?.split(",")[0] ?? req.headers.get("x-real-ip") ?? "unknown").trim();
}

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const joined = path.join("/");
  const method = req.method as Method;
  const rule = RULES.find((r) => r.method === method && r.pattern.test(joined));
  if (!rule) return NextResponse.json({ detail: "Not found" }, { status: 404 });

  if (method !== "GET" && !isSameOrigin(req)) {
    return NextResponse.json({ detail: "Forbidden" }, { status: 403 });
  }

  const backendUrl = process.env.BACKEND_URL;
  const apiKey = process.env.BACKEND_API_KEY;
  if (!backendUrl || !apiKey) {
    return NextResponse.json({ detail: "Backend is not configured" }, { status: 503 });
  }

  const headers: Record<string, string> = {
    "X-API-Key": apiKey,
    "X-Client-IP": clientIp(req),
    Accept: "application/json",
  };
  if (rule.admin) {
    if (!(await isAdminRequest(req))) {
      return NextResponse.json({ detail: "Admin login required" }, { status: 401 });
    }
    headers["X-Admin-Key"] = process.env.BACKEND_ADMIN_KEY ?? "";
  }

  let body: string | undefined;
  if (method === "POST") {
    body = await req.text();
    if (body.length > MAX_BODY_BYTES) {
      return NextResponse.json({ detail: "Request too large" }, { status: 413 });
    }
    headers["Content-Type"] = "application/json";
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${backendUrl.replace(/\/$/, "")}/api/${joined}`, {
      method,
      headers,
      body: body || undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(55_000),
    });
  } catch (err) {
    const timedOut = err instanceof Error && err.name === "TimeoutError";
    return timedOut
      ? NextResponse.json({ detail: "The AI server took too long to respond." }, { status: 504 })
      : offline();
  }

  if (upstream.status === 204) return new NextResponse(null, { status: 204 });
  const contentType = upstream.headers.get("content-type") ?? "";
  // When the home server or its tunnel is down, Cloudflare answers with an HTML error page
  // (502/503/504/530/1033). Translate that into a clean JSON "offline" response.
  if (!contentType.includes("application/json")) return offline();
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}

export { handle as GET, handle as POST, handle as DELETE };

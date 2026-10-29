import { type NextRequest, NextResponse } from "next/server";

// The public demo gives each visitor their own sandbox of the demo state (api/pheri/app.py). The visitor is this
// cookie: made here on the first page, kept for 30 minutes idle, and forwarded to the API by lib/api.ts (server
// components) and app/api/[...path]/route.ts (the browser's calls). No login, nothing else about the visitor.
const SANDBOX_COOKIE = "pheri_sandbox"; // lib/api.ts reads the same name
const IDLE_S = 30 * 60;
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export function proxy(request: NextRequest) {
  let id = request.cookies.get(SANDBOX_COOKIE)?.value ?? "";
  if (!ID.test(id)) {
    id = crypto.randomUUID();
    request.cookies.set(SANDBOX_COOKIE, id); // so this very render already has it
  }
  const response = NextResponse.next({ request: { headers: request.headers } });
  response.cookies.set(SANDBOX_COOKIE, id, { maxAge: IDLE_S, httpOnly: true, sameSite: "lax", path: "/" });
  return response;
}

export const config = { matcher: ["/((?!_next/|favicon.ico).*)"] };

import { API_URL, SANDBOX_COOKIE, SANDBOX_HEADER } from "@/lib/api";

// The browser calls /api/... on this origin and this handler forwards it to the Pheri API, so no CORS is
// needed. Unlike a next.config rewrite (fixed at build time), the API's address is read when the server
// starts, so changing PHERI_API_URL needs a restart, not a rebuild. The path and query go through as sent, with
// the visitor's sandbox id from their cookie (the public demo keeps one sandbox per visitor).
async function forward(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const target = `${API_URL}${url.pathname.replace(/^\/api/, "")}${url.search}`;
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const id = new RegExp(`(?:^|;\\s*)${SANDBOX_COOKIE}=([^;]+)`).exec(request.headers.get("cookie") ?? "")?.[1];
  try {
    const res = await fetch(target, {
      method: request.method,
      headers: {
        "content-type": request.headers.get("content-type") ?? "application/json",
        ...(id ? { [SANDBOX_HEADER]: decodeURIComponent(id) } : {}),
      },
      body: hasBody ? await request.text() : undefined,
      cache: "no-store",
    });
    return new Response(res.body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "The Pheri API is not reachable." }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;

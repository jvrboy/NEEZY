import { NextResponse } from "next/server";

export function proxy(request) {
  const username = process.env.DASHBOARD_USERNAME;
  const password = process.env.DASHBOARD_PASSWORD;
  if (!username || !password) {
    return new Response("Dashboard authentication is not configured.", { status: 503 });
  }

  const authorization = request.headers.get("authorization") || "";
  let supplied = "";
  if (authorization.startsWith("Basic ")) {
    try {
      supplied = atob(authorization.slice(6));
    } catch (_error) {
      supplied = "";
    }
  }
  if (supplied === `${username}:${password}`) return NextResponse.next();

  return new Response("Authentication required", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="NEEZY Executor", charset="UTF-8"' },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

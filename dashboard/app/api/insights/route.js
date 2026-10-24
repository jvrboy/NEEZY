import { getExecutorResource } from "@/lib/status";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return Response.json(await getExecutorResource("insights"), {
      headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
    });
  } catch (_error) {
    return Response.json({ error: "Executor insights unavailable." }, {
      status: 503, headers: { "Cache-Control": "no-store" },
    });
  }
}

export const MAX_RESPONSE_BYTES = 1_000_000;
export const RESOURCES = Object.freeze(["status", "capabilities", "insights"]);

export async function fetchExecutorResource(resource = "status", { env = process.env, fetcher = fetch } = {}) {
  if (!RESOURCES.includes(resource)) throw new Error("unsupported executor resource");
  const endpoint = new URL(env.NEEZY_STATUS_URL || "");
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password) throw new Error("executor endpoint requires HTTPS without URL credentials");
  if (resource !== "status") endpoint.pathname = `/api/${resource}`;
  endpoint.search = "";
  endpoint.hash = "";
  const response = await fetcher(endpoint, {
    headers: {
      "CF-Access-Client-Id": env.CF_ACCESS_CLIENT_ID || "",
      "CF-Access-Client-Secret": env.CF_ACCESS_CLIENT_SECRET || "",
      Accept: "application/json",
    },
    redirect: "error", cache: "no-store", signal: AbortSignal.timeout(8_000),
  });
  if (!response.ok) throw new Error("executor unavailable");
  if (!response.headers.get("content-type")?.toLowerCase().includes("application/json")) throw new Error("invalid executor content type");
  const length = Number(response.headers.get("content-length"));
  if (length > MAX_RESPONSE_BYTES) {
    await response.body?.cancel();
    throw new Error("executor response too large");
  }
  if (!response.body) throw new Error("empty executor response");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let content = "", total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_RESPONSE_BYTES) throw new Error("executor response too large");
      content += decoder.decode(value, { stream: true });
    }
    content += decoder.decode();
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally { reader.releaseLock(); }
  const document = JSON.parse(content);
  if (!document || typeof document !== "object" || Array.isArray(document)) throw new Error("invalid executor document");
  return document;
}

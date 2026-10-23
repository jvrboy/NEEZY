export async function getExecutorStatus() {
  const endpoint = new URL(process.env.NEEZY_STATUS_URL || "");
  if (endpoint.protocol !== "https:") {
    throw new Error("status endpoint must use HTTPS");
  }
  const response = await fetch(endpoint, {
    headers: {
      "CF-Access-Client-Id": process.env.CF_ACCESS_CLIENT_ID || "",
      "CF-Access-Client-Secret": process.env.CF_ACCESS_CLIENT_SECRET || "",
      Accept: "application/json",
    },
    cache: "no-store",
    signal: AbortSignal.timeout(8_000),
  });
  if (!response.ok) throw new Error("executor unavailable");
  const content = await response.text();
  if (content.length > 1_000_000) throw new Error("response too large");
  const document = JSON.parse(content);
  if (!document || typeof document !== "object" || Array.isArray(document)) {
    throw new Error("invalid status document");
  }
  return document;
}

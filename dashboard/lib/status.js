export async function getExecutorResource(resource = "status") {
  if (!["status", "capabilities"].includes(resource)) throw new Error("unsupported resource");
  const endpoint = new URL(process.env.NEEZY_STATUS_URL || "");
  if (endpoint.protocol !== "https:") {
    throw new Error("status endpoint must use HTTPS");
  }
  if (resource !== "status") endpoint.pathname = `/api/${resource}`;
  endpoint.search = "";
  endpoint.hash = "";
  const response = await fetch(endpoint, {
    redirect: "error",
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

export async function getExecutorStatus() {
  return getExecutorResource("status");
}

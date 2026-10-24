import { fetchExecutorResource } from "./executor.mjs";

export async function getExecutorResource(resource = "status") {
  return fetchExecutorResource(resource);
}

export async function getExecutorStatus() {
  return getExecutorResource("status");
}

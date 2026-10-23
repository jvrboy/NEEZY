import Dashboard from "./dashboard";
import { getExecutorStatus } from "@/lib/status";

export const dynamic = "force-dynamic";

export default async function Page() {
  let initialStatus = null;
  let initialError = "";
  try {
    initialStatus = await getExecutorStatus();
  } catch (_error) {
    initialError = "Live status is unavailable. No executor snapshot has been loaded.";
  }
  return <Dashboard initialStatus={initialStatus} initialError={initialError} />;
}

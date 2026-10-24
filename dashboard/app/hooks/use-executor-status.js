"use client";

import { useEffect, useState } from "react";
import { normalizeSnapshot, heartbeatAge } from "../../lib/snapshot.mjs";

export function useExecutorStatus({ initialStatus, initialError, preferences, ready, paused, refreshKey }) {
  const [status, setStatus] = useState(() => initialStatus ? normalizeSnapshot(initialStatus) : null);
  const [error, setError] = useState(initialError);
  const [updated, setUpdated] = useState(null);
  const [receivedAt, setReceivedAt] = useState(0);
  const [now, setNow] = useState(0);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    setReceivedAt(Date.now()); setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!ready || paused) return;
    let active = true, controller, timer, failures = 0;
    async function refresh() {
      if (!active) return;
      if (document.hidden) { timer = setTimeout(refresh, preferences.refreshSeconds * 1000); return; }
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 10000);
      setLoading(true);
      try {
        const response = await fetch("/api/status", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Status unavailable");
        const document = normalizeSnapshot(await response.json());
        if (active) {
          setStatus(document); setUpdated(new Date()); setReceivedAt(Date.now()); setNow(Date.now());
          setError(""); failures = 0;
        }
      } catch (_) {
        if (active) { failures += 1; setError("Live status is unavailable. Showing the last successful snapshot."); }
      } finally {
        clearTimeout(timeout);
        if (active) {
          setLoading(false);
          timer = setTimeout(refresh, Math.min(120000, preferences.refreshSeconds * 1000 * (2 ** Math.min(failures, 3))));
        }
      }
    }
    refresh();
    return () => { active = false; clearTimeout(timer); controller?.abort(); };
  }, [ready, paused, preferences.refreshSeconds, refreshKey]);
  return { status, error, updated, loading: loading && !paused, age: heartbeatAge(status, receivedAt, now) };
}

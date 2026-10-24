export const DEFAULT_PREFERENCES = Object.freeze({
  theme: "emerald", density: "comfortable", refreshSeconds: 30,
  reducedMotion: false, staleSeconds: 120,
});
export const STORAGE_KEY = "neezy.dashboard.preferences.v1";
export function preferenceBundle(preferences) {
  return { schema: 1, kind: "neezy-dashboard-preferences", preferences: sanitizePreferences(preferences) };
}
export function parsePreferenceBundle(content) {
  if (typeof content !== "string" || content.length > 10000) throw new Error("Settings file exceeds 10 KB.");
  const bundle = JSON.parse(content);
  if (!bundle || bundle.schema !== 1 || bundle.kind !== "neezy-dashboard-preferences" || !bundle.preferences
      || typeof bundle.preferences !== "object" || Array.isArray(bundle.preferences)) throw new Error("Unsupported settings file.");
  return sanitizePreferences(bundle.preferences);
}
export function sanitizePreferences(input) {
  const source = input && typeof input === "object" && !Array.isArray(input) ? input : {};
  return {
    theme: ["emerald", "midnight", "contrast"].includes(source.theme) ? source.theme : "emerald",
    density: source.density === "compact" ? "compact" : "comfortable",
    refreshSeconds: [15, 30, 60, 120].includes(source.refreshSeconds) ? source.refreshSeconds : 30,
    reducedMotion: source.reducedMotion === true,
    staleSeconds: [60, 120, 300].includes(source.staleSeconds) ? source.staleSeconds : 120,
  };
}

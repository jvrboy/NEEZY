import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_PREFERENCES, sanitizePreferences } from "../lib/preferences.mjs";

test("untrusted stored values fall back to safe defaults", () => {
  for (const value of [null, [], "string", 123, { theme: "<script>", refreshSeconds: -1, reducedMotion: "yes" }]) {
    assert.deepEqual(sanitizePreferences(value), DEFAULT_PREFERENCES);
  }
});
test("known choices survive and credentials or broker options do not", () => {
  assert.deepEqual(sanitizePreferences({ theme: "midnight", density: "compact", refreshSeconds: 60, staleSeconds: 300, reducedMotion: true, apiKey: "private", execution: true }), {
    theme: "midnight", density: "compact", refreshSeconds: 60, staleSeconds: 300, reducedMotion: true,
  });
});

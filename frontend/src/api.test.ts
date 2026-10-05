import { describe, expect, it } from "vitest";

import { qs } from "./api";

describe("qs", () => {
  it("returns an empty string when nothing is set", () => {
    expect(qs({})).toBe("");
    expect(qs({ a: "", b: undefined, c: null })).toBe("");
  });
  it("drops empty/undefined/null values but keeps falsy numbers", () => {
    expect(qs({ limit: 0, severity: "" })).toBe("?limit=0");
  });
  it("encodes multiple params", () => {
    const out = qs({ event_type: "PROMPT_INJECTION", limit: 50 });
    expect(out).toContain("event_type=PROMPT_INJECTION");
    expect(out).toContain("limit=50");
    expect(out.startsWith("?")).toBe(true);
  });
  it("url-encodes special characters", () => {
    expect(qs({ agent: "Finance Agent" })).toBe("?agent=Finance+Agent");
  });
});

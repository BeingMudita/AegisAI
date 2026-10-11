import { afterEach, describe, expect, it, vi } from "vitest";

import { api, qs, setToken } from "./api";

describe("ETag polling", () => {
  afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

  it("sends the tag back and reuses the data on 304", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: 1 }]), { status: 200, headers: { ETag: '"v1"' } }))
      .mockResolvedValueOnce(new Response(null, { status: 304, headers: { ETag: '"v1"' } }));
    vi.stubGlobal("fetch", fetchMock);
    setToken("t");
    const first = await api.get<{ id: number }[]>("/api/retrieval/archive");
    const second = await api.get<{ id: number }[]>("/api/retrieval/archive");
    expect(second).toBe(first);
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get("If-None-Match")).toBe('"v1"');
  });

  it("forgets tags when the signed-in user changes", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response("[]", { status: 200, headers: { ETag: '"v1"' } }));
    vi.stubGlobal("fetch", fetchMock);
    setToken("a");
    await api.get("/api/retrieval/archive");
    setToken("b");
    await api.get("/api/retrieval/archive");
    expect(new Headers(fetchMock.mock.calls[1][1].headers).has("If-None-Match")).toBe(false);
  });
});

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

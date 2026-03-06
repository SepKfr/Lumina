import { describe, it, expect, vi, beforeEach } from "vitest";
import { fetchGraph, submitInsight } from "./api";

describe("api", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("fetchGraph builds correct URL and returns JSON", async () => {
    const mockJson = { nodes: [], edges: [] };
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockJson),
    });

    const result = await fetchGraph({ node_id: "abc", depth: 2 });

    expect(result).toEqual(mockJson);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toContain("/v1/graph");
    expect(fetch.mock.calls[0][0]).toContain("node_id=abc");
    expect(fetch.mock.calls[0][0]).toContain("depth=2");
  });

  it("submitInsight sends POST with JSON body", async () => {
    const mockJson = { node: { id: "1" } };
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve(mockJson),
    });

    const result = await submitInsight("Winters are cozy.");

    expect(result).toEqual(mockJson);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toContain("/v1/insights");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "Winters are cozy." }),
    });
  });
});

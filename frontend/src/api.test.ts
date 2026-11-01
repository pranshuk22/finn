import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, clearSaved, readSaved, writeSaved } from "./api";

// Node has no localStorage; a Map behind the Storage methods api.ts uses is enough.
const store = new Map<string, string>();
Object.assign(globalThis, {
  localStorage: {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  },
});

describe("saved responses", () => {
  beforeEach(() => store.clear());

  it("returns a copy saved by this build", () => {
    writeSaved("/api/brief?hours=24", { moves: [] });
    expect(readSaved("/api/brief?hours=24")?.data).toEqual({ moves: [] });
  });

  it("ignores a copy saved by an older build, which may have a different shape", () => {
    // The blank-brief bug: a pre-deploy brief had no moves[].filed and the new code read .length of it.
    store.set("finn:/api/brief?hours=168", JSON.stringify({ at: 1, data: { moves: [{ ticker: "DIXON" }] } }));
    store.set("finn:/api/meta", JSON.stringify({ at: 1, build: "older", data: {} }));
    expect(readSaved("/api/brief?hours=168")).toBeNull();
    expect(readSaved("/api/meta")).toBeNull();
  });

  it("clears responses but keeps settings and done cards", () => {
    writeSaved("/api/brief?hours=24", {});
    store.set("finn:settings", "{}");
    store.set("finn:done", "[]");
    clearSaved();
    expect([...store.keys()].sort()).toEqual(["finn:done", "finn:settings"]);
  });
});

describe("requests during an API restart", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  const reply = (status: number, body: unknown = {}) => new Response(JSON.stringify(body), { status });

  it("sends a 502 again and returns the answer once the API is back", async () => {
    // The Ask that failed on 1 Nov landed while security updates were restarting the API.
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValueOnce(reply(502)).mockResolvedValueOnce(reply(200, { answer: "ok" }));
    vi.stubGlobal("fetch", fetch);
    const p = api.post("/api/research/RELIANCE/ask", { question: "What are the profits?" });
    await vi.runAllTimersAsync();
    await expect(p).resolves.toEqual({ answer: "ok" });
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("gives up after two retries, and never retries other errors", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValue(reply(502));
    vi.stubGlobal("fetch", fetch);
    const p = api.get("/api/brief").catch((e) => e.status);
    await vi.runAllTimersAsync();
    expect(await p).toBe(502);
    expect(fetch).toHaveBeenCalledTimes(3);

    const once = vi.fn().mockResolvedValue(reply(500, { detail: "boom" }));
    vi.stubGlobal("fetch", once);
    await expect(api.get("/api/brief")).rejects.toThrow("boom");
    expect(once).toHaveBeenCalledTimes(1);
  });
});

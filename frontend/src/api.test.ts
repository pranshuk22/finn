import { beforeEach, describe, expect, it } from "vitest";
import { clearSaved, readSaved, writeSaved } from "./api";

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

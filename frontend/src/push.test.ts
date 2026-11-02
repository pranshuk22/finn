import { describe, expect, it } from "vitest";
import { keyBytes } from "./push";

describe("push key", () => {
  it("turns the server's base64url key into the 65 bytes of a P-256 point", () => {
    // the form backend/push.py public_key() returns: 0x04, then x and y, base64url without padding
    const raw = new Uint8Array(65).map((_, i) => (i === 0 ? 4 : i));
    const b64url = btoa(String.fromCharCode(...raw)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    expect(Array.from(keyBytes(b64url))).toEqual(Array.from(raw));
  });
});

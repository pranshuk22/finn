import { api } from "./api";

// Web Push on this device. The server holds the signing key (backend/push.py); the browser gives FINN an
// endpoint to post to. iPhones only allow it for apps added to the Home Screen (iOS 16.4 and later).

export type PushState = "unsupported" | "needs-install" | "denied" | "off" | "on";

const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent);
const standalone = () => matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;

/** The key the server signs with, as the bytes PushManager wants. */
export function keyBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
  const bin = atob((b64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(bin.length));
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function pushState(): Promise<PushState> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window))
    return isIos() && !standalone() ? "needs-install" : "unsupported";
  if (Notification.permission === "denied") return "denied";
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  return sub ? "on" : "off";
}

let key: Promise<string> | null = null;

/** Fetch the server's key ahead of the tap, once per page load. */
export function prefetchKey(): Promise<string> {
  key ??= api.get<{ key: string }>("/api/push/key").then((r) => r.key);
  key.catch(() => (key = null)); // try again on the next tap
  return key;
}

export async function turnOn(): Promise<PushState> {
  if ((await Notification.requestPermission()) !== "granted") return "denied";
  const [reg, k] = await Promise.all([navigator.serviceWorker.ready, prefetchKey()]);
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(k) });
  await api.post("/api/push/subscribe", sub.toJSON());
  return "on";
}

export async function turnOff(): Promise<PushState> {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  if (sub) {
    await api.post("/api/push/unsubscribe", sub.toJSON()).catch(() => undefined); // the server forgets it anyway on its next 410
    await sub.unsubscribe();
  }
  return "off";
}

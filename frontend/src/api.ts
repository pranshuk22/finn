import { useCallback, useEffect, useRef, useState } from "react";

// Every GET is cached on the device. The screen renders the saved copy at once, then replaces it when the
// network answers. If the network fails, the saved copy stays and the screen says how old it is.

const PREFIX = "finn:";

interface Saved<T> {
  at: number;
  data: T;
}

function readSaved<T>(key: string): Saved<T> | null {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw ? (JSON.parse(raw) as Saved<T>) : null;
  } catch {
    return null;
  }
}

function writeSaved<T>(key: string, data: T): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify({ at: Date.now(), data }));
  } catch {
    // storage full or blocked: the app still works, it just cannot show this offline
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  } catch {
    throw new ApiError(0, "You are offline or the server is unreachable.");
  }
  if (!res.ok) {
    let detail = `Request failed (${res.status}).`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
};

export interface Query<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  savedAt: number | null; // set when showing a saved copy because the network failed
  reload: () => void;
}

export function useQuery<T>(path: string | null): Query<T> {
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean; savedAt: number | null }>(
    () => {
      const saved = path ? readSaved<T>(path) : null;
      return { data: saved?.data ?? null, error: null, loading: !!path, savedAt: null };
    },
  );
  const [tick, setTick] = useState(0);
  const current = useRef(path);

  useEffect(() => {
    current.current = path;
    if (!path) return;
    const saved = readSaved<T>(path);
    setState((s) => ({ ...s, data: saved?.data ?? null, loading: true, error: null, savedAt: null }));
    request<T>(path)
      .then((data) => {
        if (current.current !== path) return;
        writeSaved(path, data);
        setState({ data, error: null, loading: false, savedAt: null });
      })
      .catch((error: ApiError) => {
        if (current.current !== path) return;
        setState({ data: saved?.data ?? null, error, loading: false, savedAt: saved?.at ?? null });
      });
  }, [path, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

// Small per-device state that is not worth a server round trip: which brief cards are done.
export function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(PREFIX + key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (v: T) => {
      setValue(v);
      try {
        localStorage.setItem(PREFIX + key, JSON.stringify(v));
      } catch {
        // ignore
      }
    },
    [key],
  );
  return [value, set];
}

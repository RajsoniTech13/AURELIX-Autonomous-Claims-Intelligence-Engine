/**
 * The signed-in session, held in one place.
 *
 * - The **access token** (15 minutes) lives only in memory. A page reload loses it, which
 *   is fine: the refresh token gets a new one.
 * - The **refresh token** (7 days) is kept in localStorage so a reload does not sign the
 *   reviewer out. It is rotated on every use, and the server revokes the whole session if
 *   an old one is ever replayed — so a copy stolen from storage stops working the moment
 *   either party uses it. An httpOnly cookie would be stronger, but the frontend and the API
 *   are different sites, where browsers increasingly block such cookies (see docs/SECURITY.md).
 *
 * The page never renders model text or user text as HTML, which is what keeps script
 * injection — the usual way storage is read — off the table in the first place.
 */
import { API_URL } from "@/lib/config";

export type Role = "claimant" | "reviewer" | "admin";
export type SessionUser = { username: string; role: Role; is_demo: boolean };

type TokenResponse = {
  access_token: string;
  expires_in: number;
  refresh_token: string;
  user: SessionUser;
};

const REFRESH_KEY = "aurelix.refresh";

let accessToken: string | null = null;
let accessExpiresAt = 0;
let currentUser: SessionUser | null = null;
let refreshing: Promise<boolean> | null = null;
const listeners = new Set<(user: SessionUser | null) => void>();

function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // private mode or blocked storage: the session lasts until reload
  }
}

function setSession(tokens: TokenResponse | null) {
  if (tokens) {
    accessToken = tokens.access_token;
    // Renew a little early, so a request in flight does not carry a token that expires mid-way.
    accessExpiresAt = Date.now() + (tokens.expires_in - 30) * 1000;
    currentUser = tokens.user;
    try { storage()?.setItem(REFRESH_KEY, tokens.refresh_token); } catch { /* ignore */ }
  } else {
    accessToken = null;
    accessExpiresAt = 0;
    currentUser = null;
    try { storage()?.removeItem(REFRESH_KEY); } catch { /* ignore */ }
  }
  listeners.forEach((fn) => fn(currentUser));
}

export function getUser(): SessionUser | null {
  return currentUser;
}

export function isReviewer(user: SessionUser | null = currentUser): boolean {
  return user?.role === "reviewer" || user?.role === "admin";
}

export function onSessionChange(fn: (user: SessionUser | null) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

async function post(path: string, body: unknown): Promise<Response> {
  try {
    return await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // fetch rejects only when no response could be read at all (offline, the free instance
    // restarting, a blocked cross-origin reply); the browser's own text is "Failed to fetch".
    throw new Error("Could not reach the analysis service. It may be restarting — try again in a minute.");
  }
}

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch { /* not JSON */ }
  return fallback;
}

export async function signIn(username: string, password: string): Promise<SessionUser> {
  const res = await post("/api/v1/auth/login", { username, password });
  if (!res.ok) throw new Error(await detail(res, "Sign-in failed."));
  const tokens: TokenResponse = await res.json();
  setSession(tokens);
  return tokens.user;
}

export async function signInDemo(role: "claimant" | "reviewer"): Promise<SessionUser> {
  const res = await post("/api/v1/auth/demo", { role });
  if (!res.ok) throw new Error(await detail(res, "The demo sign-in is unavailable."));
  const tokens: TokenResponse = await res.json();
  setSession(tokens);
  return tokens.user;
}

/**
 * Exchange the stored refresh token for a new pair. Concurrent callers share one request:
 * two parallel refreshes would rotate the same token twice, and the server would read the
 * second as a replay and end the session.
 */
export function refreshSession(): Promise<boolean> {
  if (refreshing) return refreshing;
  const stored = storage()?.getItem(REFRESH_KEY);
  if (!stored) return Promise.resolve(false);
  refreshing = (async () => {
    try {
      const res = await post("/api/v1/auth/refresh", { refresh_token: stored });
      if (!res.ok) {
        setSession(null);
        return false;
      }
      setSession(await res.json());
      return true;
    } catch {
      return false; // offline or cold-starting: keep the stored token and try again later
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

/** A valid access token, refreshing first if it has expired. Null when signed out. */
export async function accessTokenFor(): Promise<string | null> {
  if (accessToken && Date.now() < accessExpiresAt) return accessToken;
  if (await refreshSession()) return accessToken;
  return null;
}

export async function signOut(): Promise<void> {
  const stored = storage()?.getItem(REFRESH_KEY);
  setSession(null);
  if (stored) {
    try { await post("/api/v1/auth/logout", { refresh_token: stored }); } catch { /* best effort */ }
  }
}

/** Called by the API layer when the server rejects a token that looked valid here. */
export function sessionRejected(): void {
  setSession(null);
}

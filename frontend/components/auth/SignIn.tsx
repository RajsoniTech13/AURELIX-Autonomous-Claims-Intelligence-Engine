"use client";

import { useEffect, useState } from "react";
import { Loader2, ShieldCheck } from "lucide-react";
import { API_URL } from "@/lib/config";
import { signIn, signInDemo } from "@/lib/auth";

/**
 * The sign-in screen.
 *
 * For the public demo the main path is one click: "Explore as a claimant" creates a fresh
 * claimant account for this visitor alone, so their claims are invisible to everyone else;
 * "Explore as a reviewer" opens the reviewer workspace. Password accounts are seeded by the
 * operator; their form is shown only when demo sign-in is switched off.
 *
 * The API runs on a free instance that sleeps when idle, so the first request after a quiet
 * spell can take ~50 seconds. The screen says so, instead of looking broken while it waits.
 */
type Config = { demo_login: boolean; demo_roles: string[] };

export function SignIn() {
  const [config, setConfig] = useState<Config | null>(null);
  const [waking, setWaking] = useState(false);
  const [unreachable, setUnreachable] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    let live = true;
    const slow = setTimeout(() => live && setWaking(true), 2500);
    fetch(`${API_URL}/api/v1/auth/config`)
      .then((r) => r.json())
      .then((c) => live && setConfig(c))
      .catch(() => live && setUnreachable(true))
      .finally(() => { clearTimeout(slow); if (live) setWaking(false); });
    return () => { live = false; clearTimeout(slow); };
  }, []);

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (e: any) {
      setError(e?.message ?? "Sign-in failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center px-4 py-10 bg-background">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 mb-6">
          <div className="h-8 w-8 rounded bg-(--aurelix-accent-weak) border border-(--aurelix-accent-line) flex items-center justify-center">
            <ShieldCheck className="h-4 w-4 text-(--aurelix-accent)" aria-hidden />
          </div>
          <div>
            <div className="text-[15px] font-semibold tracking-tight leading-none">AURELIX</div>
            <div className="text-[12px] text-muted-foreground mt-1">Claims verification</div>
          </div>
        </div>

        <div className="rounded-lg border border-line bg-surface-1 p-5 space-y-5">
          <div>
            <h1 className="text-[15px] font-semibold tracking-tight">Sign in</h1>
            <p className="text-[12px] text-muted-foreground mt-1 leading-relaxed">
              This is a demonstration system. Do not upload real personal or insurance documents.
            </p>
          </div>

          {!config && !unreachable && (
            <div className="flex items-center gap-2 text-[12px] text-muted-foreground" role="status">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              {waking
                ? "Waking the analysis service — free-tier instances sleep when idle, this can take up to a minute."
                : "Connecting…"}
            </div>
          )}

          {unreachable && (
            <p className="text-[12px] text-(--state-contra) leading-relaxed" role="alert">
              The analysis service at {API_URL} could not be reached. It may be starting up — try again in a minute.
            </p>
          )}

          {config?.demo_login && (
            <div className="space-y-2">
              {(["claimant", "reviewer"] as const).map((role) => (
                <button
                  key={role}
                  type="button"
                  disabled={busy !== null}
                  onClick={() => run(role, () => signInDemo(role))}
                  className={`w-full h-9 rounded-md text-[13px] font-medium inline-flex items-center justify-center gap-2
                              transition-colors duration-(--dur-fast) disabled:opacity-60
                              ${role === "claimant"
                                ? "bg-(--aurelix-accent) hover:bg-(--aurelix-accent-hover) text-(--primary-foreground)"
                                : "border border-line hover:bg-surface-2"}`}
                >
                  {busy === role && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                  {role === "claimant" ? "Explore as a claimant" : "Explore as a reviewer"}
                </button>
              ))}
              <p className="text-[11px] text-muted-foreground leading-relaxed">
                A claimant sees only the claims they submit. A reviewer sees every claim, decides
                escalated ones and can ask the Policy Copilot.
              </p>
            </div>
          )}

          {/* The password form is for operator-seeded accounts. While the one-click demo is
              on, visitors have no account, so offering it only looks like a wall; it appears
              when demo sign-in is switched off (AURELIX_DEMO_LOGIN=0), so there is always a
              way in. */}
          {config && !config.demo_login && (
            <form
              onSubmit={(e) => { e.preventDefault(); run("password", () => signIn(username.trim(), password)); }}
              className="space-y-2.5"
            >
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="Username"
                aria-label="Username"
                className="w-full h-9 rounded-md bg-surface-2 border border-line px-3 text-[13px] focus:border-(--aurelix-accent-line)"
              />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="Password"
                aria-label="Password"
                className="w-full h-9 rounded-md bg-surface-2 border border-line px-3 text-[13px] focus:border-(--aurelix-accent-line)"
              />
              <button
                type="submit"
                disabled={busy !== null || !username.trim() || !password}
                className="w-full h-9 rounded-md border border-line hover:bg-surface-2 text-[13px] font-medium
                           inline-flex items-center justify-center gap-2 disabled:opacity-60"
              >
                {busy === "password" && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />}
                Sign in
              </button>
            </form>
          )}

          {error && <p className="text-[12px] text-(--state-contra) leading-relaxed" role="alert">{error}</p>}
        </div>
      </div>
    </div>
  );
}

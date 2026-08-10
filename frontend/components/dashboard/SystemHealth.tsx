"use client";

import { useEffect, useState } from "react";
import { Activity, Database, KeyRound } from "lucide-react";
import { getHealth, API_URL } from "@/lib/api";

type Health = { ready: boolean; checks: Record<string, string> };

/**
 * The header status strip, backed by `GET /ready`.
 *
 * It replaces three hardcoded strings that always read green. That mattered more than it
 * looks: the first thing anyone does when a submission fails is glance at the header, and
 * a fabricated "all systems healthy" sends them to debug the wrong half of the stack. The
 * most common real failure — a free-tier backend asleep, or a missing API key — is exactly
 * what this now shows.
 */
export function SystemHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [latency, setLatency] = useState<number | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let cancelled = false;

    const probe = async () => {
      const started = performance.now();
      try {
        const data = await getHealth();
        if (cancelled) return;
        setHealth(data);
        setLatency(Math.round(performance.now() - started));
        setDown(false);
      } catch {
        if (cancelled) return;
        setDown(true);
        setLatency(null);
      }
    };

    probe();
    const timer = setInterval(probe, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const dbOk = health?.checks?.database === "ok";
  const keyOk = health?.checks?.gemini_key === "present";

  const tone = (ok: boolean) => (ok ? "text-emerald-500" : "text-destructive");

  return (
    <div
      className="hidden lg:flex items-center space-x-3 border-r border-border/50 pr-4"
      title={down ? `No response from ${API_URL}` : API_URL}
    >
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
        <Activity className={`h-3 w-3 ${down ? "text-destructive" : tone(!!health?.ready)}`} />
        API:{" "}
        <span className={`font-mono ${down ? "text-destructive" : "text-foreground"}`}>
          {down ? "offline" : latency !== null ? `${latency}ms` : "…"}
        </span>
      </div>
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
        <Database className={`h-3 w-3 ${down ? "text-muted-foreground" : tone(dbOk)}`} />
        DB: <span className="text-foreground font-mono">{down ? "—" : dbOk ? "ok" : "down"}</span>
      </div>
      <div className="flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground">
        <KeyRound
          className={`h-3 w-3 ${down ? "text-muted-foreground" : keyOk ? "text-emerald-500" : "text-amber-500"}`}
        />
        Gemini:{" "}
        <span className={`font-mono ${keyOk ? "text-foreground" : "text-amber-500"}`}>
          {down ? "—" : keyOk ? "keyed" : "no key"}
        </span>
      </div>
    </div>
  );
}

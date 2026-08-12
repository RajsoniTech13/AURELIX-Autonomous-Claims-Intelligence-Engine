"use client";

import { useEffect, useState } from "react";
import { getHealth, API_URL } from "@/lib/api";
import { StatusDot } from "@/components/ui/status";

type Health = { ready: boolean; checks: Record<string, string> };

/**
 * Top-bar system status, backed by `GET /ready`.
 *
 * It replaced three hardcoded strings that always read green — "Gemini: 100%",
 * "Redis: 2ms", "API: 14ms". That mattered more than it looks: the first thing
 * anyone does when a submission fails is glance at the header, and a fabricated
 * "all healthy" sends them to debug the wrong half of the stack.
 *
 * Presented as small dot + label + tabular figure rather than coloured chips, so
 * it reads as instrumentation and never competes with the workspace.
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
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  const dbOk = health?.checks?.database === "ok";
  const keyed = health?.checks?.gemini_key === "present";

  const items: { label: string; value: string; tone: "verified" | "warning" | "contra" | "unknown" }[] = down
    ? [{ label: "API", value: "unreachable", tone: "contra" }]
    : [
        {
          label: "API",
          value: latency !== null ? `${latency}ms` : "—",
          tone: health?.ready ? "verified" : "warning",
        },
        { label: "DB", value: dbOk ? "operational" : "degraded", tone: dbOk ? "verified" : "contra" },
        { label: "Gemini", value: keyed ? "connected" : "no key", tone: keyed ? "verified" : "warning" },
      ];

  return (
    <div
      className="flex items-center gap-3 sm:gap-4 shrink-0"
      title={down ? `No response from ${API_URL}` : API_URL}
    >
      {items.map((item, i) => (
        <div
          key={item.label}
          className={`flex items-center gap-1.5 ${i > 0 ? "hidden md:flex" : "flex"}`}
        >
          <StatusDot tone={item.tone} pulse={item.tone === "contra"} />
          <span className="label-meta">{item.label}</span>
          <span className="tnum text-[11px] text-text-2">{item.value}</span>
        </div>
      ))}
    </div>
  );
}

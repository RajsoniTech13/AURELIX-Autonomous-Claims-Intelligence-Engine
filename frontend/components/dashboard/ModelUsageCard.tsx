"use client";

import { useEffect, useState } from "react";
import { getLlmMetrics } from "@/lib/api";
import { Skeleton } from "@/components/ui/status";

/**
 * What the model calls behind the analytics actually cost.
 *
 * Every figure comes from `/api/v1/metrics/llm`, which computes it from recorded calls —
 * nothing here is estimated in the browser. Cost is the list-price equivalent: the free
 * tiers this deployment runs on bill $0, and the card says so rather than implying a spend.
 *
 * Fetches on its own so that a metrics failure leaves the rest of Analytics standing.
 */
type Quota = { model: string; used_today: number; limit_per_day: number; remaining_today: number };

function money(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  if (value === 0) return "$0";
  return value < 0.01 ? `$${value.toPrecision(2)}` : `$${value.toFixed(2)}`;
}

function ms(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

export function ModelUsageCard() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getLlmMetrics(7).then(setData).catch((e) => setError(e?.message ?? "Unavailable"));
  }, []);

  if (error) {
    return (
      <section className="rounded-lg border border-line bg-surface-1 p-5">
        <h2 className="text-[13px] font-semibold tracking-tight">Model usage</h2>
        <p className="text-[12px] text-muted-foreground mt-1">Model usage is unavailable: {error}</p>
      </section>
    );
  }
  if (!data) return <Skeleton className="h-40" />;

  const t = data.totals;
  const stats = [
    { label: "Model calls · 7d", value: t.calls, sub: `${t.failures} failed · ${t.cache_hits} from cache` },
    { label: "Latency p50 / p95", value: `${ms(data.latency_ms.p50)} / ${ms(data.latency_ms.p95)}`,
      sub: `${data.latency_ms.samples} successful calls` },
    { label: "Cost per claim", value: money(data.cost.per_claim_usd),
      sub: `list price · ${data.cost.claims_counted} claims` },
    { label: "Cache-hit rate", value: t.cache_hit_rate === null ? "—" : `${(t.cache_hit_rate * 100).toFixed(0)}%`,
      sub: "served with no model call" },
  ];

  return (
    <section className="rounded-lg border border-line bg-surface-1">
      <div className="px-5 pt-5">
        <h2 className="text-[13px] font-semibold tracking-tight">Model usage</h2>
        <p className="text-[12px] text-muted-foreground mt-1">
          Recorded per call. Costs are list-price equivalents; billed cost is $0 on the free tiers used.
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 mt-4 border-t border-line divide-x divide-y lg:divide-y-0 divide-line">
        {stats.map((s) => (
          <div key={s.label} className="px-4 sm:px-5 py-3.5 min-w-0">
            <div className="label-meta mb-2">{s.label}</div>
            <div className="tnum text-xl font-semibold tracking-tight leading-none">{s.value}</div>
            <div className="text-[11px] text-muted-foreground mt-2 truncate">{s.sub}</div>
          </div>
        ))}
      </div>

      <div className="border-t border-line px-5 py-4">
        <div className="label-meta mb-3">Gemini quota today</div>
        <ul className="space-y-2.5">
          {(data.quota as Quota[]).map((q) => {
            const pct = q.limit_per_day ? Math.min(100, (q.used_today / q.limit_per_day) * 100) : 0;
            return (
              <li key={q.model} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 items-center">
                <span className="font-mono text-[11px] text-text-2 truncate">{q.model}</span>
                <span className="tnum text-[11px] text-muted-foreground">
                  {q.used_today}/{q.limit_per_day}
                </span>
                <div className="col-span-2 h-1 rounded-full bg-surface-2 overflow-hidden">
                  <div
                    className={`h-full ${pct >= 90 ? "bg-(--state-contra)" : pct >= 60 ? "bg-(--state-warning)" : "bg-(--aurelix-accent)"}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </li>
            );
          })}
        </ul>
        {data.cost.pricing_as_of && (
          <p className="text-[11px] text-muted-foreground mt-3">Prices as of {data.cost.pricing_as_of}.</p>
        )}
      </div>
    </section>
  );
}

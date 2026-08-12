"use client";

import { useEffect, useState } from "react";
import { ArrowRight, FileText, Plus, AlertTriangle } from "lucide-react";
import { getAnalytics, getClaims } from "@/lib/api";
import {
  ConfidenceMeter, DecisionBadge, EmptyState, SectionTitle, Skeleton,
  StatusBadge, decisionTone, riskTone,
} from "@/components/ui/status";

/**
 * Relative time.
 *
 * Every row in this table used to say "Just now" — a literal string, so a claim
 * from last week and one from ten seconds ago were indistinguishable. The API
 * now sends an explicit UTC offset; without it `new Date()` reads the timestamp
 * as local time and every claim lands in the reader's own future, which is why
 * this tolerates a small negative skew rather than printing "in 5 hours".
 */
function relativeTime(iso?: string | null): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (Math.abs(seconds) < 45) return "just now";
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31557600], ["month", 2629800], ["week", 604800],
    ["day", 86400], ["hour", 3600], ["minute", 60],
  ];
  const fmt = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return fmt.format(-Math.round(seconds / size), unit);
  }
  return "just now";
}

/**
 * A KPI. Four numbers that describe the state of the claim book — not
 * "revenue", not invented growth percentages. Every value is read from
 * `/analytics`; the tiles that used to read "2.4s", "-120ms vs yesterday" and
 * "76.4%" were string literals.
 */
function Kpi({ label, value, sub, tone, onClick }: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "verified" | "contra" | "unknown" | "warning";
  onClick?: () => void;
}) {
  const accent =
    tone === "verified" ? "text-(--state-verified)"
    : tone === "contra" ? "text-(--state-contra)"
    : tone === "warning" ? "text-(--state-warning)"
    : "text-foreground";

  const Tag: any = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      className={`bg-surface-1 text-left px-4 sm:px-5 py-3.5 min-w-0 w-full
                  ${onClick ? "group cursor-pointer hover:bg-surface-2 transition-colors duration-(--dur-fast)" : ""}`}
    >
      <div className="label-meta mb-2">{label}</div>
      <div className={`tnum text-2xl font-semibold tracking-tight leading-none ${accent}`}>{value}</div>
      {sub && (
        <div className="text-[11px] text-muted-foreground mt-2 leading-none flex items-center gap-1">
          {sub}
          {onClick && (
            <ArrowRight className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity" aria-hidden />
          )}
        </div>
      )}
    </Tag>
  );
}

export function HomeDashboard({
  onNavigate,
  onSelectClaim,
}: {
  onNavigate: (tab: string) => void;
  onSelectClaim?: (claimId: number) => void;
}) {
  const [claims, setClaims] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      // Settled, not `all`: the table and the KPI strip fail independently, and
      // losing one should not blank the other.
      const [recent, analytics] = await Promise.allSettled([
        getClaims({ limit: 10 }),
        getAnalytics(),
      ]);
      if (recent.status === "fulfilled") setClaims(recent.value);
      else setError(recent.reason?.message ?? "Could not load recent investigations.");
      if (analytics.status === "fulfilled") setStats(analytics.value);
      setLoading(false);
    };
    load();
  }, []);

  const k = stats?.kpis;
  const total = k?.total_claims ?? 0;

  return (
    <div className="space-y-7">
      {/* ── Page header ────────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Claims Intelligence</h1>
          <p className="text-[13px] text-muted-foreground mt-1 max-w-xl leading-relaxed">
            Autonomous verification of damage claims. Every decision is produced by
            deterministic rules over model observations, and every rule is recorded.
          </p>
        </div>
        <button
          onClick={() => onNavigate("submit")}
          className="inline-flex items-center gap-2 h-9 px-3.5 rounded-md bg-(--aurelix-accent)
                     hover:bg-(--aurelix-accent-hover) text-(--primary-foreground) text-[13px]
                     font-medium transition-colors duration-(--dur-fast) shrink-0 self-start sm:self-auto"
        >
          <Plus className="h-4 w-4" aria-hidden /> New investigation
        </button>
      </div>

      {/*
        KPI band.

        `divide-x divide-y` on a wrapping grid draws dividers per DOM order, not
        per visual position — at two columns that left a border hanging off the
        first cell and none under the last, which is the mess in the 2×2 layout.
        A 1px gap over a line-coloured background paints the separators from the
        grid itself, so it is correct at any column count.
      */}
      <div className="rounded-lg border border-line bg-line overflow-hidden">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-px">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-surface-1 px-4 sm:px-5 py-3.5">
                <Skeleton className="h-2.5 w-20 mb-3" />
                <Skeleton className="h-6 w-14" />
              </div>
            ))
          ) : (
            <>
              <Kpi
                label="Investigations"
                value={total}
                sub={`${k?.pending_review_claims ?? 0} awaiting review`}
              />
              <Kpi
                label="Supported"
                value={k?.supported_claims ?? 0}
                tone="verified"
                sub={total ? `${Math.round(((k?.supported_claims ?? 0) / total) * 100)}% of total` : "—"}
              />
              <Kpi
                label="Contradicted"
                value={k?.contradicted_claims ?? 0}
                tone="contra"
                sub={total ? `${Math.round(((k?.contradicted_claims ?? 0) / total) * 100)}% of total` : "—"}
              />
              <Kpi
                label="Insufficient evidence"
                value={k?.not_enough_info_claims ?? 0}
                sub={`avg confidence ${k?.average_confidence ?? 0}%`}
              />
            </>
          )}
        </div>
      </div>

      {/* ── Recent investigations ──────────────────────────────────────── */}
      <section>
        <SectionTitle
          action={
            claims.length > 0 && (
              <button
                onClick={() => onNavigate("queue")}
                className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1
                           transition-colors duration-(--dur-fast)"
              >
                Review queue <ArrowRight className="h-3 w-3" aria-hidden />
              </button>
            )
          }
        >
          Recent investigations
        </SectionTitle>

        <div className="rounded-lg border border-line bg-surface-1 overflow-hidden">
          {loading ? (
            <div className="divide-y divide-line">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 px-4 py-3">
                  <Skeleton className="h-3 w-16" />
                  <Skeleton className="h-3 flex-1 max-w-[220px]" />
                  <Skeleton className="h-3 w-24 ml-auto" />
                </div>
              ))}
            </div>
          ) : error ? (
            <EmptyState
              icon={AlertTriangle}
              title="Could not load investigations"
              description={error}
            />
          ) : claims.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No investigations yet"
              description="Start your first investigation to begin building the claims evidence record."
              action={
                <button
                  onClick={() => onNavigate("submit")}
                  className="inline-flex items-center gap-2 h-8 px-3 rounded-md bg-(--aurelix-accent)
                             hover:bg-(--aurelix-accent-hover) text-(--primary-foreground) text-[13px] font-medium
                             transition-colors duration-(--dur-fast)"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden /> New investigation
                </button>
              }
            />
          ) : (
            /* The table is wider than a phone. It scrolls inside its own
               container so the page never does — but a hard clip at the card
               edge reads as broken layout rather than as scrollable, so the
               right edge fades to signal there is more. */
            <div
              className="overflow-x-auto
                         [mask-image:linear-gradient(to_right,#000_calc(100%-28px),transparent)]
                         lg:[mask-image:none]"
            >
              <table className="w-full min-w-[760px] text-[13px]">
                <thead>
                  <tr className="border-b border-line">
                    {["Claim", "Policyholder", "Object", "Submitted", "Decision", "Confidence", "Review"].map(h => (
                      <th
                        key={h}
                        scope="col"
                        className="label-meta text-left font-medium px-4 py-2.5 whitespace-nowrap"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {claims.map(c => (
                    <tr
                      key={c.id}
                      tabIndex={0}
                      role="button"
                      onClick={() => onSelectClaim?.(c.id)}
                      onKeyDown={e => {
                        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelectClaim?.(c.id); }
                      }}
                      className="cursor-pointer hover:bg-surface-2/70 transition-colors duration-(--dur-fast)
                                 focus:outline-none focus-visible:bg-surface-2"
                    >
                      <td className="px-4 py-2.5 tnum font-medium whitespace-nowrap">
                        INV-{String(c.id).padStart(4, "0")}
                      </td>
                      <td className="px-4 py-2.5 text-text-2 whitespace-nowrap">{c.user_id}</td>
                      <td className="px-4 py-2.5 text-text-2 capitalize whitespace-nowrap">{c.claim_object}</td>
                      <td
                        className="px-4 py-2.5 text-muted-foreground whitespace-nowrap"
                        title={c.created_at ? new Date(c.created_at).toLocaleString() : ""}
                      >
                        {relativeTime(c.created_at)}
                      </td>
                      <td className="px-4 py-2.5"><DecisionBadge status={c.claim_status} /></td>
                      <td className="px-4 py-2.5"><ConfidenceMeter value={c.confidence_score} /></td>
                      <td className="px-4 py-2.5">
                        {c.manual_verdict ? (
                          <StatusBadge tone={c.manual_verdict === "approved" ? "verified" : "contra"}>
                            {c.manual_verdict === "approved" ? "Approved" : "Rejected"}
                          </StatusBadge>
                        ) : c.manual_review_required ? (
                          <StatusBadge tone="warning">Pending</StatusBadge>
                        ) : (
                          <span className="text-muted-foreground">Automatic</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

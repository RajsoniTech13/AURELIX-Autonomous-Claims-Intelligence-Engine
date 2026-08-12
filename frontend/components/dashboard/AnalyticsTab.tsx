"use client";

import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis,
} from "recharts";
import { Activity, AlertTriangle, Loader2, RefreshCw } from "lucide-react";
import { getAnalytics } from "@/lib/api";
import { EmptyState, SectionTitle, Skeleton } from "@/components/ui/status";

/**
 * Chart palette.
 *
 * One accent plus the semantic state colours — no rainbow, no gradients. A
 * category only gets a colour when the colour means something: supported is
 * green because supported is green everywhere in the product.
 */
const C = {
  accent: "oklch(0.66 0.145 274)",
  verified: "oklch(0.72 0.155 158)",
  warning: "oklch(0.79 0.150 78)",
  contra: "oklch(0.65 0.190 22)",
  unknown: "oklch(0.65 0.012 265)",
  grid: "oklch(0.30 0.008 265)",
  axis: "oklch(0.60 0.012 265)",
  surface: "oklch(0.221 0.008 265)",
};

const tooltipStyle = {
  background: C.surface,
  border: `1px solid ${C.grid}`,
  borderRadius: 6,
  fontSize: 12,
  padding: "6px 10px",
} as const;

function statusColour(status: string) {
  return status === "supported" ? C.verified
    : status === "contradicted" ? C.contra
    : C.unknown;
}

/** A chart panel. One consistent frame so the three charts read as a set. */
function Panel({ title, caption, children }: {
  title: string; caption?: string; children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-line bg-surface-1 p-5 min-w-0">
      <div className="mb-4">
        <h2 className="text-[13px] font-semibold tracking-tight">{title}</h2>
        {caption && <p className="text-[12px] text-muted-foreground mt-1">{caption}</p>}
      </div>
      {children}
    </section>
  );
}

export function AnalyticsTab() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const fetchStats = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await getAnalytics());
      setFetchedAt(new Date());
    } catch (err: any) {
      // This used to log to the console and leave the spinner up forever, so a
      // backend that was down looked identical to a slow request.
      setError(err?.message ?? "Could not load analytics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStats(); }, []);

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-24" />
        <div className="grid lg:grid-cols-3 gap-5">
          {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-64" />)}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <EmptyState
        icon={AlertTriangle}
        title="Analytics unavailable"
        description={error ?? "The analytics service returned no data."}
        action={
          <button
            onClick={fetchStats}
            className="h-8 px-3 rounded-md bg-(--aurelix-accent) hover:bg-(--aurelix-accent-hover)
                       text-(--primary-foreground) text-[13px] font-medium transition-colors duration-(--dur-fast)"
          >
            Try again
          </button>
        }
      />
    );
  }

  const k = data.kpis;

  if (!k?.total_claims) {
    return (
      <EmptyState
        icon={Activity}
        title="No claims analysed yet"
        description="Analytics appear once the first investigation completes."
      />
    );
  }

  const automationRate = (((k.total_claims - k.manual_review_claims) / k.total_claims) * 100).toFixed(1);
  const contradictionRate = ((k.contradicted_claims / k.total_claims) * 100).toFixed(1);
  const sufficiency = (((k.total_claims - k.not_enough_info_claims) / k.total_claims) * 100).toFixed(1);

  const decisions = (data.status_distribution ?? []).map((d: any) => ({
    name: d.status === "not_enough_information" ? "Insufficient"
      : d.status.charAt(0).toUpperCase() + d.status.slice(1),
    value: d.count,
    colour: statusColour(d.status),
  }));

  const fraud = (data.fraud_distribution ?? []).map((d: any) => ({ bucket: d.bucket, claims: d.count }));
  const volume = (data.claims_over_time ?? []).map((d: any) => ({ date: d.date, claims: d.claims }));

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Analytics</h1>
          <p className="text-[13px] text-muted-foreground mt-1">
            Decision, evidence and fraud metrics across every claim analysed.
          </p>
        </div>
        {/* Was a pulsing "Live Data Feed" badge on a page that fetches once. */}
        <div className="flex items-center gap-2.5 shrink-0">
          <span className="text-[12px] text-muted-foreground tnum">
            Updated {fetchedAt ? fetchedAt.toLocaleTimeString() : "—"}
          </span>
          <button
            onClick={fetchStats}
            className="h-8 px-2.5 inline-flex items-center gap-1.5 rounded-md border border-line
                       text-[12px] text-muted-foreground hover:text-foreground hover:bg-surface-2
                       transition-colors duration-(--dur-fast)"
          >
            <RefreshCw className="h-3 w-3" aria-hidden /> Refresh
          </button>
        </div>
      </div>

      {/* ── Rates. Each answers one question. ─────────────────────────── */}
      <div className="rounded-lg border border-line bg-surface-1">
        <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-y lg:divide-y-0 divide-line">
          {[
            { label: "Automation rate", value: `${automationRate}%`, sub: "resolved without a human" },
            { label: "Evidence sufficiency", value: `${sufficiency}%`, sub: "claims decidable from evidence" },
            { label: "Contradiction rate", value: `${contradictionRate}%`, sub: "evidence disputed the claim" },
            { label: "Awaiting review", value: k.pending_review_claims, sub: `of ${k.manual_review_claims} escalated` },
          ].map(m => (
            <div key={m.label} className="px-4 sm:px-5 py-3.5">
              <div className="label-meta mb-2">{m.label}</div>
              <div className="tnum text-2xl font-semibold tracking-tight leading-none">{m.value}</div>
              <div className="text-[11px] text-muted-foreground mt-2">{m.sub}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid lg:grid-cols-3 gap-5">
        <Panel title="Decision breakdown" caption="How the claim book resolved">
          <div className="h-[200px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={decisions}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={52}
                  outerRadius={78}
                  paddingAngle={2}
                  stroke="none"
                >
                  {decisions.map((d: any, i: number) => <Cell key={i} fill={d.colour} />)}
                </Pie>
                <RechartsTooltip contentStyle={tooltipStyle} itemStyle={{ color: "#fff" }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="mt-3 space-y-1.5">
            {decisions.map((d: any) => (
              <li key={d.name} className="flex items-center justify-between text-[12px]">
                <span className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: d.colour }} aria-hidden />
                  <span className="text-text-2">{d.name}</span>
                </span>
                <span className="tnum text-muted-foreground">{d.value}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Investigation volume" caption="Claims analysed per day">
          <div className="h-[268px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={volume} margin={{ top: 4, right: 8, bottom: 0, left: -22 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="date" stroke={C.axis} fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke={C.axis} fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} width={40} />
                <RechartsTooltip contentStyle={tooltipStyle} itemStyle={{ color: "#fff" }} />
                <Line
                  type="monotone" dataKey="claims" stroke={C.accent} strokeWidth={2}
                  dot={{ r: 2.5, fill: C.accent, strokeWidth: 0 }} activeDot={{ r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Fraud score distribution" caption="Objective signals, not model opinion">
          <div className="h-[268px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={fraud} margin={{ top: 4, right: 8, bottom: 0, left: -22 }}>
                <CartesianGrid stroke={C.grid} strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="bucket" stroke={C.axis} fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke={C.axis} fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} width={40} />
                <RechartsTooltip cursor={{ fill: "oklch(1 0 0 / 0.04)" }} contentStyle={tooltipStyle} itemStyle={{ color: "#fff" }} />
                <Bar dataKey="claims" radius={[3, 3, 0, 0]}>
                  {fraud.map((d: any, i: number) => (
                    <Cell
                      key={i}
                      fill={d.bucket === "81-100" ? C.contra : d.bucket === "51-80" ? C.warning : C.accent}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>
    </div>
  );
}

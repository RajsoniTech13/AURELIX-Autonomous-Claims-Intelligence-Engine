"use client";

import { useEffect, useState } from "react";
import { getAnalytics } from "@/lib/api";
import { Loader2, Activity, AlertTriangle, UserX, Zap, ShieldCheck, RefreshCw, PieChart as PieChartIcon } from "lucide-react";
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as RechartsTooltip, ResponsiveContainer, 
  PieChart, Pie, Cell, LineChart, Line, AreaChart, Area
} from "recharts";

const COLORS = {
  emerald: '#10b981',
  destructive: '#ef4444',
  amber: '#f59e0b',
  primary: '#6366f1',
  muted: '#3f3f46'
};

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
      // Previously logged to the console and left `loading` visually true, so a backend
      // that was down rendered a spinner that never resolved — indistinguishable from a
      // slow request, and with no way to retry short of a page reload.
      setError(err?.message ?? "Could not load analytics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStats(); }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground/30" />
        <p className="text-xs text-muted-foreground">Loading analytics…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center px-6">
        <AlertTriangle className="h-8 w-8 mb-3 text-destructive/60" />
        <p className="text-sm font-medium text-foreground">Analytics unavailable</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-md leading-relaxed">
          {error ?? "The analytics service returned no data."}
        </p>
        <button
          onClick={fetchStats}
          className="mt-4 text-xs bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-md font-medium transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  if (!data.kpis?.total_claims) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center px-6">
        <Activity className="h-8 w-8 mb-3 opacity-20" />
        <p className="text-sm font-medium text-foreground">No claims analysed yet</p>
        <p className="text-xs text-muted-foreground mt-1 max-w-sm">
          Analytics appear once the first investigation completes.
        </p>
      </div>
    );
  }

  const { kpis, status_distribution, claims_over_time } = data;

  // Was `supported / total`, which is an approval rate, sitting under the label
  // "Automation Rate — no human intervention required". The Overview tile computed the
  // same-named metric a different way, so the two screens disagreed. One definition:
  // the share of claims resolved without being escalated to a human.
  // One decimal, matching the Overview tile — the same metric rendered 61.5% on one
  // screen and 62% on the other purely from a different rounding call.
  const automationRate = kpis.total_claims
    ? (((kpis.total_claims - kpis.manual_review_claims) / kpis.total_claims) * 100).toFixed(1)
    : "0.0";

  // Formatting for Recharts
  const pieData = status_distribution.map((d: any) => ({
    name: d.status.charAt(0).toUpperCase() + d.status.slice(1),
    value: d.count,
    color: d.status === "supported" ? COLORS.emerald : d.status === "contradicted" ? COLORS.destructive : COLORS.amber
  }));

  return (
    <div className="space-y-8 pb-12 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-border/50 pb-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight mb-1">Platform Analytics</h2>
          <p className="text-sm text-muted-foreground">Decision, confidence and fraud metrics across every claim analysed.</p>
        </div>
        {/* This was a pulsing green "Live Data Feed" badge on a page that fetches once on
            mount. It now states when the figures were actually read, and offers the
            refresh the badge implied but never performed. */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground">
            Updated {fetchedAt ? fetchedAt.toLocaleTimeString() : "—"}
          </span>
          <button
            onClick={fetchStats}
            className="text-xs flex items-center gap-1.5 text-muted-foreground hover:text-foreground bg-muted/20 hover:bg-muted/40 px-3 py-1.5 rounded-md border border-border/50 transition-colors"
          >
            <RefreshCw className="h-3 w-3" /> Refresh
          </button>
        </div>
      </div>

      {/* Primary KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-card border border-border/50 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-muted-foreground">Total Processed</span>
            <Activity className="h-4 w-4 text-muted-foreground" />
          </div>
          <div className="text-3xl font-bold tracking-tight">{kpis.total_claims}</div>
          {/* Read "+12% vs last month". Nothing in this system stores a month-over-month
              comparison, so the figure was invented. Replaced with the breakdown the
              endpoint actually returns. */}
          <div className="text-xs text-muted-foreground mt-2">
            {kpis.supported_claims} supported · {kpis.contradicted_claims} contradicted ·{" "}
            {kpis.not_enough_info_claims} inconclusive
          </div>
        </div>
        
        <div className="bg-card border border-border/50 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-muted-foreground">Automation Rate</span>
            <Zap className="h-4 w-4 text-emerald-500" />
          </div>
          <div className="text-3xl font-bold tracking-tight text-emerald-500">{automationRate}%</div>
          <div className="text-xs text-muted-foreground mt-2">
            No human intervention required
          </div>
        </div>

        <div className="bg-card border border-border/50 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-muted-foreground">Avg Confidence</span>
            <ShieldCheck className="h-4 w-4 text-primary" />
          </div>
          <div className="text-3xl font-bold tracking-tight text-primary">{kpis.average_confidence}%</div>
          <div className="text-xs text-muted-foreground mt-2">
            AI decision certainty
          </div>
        </div>

        <div className="bg-card border border-border/50 rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <span className="text-sm font-medium text-muted-foreground">Escalation Queue</span>
            <UserX className="h-4 w-4 text-amber-500" />
          </div>
          <div className="text-3xl font-bold tracking-tight text-amber-500">{kpis.pending_review_claims}</div>
          <div className="text-xs text-muted-foreground mt-2">
            Pending manual review
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Charts: Decision Distribution */}
        <div className="bg-card border border-border/50 rounded-lg p-5 col-span-1">
          <div className="flex items-center gap-2 mb-6 border-b border-border/50 pb-4">
            <PieChartIcon className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Decision Breakdown</h3>
          </div>
          <div className="h-[250px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                  stroke="none"
                >
                  {pieData.map((entry: any, index: number) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <RechartsTooltip 
                  contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', borderRadius: '8px', fontSize: '12px' }}
                  itemStyle={{ color: '#fff' }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-col gap-2 mt-2">
            {pieData.map((d: any, i: number) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <div className="h-2 w-2 rounded-full" style={{ backgroundColor: d.color }} />
                  <span className="text-muted-foreground">{d.name}</span>
                </div>
                <span className="font-medium">{d.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Charts: Claims Over Time */}
        <div className="bg-card border border-border/50 rounded-lg p-5 col-span-1 lg:col-span-2">
          <div className="flex items-center gap-2 mb-6 border-b border-border/50 pb-4">
            <Activity className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">Investigation Volume (Last 30 Days)</h3>
          </div>
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={claims_over_time} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorClaims" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor={COLORS.primary} stopOpacity={0.3}/>
                    <stop offset="95%" stopColor={COLORS.primary} stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#27272a" />
                <XAxis dataKey="date" stroke="#a1a1aa" fontSize={10} tickLine={false} axisLine={false} />
                <YAxis stroke="#a1a1aa" fontSize={10} tickLine={false} axisLine={false} />
                <RechartsTooltip 
                  contentStyle={{ backgroundColor: '#18181b', borderColor: '#27272a', borderRadius: '8px', fontSize: '12px' }}
                  itemStyle={{ color: '#fff' }}
                />
                <Area type="monotone" dataKey="claims" stroke={COLORS.primary} strokeWidth={2} fillOpacity={1} fill="url(#colorClaims)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Removed: "Avg Pipeline Latency 2.4 sec", "Redis Cache Hit Rate 94.2%" and
          "Gemini API Success 99.9%". None of the three were measured anywhere — there is
          no latency timer, no cache-hit counter and no success-rate metric in the backend.
          Fabricated operational numbers on an analytics page are worse than none: they are
          exactly what a reader would trust without checking.

          Fraud-score distribution is real, comes from the same /analytics response, and is
          the operationally useful thing this row was occupying space with. */}
      <div className="bg-card border border-border/50 rounded-lg p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-4">
          Fraud Score Distribution
        </h3>
        <div className="h-[220px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={(data.fraud_distribution ?? []).map((d: any) => ({
              bucket: d.bucket, claims: d.count,
            }))}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.muted} vertical={false} />
              <XAxis dataKey="bucket" stroke="#71717a" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="#71717a" fontSize={12} tickLine={false} axisLine={false} allowDecimals={false} />
              <RechartsTooltip
                cursor={{ fill: "rgba(255,255,255,0.04)" }}
                contentStyle={{
                  background: "#18181b", border: "1px solid #27272a",
                  borderRadius: "8px", fontSize: "12px",
                }}
              />
              <Bar dataKey="claims" fill={COLORS.primary} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}

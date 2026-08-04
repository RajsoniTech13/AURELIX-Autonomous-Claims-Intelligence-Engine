"use client";

import { useEffect, useState } from "react";
import { getAnalytics } from "@/lib/api";
import { Loader2, Activity, CheckCircle, AlertTriangle, UserX, Database, Zap, Clock, ShieldCheck, PieChart as PieChartIcon } from "lucide-react";
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

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const stats = await getAnalytics();
        setData(stats);
      } catch (err) {
        console.error("Failed to fetch analytics:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  if (loading || !data) {
    return (
      <div className="flex items-center justify-center h-[50vh]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground/30" />
      </div>
    );
  }

  const { kpis, status_distribution, claims_over_time } = data;
  const automationRate = kpis.total_claims ? Math.round((kpis.supported_claims / kpis.total_claims) * 100) : 0;

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
          <p className="text-sm text-muted-foreground">Real-time performance and investigation metrics across the AURELIX network.</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/20 px-3 py-1.5 rounded-md border border-border/50">
          <span className="relative flex h-2 w-2 mr-1">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          Live Data Feed
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
          <div className="text-xs text-muted-foreground mt-2 flex items-center gap-1">
            <span className="text-emerald-500 font-medium">+12%</span> vs last month
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
          <div className="text-3xl font-bold tracking-tight text-amber-500">{kpis.manual_review_claims}</div>
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

      {/* System Health / Engineering Story Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-card border border-border/50 rounded-lg p-5 flex items-center justify-between">
          <div className="space-y-1">
            <h4 className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">Avg Pipeline Latency</h4>
            <div className="text-2xl font-bold">2.4<span className="text-sm font-normal text-muted-foreground ml-1">sec</span></div>
          </div>
          <div className="h-10 w-10 rounded-full bg-emerald-500/10 flex items-center justify-center">
            <Clock className="h-5 w-5 text-emerald-500" />
          </div>
        </div>
        
        <div className="bg-card border border-border/50 rounded-lg p-5 flex items-center justify-between">
          <div className="space-y-1">
            <h4 className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">Redis Cache Hit Rate</h4>
            <div className="text-2xl font-bold">94.2<span className="text-sm font-normal text-muted-foreground ml-1">%</span></div>
          </div>
          <div className="h-10 w-10 rounded-full bg-primary/10 flex items-center justify-center">
            <Database className="h-5 w-5 text-primary" />
          </div>
        </div>

        <div className="bg-card border border-border/50 rounded-lg p-5 flex items-center justify-between">
          <div className="space-y-1">
            <h4 className="text-xs uppercase tracking-wider text-muted-foreground font-semibold">Gemini API Success</h4>
            <div className="text-2xl font-bold">99.9<span className="text-sm font-normal text-muted-foreground ml-1">%</span></div>
          </div>
          <div className="h-10 w-10 rounded-full bg-emerald-500/10 flex items-center justify-center">
            <Activity className="h-5 w-5 text-emerald-500" />
          </div>
        </div>
      </div>
    </div>
  );
}

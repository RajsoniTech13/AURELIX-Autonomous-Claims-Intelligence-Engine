"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { 
  Activity, Clock, ShieldCheck, Zap, ArrowRight, 
  Search, AlertTriangle, CheckCircle2, UserX, FileText
} from "lucide-react";
import { getAnalytics, getClaims } from "@/lib/api";

/**
 * Every row in this table said "Just now" — a literal string, not a computed one, so a
 * claim from last week and one from ten seconds ago were indistinguishable.
 *
 * The API now sends an explicit UTC offset. Without it `new Date()` reads the timestamp as
 * local time and every claim lands in the reader's own future, which is why this needs to
 * tolerate a small negative skew rather than printing "in 5 hours".
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

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1 }
  }
};

const item = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0 }
};

export function HomeDashboard({
  onNavigate,
  onSelectClaim,
}: {
  onNavigate: (tab: string) => void;
  /** Open one claim's full investigation. Rows were styled as clickable and were not. */
  onSelectClaim?: (claimId: number) => void;
}) {
  const [claims, setClaims] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      // Settled, not `all`: the recent-claims table and the KPI strip fail independently,
      // and losing one should not blank the other.
      const [recent, analytics] = await Promise.allSettled([
        getClaims({ limit: 8 }),
        getAnalytics(),
      ]);
      if (recent.status === "fulfilled") setClaims(recent.value);
      else setError(recent.reason?.message ?? "Could not load recent investigations.");
      if (analytics.status === "fulfilled") setStats(analytics.value);
      setLoading(false);
    };
    load();
  }, []);

  const kpi = (pick: (k: any) => number) => (stats ? pick(stats.kpis) : "—");

  const automationRate =
    stats && stats.kpis.total_claims > 0
      ? ((stats.kpis.total_claims - stats.kpis.manual_review_claims) /
          stats.kpis.total_claims) *
        100
      : null;

  const getStatusIcon = (status: string) => {
    switch(status) {
      case "supported": return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
      case "contradicted": return <AlertTriangle className="h-4 w-4 text-destructive" />;
      case "not_enough_information": return <UserX className="h-4 w-4 text-amber-500" />;
      default: return <Activity className="h-4 w-4 text-muted-foreground" />;
    }
  };

  return (
    <motion.div 
      variants={container}
      initial="hidden"
      animate="show"
      className="space-y-8"
    >
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <motion.h1 variants={item} className="text-2xl font-semibold tracking-tight mb-1">
            Welcome back, System Admin
          </motion.h1>
          <motion.p variants={item} className="text-sm text-muted-foreground">
            AURELIX AI Orchestration Platform is online and processing claims.
          </motion.p>
        </div>
        <motion.div variants={item} className="flex items-center gap-3">
          <button 
            onClick={() => onNavigate("submit")}
            className="flex items-center gap-2 bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-md text-sm font-medium transition-colors shadow-sm"
          >
            <Zap className="h-4 w-4" />
            New Investigation
          </button>
        </motion.div>
      </div>

      {/* Every tile here read from a string literal: "2.4s", "-120ms vs yesterday",
          "76.4%", "14". They are now computed from GET /analytics. A claims product that
          invents its own operating numbers is the same failure as one that invents a
          verdict, just further from the eye. */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <motion.div variants={item} className="bg-card border border-border/50 rounded-lg p-5 group hover:border-border transition-colors">
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Claims Analysed</span>
            <FileText className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
          </div>
          <div className="text-2xl font-bold tracking-tight">{kpi(k => k.total_claims)}</div>
          <div className="text-xs text-muted-foreground mt-2">
            {stats ? `${stats.kpis.supported_claims} supported · ${stats.kpis.contradicted_claims} contradicted` : "—"}
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-card border border-border/50 rounded-lg p-5 group hover:border-border transition-colors">
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Automation Rate</span>
            <Activity className="h-4 w-4 text-muted-foreground group-hover:text-emerald-500 transition-colors" />
          </div>
          <div className="text-2xl font-bold tracking-tight text-emerald-500">
            {automationRate === null ? "—" : `${automationRate.toFixed(1)}%`}
          </div>
          <div className="text-xs text-muted-foreground mt-2">
            Resolved without human review
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-card border border-border/50 rounded-lg p-5 group hover:border-border transition-colors cursor-pointer" onClick={() => onNavigate("queue")}>
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Manual Review</span>
            <ShieldCheck className="h-4 w-4 text-amber-500" />
          </div>
          <div className="text-2xl font-bold tracking-tight text-amber-500">{kpi(k => k.pending_review_claims)}</div>
          <div className="text-xs text-muted-foreground mt-2 flex items-center gap-1 hover:text-foreground transition-colors">
            View queue <ArrowRight className="h-3 w-3" />
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-card border border-border/50 rounded-lg p-5 group hover:border-border transition-colors cursor-pointer" onClick={() => onNavigate("analytics")}>
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Avg Confidence</span>
            <Zap className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
          </div>
          <div className="text-2xl font-bold tracking-tight">
            {stats ? `${stats.kpis.average_confidence}%` : "—"}
          </div>
          <div className="text-xs text-muted-foreground mt-2 flex items-center gap-1 hover:text-foreground transition-colors">
            View system metrics <ArrowRight className="h-3 w-3" />
          </div>
        </motion.div>
      </div>

      <motion.div variants={item} className="bg-card border border-border/50 rounded-lg overflow-hidden">
        <div className="px-5 py-4 border-b border-border/50 flex items-center justify-between">
          <h3 className="text-sm font-medium">Recent Investigations</h3>
          <button 
            onClick={() => onNavigate("review")}
            className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
          >
            View all <ArrowRight className="h-3 w-3" />
          </button>
        </div>
        
        {loading ? (
          <div className="p-8 text-center text-sm text-muted-foreground">Loading investigations…</div>
        ) : error ? (
          // The fetch error was captured into state and never rendered, so a backend that
          // was down produced an empty table indistinguishable from "no claims yet".
          <div className="p-8 text-center flex flex-col items-center">
            <AlertTriangle className="h-8 w-8 mb-3 text-destructive/60" />
            <p className="text-sm font-medium text-foreground">Could not load investigations</p>
            <p className="text-xs text-muted-foreground mt-1 max-w-md leading-relaxed">{error}</p>
          </div>
        ) : claims.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground flex flex-col items-center">
            <FileText className="h-8 w-8 mb-3 opacity-20" />
            No recent investigations found.
          </div>
        ) : (
          <div className="divide-y divide-border/30">
            <div className="grid grid-cols-12 gap-4 px-5 py-3 bg-muted/10 text-xs font-medium text-muted-foreground uppercase tracking-wider">
              <div className="col-span-2">ID / Time</div>
              <div className="col-span-4">Object</div>
              <div className="col-span-3">Decision</div>
              <div className="col-span-2">Confidence</div>
              <div className="col-span-1 text-right">Escalated</div>
            </div>
            {claims.map((claim) => (
              <div
                key={claim.id}
                onClick={() => onSelectClaim?.(claim.id)}
                className="grid grid-cols-12 gap-4 px-5 py-3 items-center text-sm hover:bg-muted/5 transition-colors cursor-pointer"
              >
                <div className="col-span-2 flex flex-col">
                  <span className="font-mono text-xs">INV-{claim.id.toString().padStart(4, '0')}</span>
                  <span
                    className="text-xs text-muted-foreground"
                    title={claim.created_at ? new Date(claim.created_at).toLocaleString() : ""}
                  >
                    {relativeTime(claim.created_at)}
                  </span>
                </div>
                <div className="col-span-4 flex items-center gap-3">
                  <div className="h-8 w-8 rounded bg-muted/20 border border-border/50 flex items-center justify-center shrink-0">
                    <Search className="h-3.5 w-3.5 text-muted-foreground" />
                  </div>
                  <div className="flex flex-col truncate">
                    <span className="font-medium truncate">{claim.claim_object.charAt(0).toUpperCase() + claim.claim_object.slice(1)}</span>
                    <span className="text-xs text-muted-foreground truncate">{claim.user_id}</span>
                  </div>
                </div>
                <div className="col-span-3 flex items-center gap-2">
                  {getStatusIcon(claim.claim_status)}
                  <span className="capitalize">{claim.claim_status.replace(/_/g, ' ')}</span>
                </div>
                <div className="col-span-2 flex items-center gap-2">
                  <div className="h-1.5 w-16 bg-muted rounded-full overflow-hidden">
                    <div 
                      className={`h-full ${claim.confidence_score >= 90 ? 'bg-emerald-500' : claim.confidence_score >= 70 ? 'bg-amber-500' : 'bg-destructive'}`}
                      style={{ width: `${claim.confidence_score}%` }}
                    />
                  </div>
                  <span className="text-xs font-medium">{claim.confidence_score}%</span>
                </div>
                <div className="col-span-1 text-right">
                  {claim.manual_review_required ? (
                    <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-amber-500/10 text-amber-500">
                      <ShieldCheck className="h-3 w-3" />
                    </span>
                  ) : (
                    <span className="text-muted-foreground">-</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </motion.div>
    </motion.div>
  );
}

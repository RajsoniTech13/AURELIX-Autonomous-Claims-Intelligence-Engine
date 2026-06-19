"use client";

import React, { useState, useEffect } from "react";
import {
  LayoutDashboard,
  FileText,
  ShieldAlert,
  BarChart3,
  Search,
  Filter,
  CheckCircle,
  XCircle,
  AlertCircle,
  Clock,
  ArrowRight,
  TrendingUp,
  FileSearch,
  RefreshCw,
  User,
  Image as ImageIcon,
  Shield,
  Layers,
  ChevronRight,
  FileJson
} from "lucide-react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  BarChart,
  Bar,
  Cell,
  PieChart,
  Pie
} from "recharts";

const API_BASE_URL = "http://localhost:8000";

export default function AurelixDashboard() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [claims, setClaims] = useState<any[]>([]);
  const [queue, setQueue] = useState<any[]>([]);
  const [analytics, setAnalytics] = useState<any>({
    kpis: {
      total_claims: 0,
      supported_claims: 0,
      contradicted_claims: 0,
      not_enough_info_claims: 0,
      manual_review_claims: 0,
      average_confidence: 0
    },
    status_distribution: [],
    object_distribution: [],
    severity_distribution: [],
    confidence_distribution: [],
    fraud_distribution: [],
    claims_over_time: []
  });
  const [selectedClaim, setSelectedClaim] = useState<any | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  
  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [objectFilter, setObjectFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState("all");
  
  // Manual reviewer inputs
  const [reviewerNotes, setReviewerNotes] = useState("");
  
  const fetchAllData = async () => {
    setIsRefreshing(true);
    try {
      // 1. Fetch claims list
      const claimsRes = await fetch(`${API_BASE_URL}/claims`);
      if (claimsRes.ok) {
        const claimsData = await claimsRes.json();
        setClaims(claimsData);
      }
      
      // 2. Fetch manual review queue
      const queueRes = await fetch(`${API_BASE_URL}/queue`);
      if (queueRes.ok) {
        const queueData = await queueRes.json();
        setQueue(queueData);
      }
      
      // 3. Fetch analytics
      const analyticsRes = await fetch(`${API_BASE_URL}/analytics`);
      if (analyticsRes.ok) {
        const analyticsData = await analyticsRes.json();
        setAnalytics(analyticsData);
      }
    } catch (error) {
      printError("Failed to fetch data from backend. Make sure the FastAPI backend is running on port 8000.", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  const printError = (msg: string, err: any) => {
    console.error(msg, err);
  };

  useEffect(() => {
    fetchAllData();
  }, []);
  
  // Auto-refresh when active tab changes
  useEffect(() => {
    if (selectedClaim) {
      // Re-fetch selected claim from updated claims list
      const updated = claims.find((c) => c.id === selectedClaim.id);
      if (updated) setSelectedClaim(updated);
    }
  }, [claims]);

  const handleManualVerdict = async (claimId: number, verdict: "approved" | "rejected") => {
    try {
      const res = await fetch(`${API_BASE_URL}/queue/${claimId}/verdict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict, notes: reviewerNotes })
      });
      if (res.ok) {
        setReviewerNotes("");
        // Reload everything
        await fetchAllData();
        // Clear details overlay or update selected claim state
        setSelectedClaim(null);
      } else {
        alert("Failed to submit manual review decision.");
      }
    } catch (e) {
      console.error(e);
      alert("Error submitting verdict.");
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "supported":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle className="w-3.5 h-3.5" /> Supported
          </span>
        );
      case "contradicted":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-red-500/10 text-red-400 border border-red-500/20">
            <XCircle className="w-3.5 h-3.5" /> Contradicted
          </span>
        );
      case "not_enough_information":
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <AlertCircle className="w-3.5 h-3.5" /> Not Enough Info
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-slate-500/10 text-slate-400 border border-slate-500/20">
            <Clock className="w-3.5 h-3.5" /> Under Review
          </span>
        );
    }
  };

  const getConfidenceBadge = (score: number) => {
    if (score >= 90) {
      return <span className="text-xs font-semibold text-emerald-400">{score}%</span>;
    } else if (score >= 70) {
      return <span className="text-xs font-semibold text-amber-400">{score}%</span>;
    } else {
      return <span className="text-xs font-semibold text-red-400">{score}%</span>;
    }
  };

  const getFraudBadge = (score: number) => {
    if (score > 60) {
      return <span className="inline-flex px-2 py-0.5 rounded text-xs font-bold bg-red-500/10 text-red-400 border border-red-500/20">{score}/100</span>;
    } else if (score > 30) {
      return <span className="inline-flex px-2 py-0.5 rounded text-xs font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">{score}/100</span>;
    } else {
      return <span className="inline-flex px-2 py-0.5 rounded text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">{score}/100</span>;
    }
  };

  const getSeverityBadge = (sev: string) => {
    switch (sev.toLowerCase()) {
      case "high":
        return <span className="text-xs font-semibold text-red-400 bg-red-500/10 px-2 py-0.5 rounded border border-red-500/20">High</span>;
      case "medium":
        return <span className="text-xs font-semibold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/20">Medium</span>;
      case "low":
        return <span className="text-xs font-semibold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">Low</span>;
      default:
        return <span className="text-xs font-semibold text-slate-400 bg-slate-500/10 px-2 py-0.5 rounded border border-slate-500/20">None</span>;
    }
  };

  // Filtered claims
  const filteredClaims = claims.filter((c) => {
    const matchesSearch =
      c.user_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      c.user_claim.toLowerCase().includes(searchQuery.toLowerCase());
      
    const matchesStatus = statusFilter === "all" || c.claim_status === statusFilter;
    const matchesObject = objectFilter === "all" || c.claim_object === objectFilter;
    
    let matchesRisk = true;
    if (riskFilter === "high") {
      matchesRisk = c.fraud_score > 60 || c.user_risk_score > 60;
    } else if (riskFilter === "medium") {
      matchesRisk = (c.fraud_score > 30 && c.fraud_score <= 60) || (c.user_risk_score > 30 && c.user_risk_score <= 60);
    } else if (riskFilter === "low") {
      matchesRisk = c.fraud_score <= 30 && c.user_risk_score <= 30;
    }
    
    return matchesSearch && matchesStatus && matchesObject && matchesRisk;
  });

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground font-sans">
      {/* Sidebar Navigation */}
      <aside className="w-64 border-r border-border bg-[#090a0c] flex flex-col justify-between p-6">
        <div>
          {/* Logo */}
          <div className="flex items-center gap-2 mb-8">
            <div className="p-2 bg-primary/20 text-primary rounded-lg border border-primary/30">
              <Shield className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-white">AURELIX</h1>
              <p className="text-[10px] text-muted tracking-widest uppercase font-mono">Trust Intelligence</p>
            </div>
          </div>
          
          {/* Menu */}
          <nav className="space-y-1">
            <button
              onClick={() => { setActiveTab("dashboard"); setSelectedClaim(null); }}
              className={`w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors ${
                activeTab === "dashboard"
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted hover:text-white hover:bg-card/50"
              }`}
            >
              <LayoutDashboard className="w-4 h-4" />
              Dashboard
            </button>
            
            <button
              onClick={() => { setActiveTab("claims"); setSelectedClaim(null); }}
              className={`w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors ${
                activeTab === "claims"
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted hover:text-white hover:bg-card/50"
              }`}
            >
              <FileText className="w-4 h-4" />
              Claims Database
            </button>
            
            <button
              onClick={() => { setActiveTab("queue"); setSelectedClaim(null); }}
              className={`w-full flex items-center justify-between px-3 py-2 text-sm font-medium rounded-lg transition-colors ${
                activeTab === "queue"
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted hover:text-white hover:bg-card/50"
              }`}
            >
              <div className="flex items-center gap-3">
                <ShieldAlert className="w-4 h-4" />
                Human Queue
              </div>
              {queue.length > 0 && (
                <span className="px-1.5 py-0.5 rounded text-[10px] bg-danger/20 text-danger border border-danger/30 font-bold">
                  {queue.length}
                </span>
              )}
            </button>
            
            <button
              onClick={() => { setActiveTab("analytics"); setSelectedClaim(null); }}
              className={`w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-lg transition-colors ${
                activeTab === "analytics"
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted hover:text-white hover:bg-card/50"
              }`}
            >
              <BarChart3 className="w-4 h-4" />
              Analytics
            </button>
          </nav>
        </div>
        
        {/* Footer info */}
        <div className="border-t border-border pt-4 text-[11px] text-muted space-y-1">
          <p className="font-mono">Local Host: 8000</p>
          <div className="flex items-center justify-between">
            <span>Status: Online</span>
            <button
              onClick={fetchAllData}
              disabled={isRefreshing}
              className="text-primary hover:text-primary-hover p-1 rounded hover:bg-card"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>
      </aside>
      
      {/* Main Content Workspace */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-background">
        {/* Top Header */}
        <header className="h-16 border-b border-border bg-[#090a0c]/80 backdrop-blur flex items-center justify-between px-8 z-10">
          <div className="flex items-center gap-3">
            <h2 className="text-md font-semibold text-white capitalize">
              {activeTab === "queue" ? "Human Review Queue" : `${activeTab} Workspace`}
            </h2>
            {activeTab === "queue" && (
              <span className="text-xs text-muted">Review escalated claims and apply overrides.</span>
            )}
          </div>
          
          <div className="flex items-center gap-4">
            <button
              onClick={fetchAllData}
              className="flex items-center gap-2 px-3 py-1.5 text-xs bg-card hover:bg-card-hover border border-border text-white rounded-lg transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <div className="h-8 w-px bg-border"></div>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold text-xs border border-primary/30">
                A
              </div>
              <span className="text-xs font-medium text-white">Claims Officer</span>
            </div>
          </div>
        </header>
        
        {/* Dynamic Tab Body */}
        <div className="flex-1 overflow-y-auto p-8">
          
          {/* TAB 1: DASHBOARD VIEW */}
          {activeTab === "dashboard" && (
            <div className="space-y-8">
              {/* KPI Cards Grid */}
              <div className="grid grid-cols-5 gap-6">
                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Total Claims</p>
                  <h3 className="text-2xl font-bold text-white mt-2">{analytics.kpis.total_claims}</h3>
                  <div className="text-[10px] text-muted mt-1.5 flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3 text-primary" /> Active in database
                  </div>
                </div>
                
                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Supported</p>
                  <h3 className="text-2xl font-bold text-emerald-400 mt-2">{analytics.kpis.supported_claims}</h3>
                  <div className="text-[10px] text-emerald-500/80 mt-1.5 flex items-center gap-1 font-mono">
                    <CheckCircle className="w-3 h-3" /> Auto-verified claims
                  </div>
                </div>
                
                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Contradicted</p>
                  <h3 className="text-2xl font-bold text-red-400 mt-2">{analytics.kpis.contradicted_claims}</h3>
                  <div className="text-[10px] text-red-500/80 mt-1.5 flex items-center gap-1 font-mono">
                    <XCircle className="w-3 h-3" /> Visual evidence mismatch
                  </div>
                </div>
                
                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Human Queue</p>
                  <h3 className="text-2xl font-bold text-amber-400 mt-2">{queue.length}</h3>
                  <div className="text-[10px] text-amber-500/80 mt-1.5 flex items-center gap-1 font-mono">
                    <ShieldAlert className="w-3 h-3" /> Awaiting review
                  </div>
                </div>
                
                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Average Trust</p>
                  <h3 className="text-2xl font-bold text-primary mt-2">{analytics.kpis.average_confidence}%</h3>
                  <div className="text-[10px] text-primary mt-1.5 flex items-center gap-1 font-mono">
                    <TrendingUp className="w-3 h-3" /> Confidence rating
                  </div>
                </div>
              </div>
              
              {/* Claims Overview Chart & Recents */}
              <div className="grid grid-cols-3 gap-8">
                {/* Visual Analytics Preview */}
                <div className="col-span-2 bg-card border border-border rounded-xl p-6">
                  <div className="flex items-center justify-between mb-6">
                    <div>
                      <h4 className="text-sm font-bold text-white">Trust Intelligence Volume</h4>
                      <p className="text-xs text-muted mt-0.5">Claims ingest and decision distribution trend.</p>
                    </div>
                    <span className="text-xs text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded font-mono font-semibold">Realtime</span>
                  </div>
                  
                  <div className="h-64">
                    {analytics.claims_over_time.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={analytics.claims_over_time}>
                          <defs>
                            <linearGradient id="colorClaims" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.2}/>
                              <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0}/>
                            </linearGradient>
                          </defs>
                          <XAxis dataKey="date" stroke="#8e939e" fontSize={11} tickLine={false} axisLine={false} />
                          <YAxis stroke="#8e939e" fontSize={11} tickLine={false} axisLine={false} />
                          <Tooltip contentStyle={{ backgroundColor: "#13151a", borderColor: "#22252e", color: "#f4f4f7" }} />
                          <Area type="monotone" dataKey="claims" stroke="#8b5cf6" strokeWidth={2} fillOpacity={1} fill="url(#colorClaims)" />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-xs text-muted font-mono">
                        No processing records available yet. Submit or import claims.
                      </div>
                    )}
                  </div>
                </div>
                
                {/* Recent High Risk claims */}
                <div className="bg-card border border-border rounded-xl p-6 flex flex-col">
                  <h4 className="text-sm font-bold text-white mb-4">Risk & Fraud Alerts</h4>
                  <div className="flex-1 space-y-3 overflow-y-auto max-h-64 pr-2">
                    {claims.filter(c => c.fraud_score > 30).slice(0, 5).map((claim, idx) => (
                      <div
                        key={idx}
                        onClick={() => setSelectedClaim(claim)}
                        className="p-3 bg-background hover:bg-card-hover border border-border rounded-lg flex items-center justify-between cursor-pointer transition-colors"
                      >
                        <div className="min-w-0">
                          <p className="text-xs font-semibold text-white font-mono">{claim.user_id}</p>
                          <p className="text-[10px] text-muted truncate mt-0.5">{claim.claim_object.toUpperCase()} - {claim.issue_type}</p>
                        </div>
                        <div className="text-right">
                          <span className="text-[10px] block text-muted">Fraud Score</span>
                          <span className={`text-xs font-bold ${claim.fraud_score > 60 ? "text-red-400" : "text-amber-400"}`}>
                            {claim.fraud_score}/100
                          </span>
                        </div>
                      </div>
                    ))}
                    {claims.filter(c => c.fraud_score > 30).length === 0 && (
                      <div className="h-full flex items-center justify-center text-xs text-muted">
                        No active risk alerts detected.
                      </div>
                    )}
                  </div>
                </div>
              </div>
              
              {/* Recent claims table */}
              <div className="bg-card border border-border rounded-xl p-6">
                <div className="flex items-center justify-between mb-6">
                  <h4 className="text-sm font-bold text-white">Recent Claims Ingestion</h4>
                  <button
                    onClick={() => setActiveTab("claims")}
                    className="text-xs text-primary hover:text-primary-hover flex items-center gap-1 font-semibold"
                  >
                    View database <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
                
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-border text-muted uppercase font-mono tracking-wider">
                        <th className="pb-3 font-semibold">User ID</th>
                        <th className="pb-3 font-semibold">Object</th>
                        <th className="pb-3 font-semibold">Claimed Issue</th>
                        <th className="pb-3 font-semibold">Status</th>
                        <th className="pb-3 font-semibold text-right">Confidence</th>
                        <th className="pb-3 font-semibold text-right">Fraud Score</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/50 text-white">
                      {claims.slice(0, 5).map((claim, idx) => (
                        <tr
                          key={idx}
                          onClick={() => setSelectedClaim(claim)}
                          className="hover:bg-card-hover cursor-pointer transition-colors"
                        >
                          <td className="py-3 font-mono text-primary font-semibold">{claim.user_id}</td>
                          <td className="py-3 capitalize">{claim.claim_object}</td>
                          <td className="py-3 truncate max-w-xs text-muted">{claim.user_claim}</td>
                          <td className="py-3">{getStatusBadge(claim.claim_status)}</td>
                          <td className="py-3 text-right font-mono font-semibold">{getConfidenceBadge(claim.confidence_score)}</td>
                          <td className="py-3 text-right font-mono font-semibold">{getFraudBadge(claim.fraud_score)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
          
          {/* TAB 2: CLAIMS LIST VIEW */}
          {activeTab === "claims" && (
            <div className="space-y-6">
              {/* Search and Filters panel */}
              <div className="bg-card border border-border rounded-xl p-5 flex flex-wrap gap-4 items-center justify-between shadow-sm">
                <div className="flex items-center gap-3 bg-background border border-border px-3 py-2 rounded-lg max-w-md w-full">
                  <Search className="w-4 h-4 text-muted" />
                  <input
                    type="text"
                    placeholder="Search by User ID or claim text..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="bg-transparent border-none outline-none text-white text-xs w-full placeholder-muted"
                  />
                </div>
                
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex items-center gap-2 text-xs text-muted border border-border bg-background px-3 py-1.5 rounded-lg">
                    <Filter className="w-3.5 h-3.5" />
                    <span>Object:</span>
                    <select
                      value={objectFilter}
                      onChange={(e) => setObjectFilter(e.target.value)}
                      className="bg-transparent border-none outline-none text-white font-medium cursor-pointer"
                    >
                      <option value="all">All</option>
                      <option value="car">Car</option>
                      <option value="laptop">Laptop</option>
                      <option value="package">Package</option>
                    </select>
                  </div>
                  
                  <div className="flex items-center gap-2 text-xs text-muted border border-border bg-background px-3 py-1.5 rounded-lg">
                    <Filter className="w-3.5 h-3.5" />
                    <span>Verdict:</span>
                    <select
                      value={statusFilter}
                      onChange={(e) => setStatusFilter(e.target.value)}
                      className="bg-transparent border-none outline-none text-white font-medium cursor-pointer"
                    >
                      <option value="all">All</option>
                      <option value="supported">Supported</option>
                      <option value="contradicted">Contradicted</option>
                      <option value="not_enough_information">Not Enough Info</option>
                    </select>
                  </div>
                  
                  <div className="flex items-center gap-2 text-xs text-muted border border-border bg-background px-3 py-1.5 rounded-lg">
                    <Filter className="w-3.5 h-3.5" />
                    <span>Risk Level:</span>
                    <select
                      value={riskFilter}
                      onChange={(e) => setRiskFilter(e.target.value)}
                      className="bg-transparent border-none outline-none text-white font-medium cursor-pointer"
                    >
                      <option value="all">All</option>
                      <option value="high">High Risk</option>
                      <option value="medium">Medium Risk</option>
                      <option value="low">Low Risk</option>
                    </select>
                  </div>
                </div>
              </div>
              
              {/* Claims Database Table */}
              <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-border bg-card-hover text-muted uppercase font-mono tracking-wider">
                        <th className="py-4 px-6 font-semibold">User ID</th>
                        <th className="py-4 px-3 font-semibold">Object</th>
                        <th className="py-4 px-3 font-semibold">Claim Conversation</th>
                        <th className="py-4 px-3 font-semibold">Verdict</th>
                        <th className="py-4 px-3 font-semibold">Severity</th>
                        <th className="py-4 px-3 font-semibold text-right">Confidence</th>
                        <th className="py-4 px-3 font-semibold text-right">Fraud Score</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/50 text-white">
                      {filteredClaims.map((claim, idx) => (
                        <tr
                          key={idx}
                          onClick={() => setSelectedClaim(claim)}
                          className="hover:bg-card-hover cursor-pointer transition-colors"
                        >
                          <td className="py-3.5 px-6 font-mono text-primary font-semibold">{claim.user_id}</td>
                          <td className="py-3.5 px-3 capitalize">{claim.claim_object}</td>
                          <td className="py-3.5 px-3 truncate max-w-sm text-muted">{claim.user_claim}</td>
                          <td className="py-3.5 px-3">{getStatusBadge(claim.claim_status)}</td>
                          <td className="py-3.5 px-3">{getSeverityBadge(claim.severity)}</td>
                          <td className="py-3.5 px-3 text-right font-mono font-semibold">{getConfidenceBadge(claim.confidence_score)}</td>
                          <td className="py-3.5 px-3 text-right font-mono font-semibold">{getFraudBadge(claim.fraud_score)}</td>
                        </tr>
                      ))}
                      {filteredClaims.length === 0 && (
                        <tr>
                          <td colSpan={7} className="py-8 text-center text-muted font-mono">
                            No claims matching active filters.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
          
          {/* TAB 3: HUMAN REVIEW QUEUE */}
          {activeTab === "queue" && (
            <div className="space-y-6">
              <div className="bg-card border border-border rounded-xl p-6 shadow-sm">
                <h3 className="text-sm font-bold text-white mb-2">Manual Verification Queue</h3>
                <p className="text-xs text-muted leading-relaxed">
                  These claims were escalated because they fell below the auto-confidence threshold (70/100), had suspicious risk flags, 
                  or showed evidence of image manipulation. Assess the visual logs below to overrides or confirm agent status.
                </p>
              </div>
              
              <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-border bg-card-hover text-muted uppercase font-mono tracking-wider">
                        <th className="py-4 px-6 font-semibold">User ID</th>
                        <th className="py-4 px-3 font-semibold">Object</th>
                        <th className="py-4 px-3 font-semibold">Escalation Reason</th>
                        <th className="py-4 px-3 font-semibold">Confidence</th>
                        <th className="py-4 px-3 font-semibold">Fraud Score</th>
                        <th className="py-4 px-6 font-semibold text-right">Review Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/50 text-white">
                      {queue.map((claim, idx) => (
                        <tr
                          key={idx}
                          className="hover:bg-card-hover/40 transition-colors"
                        >
                          <td
                            className="py-4 px-6 font-mono text-primary font-semibold cursor-pointer"
                            onClick={() => setSelectedClaim(claim)}
                          >
                            {claim.user_id}
                          </td>
                          <td className="py-4 px-3 capitalize">{claim.claim_object}</td>
                          <td className="py-4 px-3 text-red-400 font-medium max-w-sm truncate">
                            {claim.escalation_reason}
                          </td>
                          <td className="py-4 px-3 font-mono font-semibold">{getConfidenceBadge(claim.confidence_score)}</td>
                          <td className="py-4 px-3 font-mono font-semibold">{getFraudBadge(claim.fraud_score)}</td>
                          <td className="py-4 px-6 text-right whitespace-nowrap space-x-2">
                            <button
                              onClick={() => { setSelectedClaim(claim); }}
                              className="px-2.5 py-1 text-[11px] bg-card hover:bg-card-hover border border-border rounded text-white font-medium"
                            >
                              Inspect
                            </button>
                            <button
                              onClick={() => handleManualVerdict(claim.id, "approved")}
                              className="px-2.5 py-1 text-[11px] bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 border border-emerald-500/30 rounded font-medium"
                            >
                              Approve
                            </button>
                            <button
                              onClick={() => handleManualVerdict(claim.id, "rejected")}
                              className="px-2.5 py-1 text-[11px] bg-red-500/20 hover:bg-red-500/30 text-red-400 border border-red-500/30 rounded font-medium"
                            >
                              Reject
                            </button>
                          </td>
                        </tr>
                      ))}
                      {queue.length === 0 && (
                        <tr>
                          <td colSpan={6} className="py-8 text-center text-muted font-mono">
                            Human review queue is currently empty. Excellent work!
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
          
          {/* TAB 4: ANALYTICS PAGE */}
          {activeTab === "analytics" && (
            <div className="space-y-8">
              {/* Metrics Grid */}
              <div className="grid grid-cols-2 gap-8">
                {/* 1. Decision Status distribution */}
                <div className="bg-card border border-border rounded-xl p-6">
                  <h4 className="text-sm font-bold text-white mb-4">Verdict Distribution</h4>
                  <div className="h-64 flex items-center justify-between">
                    <div className="w-1/2 h-full">
                      {analytics.status_distribution.length > 0 ? (
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={analytics.status_distribution}
                              dataKey="count"
                              nameKey="status"
                              cx="50%"
                              cy="50%"
                              innerRadius={60}
                              outerRadius={80}
                              paddingAngle={5}
                            >
                              {analytics.status_distribution.map((entry: any, index: number) => {
                                const colors = {
                                  supported: "#10b981",
                                  contradicted: "#ef4444",
                                  not_enough_information: "#f59e0b"
                                };
                                return <Cell key={`cell-${index}`} fill={(colors as any)[entry.status] || "#8b5cf6"} />;
                              })}
                            </Pie>
                            <Tooltip contentStyle={{ backgroundColor: "#13151a", borderColor: "#22252e", color: "#f4f4f7" }} />
                          </PieChart>
                        </ResponsiveContainer>
                      ) : (
                        <div className="h-full flex items-center justify-center text-xs text-muted font-mono">No Data</div>
                      )}
                    </div>
                    
                    <div className="w-1/2 space-y-3 pr-4">
                      {analytics.status_distribution.map((entry: any, idx: number) => {
                        const labels = {
                          supported: "Supported (Auto-Approved)",
                          contradicted: "Contradicted (Auto-Rejected)",
                          not_enough_information: "Insufficient Information"
                        };
                        const bgColors = {
                          supported: "bg-emerald-500",
                          contradicted: "bg-danger",
                          not_enough_information: "bg-amber-500"
                        };
                        return (
                          <div key={idx} className="flex items-center justify-between text-xs">
                            <div className="flex items-center gap-2">
                              <span className={`w-3 h-3 rounded-full ${(bgColors as any)[entry.status] || "bg-primary"}`}></span>
                              <span className="text-muted">{(labels as any)[entry.status] || entry.status}</span>
                            </div>
                            <span className="font-mono text-white font-bold">{entry.count}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
                
                {/* 2. Claim Objects Distribution */}
                <div className="bg-card border border-border rounded-xl p-6">
                  <h4 className="text-sm font-bold text-white mb-4">Claims by Object Category</h4>
                  <div className="h-64">
                    {analytics.object_distribution.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={analytics.object_distribution}>
                          <XAxis dataKey="object" stroke="#8e939e" fontSize={11} tickLine={false} axisLine={false} />
                          <YAxis stroke="#8e939e" fontSize={11} tickLine={false} axisLine={false} />
                          <Tooltip contentStyle={{ backgroundColor: "#13151a", borderColor: "#22252e", color: "#f4f4f7" }} />
                          <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                            {analytics.object_distribution.map((entry: any, index: number) => {
                              const colors = ["#8b5cf6", "#10b981", "#3b82f6"];
                              return <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />;
                            })}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-xs text-muted font-mono">No Data</div>
                    )}
                  </div>
                </div>
              </div>
              
              <div className="grid grid-cols-3 gap-8">
                {/* 3. Confidence score distribution */}
                <div className="bg-card border border-border rounded-xl p-6">
                  <h4 className="text-sm font-bold text-white mb-4">Confidence Score Profile</h4>
                  <div className="h-48">
                    {analytics.confidence_distribution.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={analytics.confidence_distribution}>
                          <XAxis dataKey="bucket" stroke="#8e939e" fontSize={11} tickLine={false} axisLine={false} />
                          <Tooltip contentStyle={{ backgroundColor: "#13151a", borderColor: "#22252e", color: "#f4f4f7" }} />
                          <Bar dataKey="count" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-xs text-muted font-mono">No Data</div>
                    )}
                  </div>
                </div>
                
                {/* 4. Fraud risk distribution */}
                <div className="bg-card border border-border rounded-xl p-6">
                  <h4 className="text-sm font-bold text-white mb-4">Fraud Score Distribution</h4>
                  <div className="h-48">
                    {analytics.fraud_distribution.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={analytics.fraud_distribution}>
                          <XAxis dataKey="bucket" stroke="#8e939e" fontSize={11} tickLine={false} axisLine={false} />
                          <Tooltip contentStyle={{ backgroundColor: "#13151a", borderColor: "#22252e", color: "#f4f4f7" }} />
                          <Bar dataKey="count" fill="#ef4444" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-xs text-muted font-mono">No Data</div>
                    )}
                  </div>
                </div>
                
                {/* 5. Severity breakdown */}
                <div className="bg-card border border-border rounded-xl p-6">
                  <h4 className="text-sm font-bold text-white mb-4">Visual Severity breakdown</h4>
                  <div className="h-48">
                    {analytics.severity_distribution.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={analytics.severity_distribution}>
                          <XAxis dataKey="severity" stroke="#8e939e" fontSize={11} tickLine={false} axisLine={false} />
                          <Tooltip contentStyle={{ backgroundColor: "#13151a", borderColor: "#22252e", color: "#f4f4f7" }} />
                          <Bar dataKey="count" fill="#10b981" radius={[4, 4, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-xs text-muted font-mono">No Data</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
          
        </div>
      </main>
      
      {/* CLAIM DETAILS DETAILED WORKSPACE (Slide-over Inspector panel) */}
      {selectedClaim && (
        <div className="w-130 border-l border-border bg-[#090a0c] flex flex-col h-full overflow-hidden shadow-2xl relative z-20">
          {/* Details header */}
          <div className="p-6 border-b border-border flex items-center justify-between">
            <div>
              <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded font-mono font-bold">
                CLAIM INSPECTOR
              </span>
              <h3 className="text-sm font-bold text-white mt-1.5 font-mono">{selectedClaim.user_id}</h3>
            </div>
            <button
              onClick={() => setSelectedClaim(null)}
              className="text-muted hover:text-white hover:bg-card p-1 rounded-md transition-colors"
            >
              <XCircle className="w-5 h-5" />
            </button>
          </div>
          
          {/* Details Body */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            
            {/* Status section */}
            <div className="grid grid-cols-3 gap-4 bg-card border border-border p-4 rounded-xl">
              <div>
                <span className="text-[9px] text-muted block uppercase font-semibold">Verdict</span>
                <div className="mt-1">{getStatusBadge(selectedClaim.claim_status)}</div>
              </div>
              <div>
                <span className="text-[9px] text-muted block uppercase font-semibold">Confidence</span>
                <div className="mt-1 font-mono text-sm font-bold">{getConfidenceBadge(selectedClaim.confidence_score)}</div>
              </div>
              <div>
                <span className="text-[9px] text-muted block uppercase font-semibold">Fraud Score</span>
                <div className="mt-1 font-mono text-sm font-bold">{getFraudBadge(selectedClaim.fraud_score)}</div>
              </div>
            </div>
            
            {/* Execution Timeline (Agentic flow verification) */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-4 flex items-center gap-1.5">
                <Layers className="w-4 h-4 text-primary" /> Agent Execution Logs
              </h4>
              
              <div className="relative border-l-2 border-border/50 ml-3 pl-5 space-y-4 text-xs">
                {/* 1. Intake */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 flex items-center justify-center font-bold text-[8px]">
                    ✓
                  </span>
                  <div>
                    <h5 className="font-semibold text-white">Claim Intake & Parsing</h5>
                    <p className="text-[10px] text-muted mt-0.5">Claim Understanding Agent successfully parsed chat.</p>
                  </div>
                </div>
                
                {/* 2. Quality */}
                <div className="relative">
                  <span className={`absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold text-[8px] ${
                    selectedClaim.valid_image 
                      ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50" 
                      : "bg-amber-500/20 text-amber-400 border border-amber-500/50"
                  }`}>
                    {selectedClaim.valid_image ? "✓" : "!"}
                  </span>
                  <div>
                    <h5 className="font-semibold text-white">Image Quality Check</h5>
                    <p className="text-[10px] text-muted mt-0.5">
                      {selectedClaim.valid_image ? "Images marked valid." : "Image quality exceptions logged."}
                    </p>
                  </div>
                </div>
                
                {/* 3. Vision */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 flex items-center justify-center font-bold text-[8px]">
                    ✓
                  </span>
                  <div>
                    <h5 className="font-semibold text-white">Vision Feature Analysis</h5>
                    <p className="text-[10px] text-muted mt-0.5">Detected: {selectedClaim.issue_type} on {selectedClaim.object_part}.</p>
                  </div>
                </div>
                
                {/* 4. Compliance */}
                <div className="relative">
                  <span className={`absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold text-[8px] ${
                    selectedClaim.evidence_standard_met === "true" || selectedClaim.evidence_standard_met === true
                      ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50" 
                      : "bg-red-500/20 text-red-400 border border-red-500/50"
                  }`}>
                    {selectedClaim.evidence_standard_met === "true" || selectedClaim.evidence_standard_met === true ? "✓" : "!"}
                  </span>
                  <div>
                    <h5 className="font-semibold text-white">Policy Compliance Verification</h5>
                    <p className="text-[10px] text-muted mt-0.5">
                      {selectedClaim.evidence_standard_met === "true" || selectedClaim.evidence_standard_met === true ? "Complies with policy rules." : "Policy verification failed."}
                    </p>
                  </div>
                </div>
                
                {/* 5. Risk & Decision */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-primary/20 text-primary border border-primary/50 flex items-center justify-center font-bold text-[8px]">
                    ✓
                  </span>
                  <div>
                    <h5 className="font-semibold text-white">Verdict Generation</h5>
                    <p className="text-[10px] text-muted mt-0.5">Autonomously resolved status to {selectedClaim.claim_status.toUpperCase()}.</p>
                  </div>
                </div>
              </div>
            </div>
            
            {/* Visual Evidence Viewer */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-1.5">
                <ImageIcon className="w-4 h-4 text-emerald-400" /> Submitted Visual Evidence
              </h4>
              
              <div className="grid grid-cols-2 gap-3">
                {selectedClaim.image_paths.split(";").map((img_path: string, idx: number) => {
                  const imgName = img_path.split("/").pop() || `img_${idx+1}`;
                  const isSupporting = selectedClaim.supporting_image_ids.includes(`img_${idx+1}`) || selectedClaim.supporting_image_ids === "all";
                  return (
                    <div 
                      key={idx} 
                      className={`p-4 bg-background border rounded-lg flex flex-col items-center justify-center text-center group relative transition-colors ${
                        isSupporting ? "border-emerald-500/40 bg-emerald-500/[0.02]" : "border-border"
                      }`}
                    >
                      <ImageIcon className={`w-8 h-8 ${isSupporting ? "text-emerald-400" : "text-muted"}`} />
                      <span className="text-[10px] font-mono text-muted truncate max-w-full mt-2">{imgName}</span>
                      {isSupporting && (
                        <span className="absolute top-1.5 right-1.5 px-1 rounded text-[8px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold font-mono">
                          SUPPORTING
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
            
            {/* Customer Chat Transcript log */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-4 flex items-center gap-1.5">
                <FileSearch className="w-4 h-4 text-amber-400" /> claim Transcript Logs
              </h4>
              <div className="space-y-4 max-h-48 overflow-y-auto pr-2 text-xs leading-relaxed">
                {selectedClaim.user_claim.split("|").map((msg: string, idx: number) => {
                  const isAgent = msg.trim().startsWith("Agent:") || msg.trim().startsWith("Support:") || msg.trim().startsWith("Soporte:");
                  return (
                    <div
                      key={idx}
                      className={`p-3 rounded-lg ${
                        isAgent 
                          ? "bg-primary/5 text-primary-foreground border-l-2 border-primary ml-4" 
                          : "bg-background text-white border-l-2 border-emerald-400 mr-4"
                      }`}
                    >
                      <p className="font-semibold text-[10px] uppercase font-mono tracking-wider mb-1">
                        {isAgent ? "Support Agent" : "Customer (Claimant)"}
                      </p>
                      <p className="text-muted text-[11px]">{msg.replace(/^(Agent|Support|Customer|Cliente|Soporte):\s*/i, "").trim()}</p>
                    </div>
                  );
                })}
              </div>
            </div>
            
            {/* Explainable AI justification explanation */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-2 flex items-center gap-1.5">
                <CheckCircle className="w-4 h-4 text-emerald-400" /> Explainable AI Justification
              </h4>
              <p className="text-xs text-muted leading-relaxed font-mono bg-background p-4 rounded-lg border border-border">
                {selectedClaim.claim_status_justification}
              </p>
            </div>
            
            {/* Raw Audit Logs JSON */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-1.5">
                <FileJson className="w-4 h-4 text-muted" /> Audit Log metadata
              </h4>
              <details className="text-xs cursor-pointer">
                <summary className="text-[10px] text-muted hover:text-white font-mono uppercase">
                  Show Internal Agent Schemas (Pydantic / LangGraph)
                </summary>
                <div className="mt-3 p-3 bg-background rounded-lg border border-border text-[10px] font-mono text-muted overflow-x-auto max-h-60">
                  <pre>{JSON.stringify({
                    claim_id: selectedClaim.id,
                    user_id: selectedClaim.user_id,
                    evidence_compliance: {
                      met: selectedClaim.evidence_standard_met,
                      reason: selectedClaim.evidence_standard_met_reason
                    },
                    vision: {
                      detected_part: selectedClaim.object_part,
                      detected_issue: selectedClaim.issue_type,
                      severity: selectedClaim.severity
                    },
                    risk_evaluation: {
                      user_risk_score: selectedClaim.user_risk_score,
                      fraud_score: selectedClaim.fraud_score,
                      risk_flags: selectedClaim.risk_flags.split(";")
                    }
                  }, null, 2)}</pre>
                </div>
              </details>
            </div>
            
            {/* Human Override Controls */}
            {selectedClaim.escalation_reason && !selectedClaim.manual_verdict && (
              <div className="bg-danger/5 border border-danger/20 p-5 rounded-xl space-y-4">
                <div>
                  <h4 className="text-xs font-bold text-red-400 flex items-center gap-1.5">
                    <ShieldAlert className="w-4 h-4" /> Human Verification Panel
                  </h4>
                  <p className="text-[10px] text-muted mt-1 leading-relaxed">
                    Reason escalated: <span className="text-red-400">{selectedClaim.escalation_reason}</span>
                  </p>
                </div>
                
                <div className="space-y-2">
                  <label className="text-[10px] text-muted block uppercase font-mono font-semibold">Reviewer Notes</label>
                  <textarea
                    placeholder="Enter manual review justification notes..."
                    value={reviewerNotes}
                    onChange={(e) => setReviewerNotes(e.target.value)}
                    className="w-full text-xs p-3 bg-background border border-border rounded-lg outline-none text-white focus:border-primary/50 placeholder-muted h-20 resize-none"
                  />
                </div>
                
                <div className="flex gap-3">
                  <button
                    onClick={() => handleManualVerdict(selectedClaim.id, "approved")}
                    className="flex-1 py-2 text-xs font-bold bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 transition-colors"
                  >
                    Confirm & Approve Claim
                  </button>
                  <button
                    onClick={() => handleManualVerdict(selectedClaim.id, "rejected")}
                    className="flex-1 py-2 text-xs font-bold bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                  >
                    Reject & Block Claim
                  </button>
                </div>
              </div>
            )}
            
            {/* Human Override Verdict Logged */}
            {selectedClaim.manual_verdict && (
              <div className="bg-card border border-border p-5 rounded-xl border-l-4 border-primary">
                <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                  <User className="w-4 h-4 text-primary" /> Human Decision Recorded
                </h4>
                <div className="mt-2 text-xs leading-relaxed space-y-1">
                  <p className="text-muted">
                    Verdict: <span className={`font-semibold capitalize ${selectedClaim.manual_verdict === "approved" ? "text-emerald-400" : "text-red-400"}`}>
                      {selectedClaim.manual_verdict.toUpperCase()}
                    </span>
                  </p>
                  <p className="text-muted">
                    Notes: <span className="italic">"{selectedClaim.manual_reviewer_notes || "None"}"</span>
                  </p>
                </div>
              </div>
            )}

          </div>
        </div>
      )}
    </div>
  );
}

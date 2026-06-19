"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
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
  FileJson,
  Upload,
  Zap,
  Brain,
  Eye,
  Fingerprint,
  Scale,
  Activity,
  Sparkles,
  Camera,
  X,
  ChevronDown,
  Loader2
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

/* ──────────────────────── Agent Step definitions ──────────────────────── */
const AGENT_STEPS = [
  { key: "intake",     icon: Upload,       name: "Claim Ingestion",                 color: "emerald" },
  { key: "quality",    icon: Camera,       name: "Image Quality Assessment",        color: "emerald" },
  { key: "vision",     icon: Eye,          name: "Vision Analysis (Gemini)",        color: "violet" },
  { key: "evidence",   icon: FileSearch,   name: "Evidence Compliance Check",       color: "emerald" },
  { key: "rag",        icon: Search,       name: "Similar Claims RAG Search",       color: "blue" },
  { key: "risk",       icon: Activity,     name: "User Risk Assessment",            color: "amber" },
  { key: "fraud",      icon: Fingerprint,  name: "Fraud Intelligence Agent",        color: "red" },
  { key: "confidence", icon: Scale,        name: "Confidence Scoring",              color: "violet" },
  { key: "decision",   icon: Brain,        name: "Decision Agent (Gemini 2.5)",     color: "primary" },
];

/* ──────────────────────── Score Ring Component ──────────────────────── */
function ScoreRing({ score, label, color, size = 88 }: { score: number; label: string; color: string; size?: number }) {
  const radius = (size - 12) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  const colorMap: Record<string, string> = {
    emerald: "#10b981",
    red: "#ef4444",
    amber: "#f59e0b",
    violet: "#8b5cf6",
    primary: "#8b5cf6",
    blue: "#3b82f6",
  };

  const strokeColor = colorMap[color] || "#8b5cf6";

  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width={size} height={size} className="transform -rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#22252e" strokeWidth="5" />
        <circle
          cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={strokeColor} strokeWidth="5"
          strokeDasharray={circumference} strokeDashoffset={offset}
          strokeLinecap="round" className="score-ring"
        />
      </svg>
      <span className="text-lg font-bold font-mono text-white" style={{ marginTop: -(size / 2 + 10) }}>
        {score}
      </span>
      <span className="text-[10px] text-muted uppercase tracking-widest font-semibold mt-5">{label}</span>
    </div>
  );
}

/* ──────────────────────── Main App ──────────────────────── */
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

  // ─── New Investigation state ───
  const [submitUserId, setSubmitUserId] = useState("");
  const [submitClaim, setSubmitClaim] = useState("");
  const [submitObject, setSubmitObject] = useState("car");
  const [submitImagePaths, setSubmitImagePaths] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState<any | null>(null);
  const [currentAgentStep, setCurrentAgentStep] = useState(-1);
  const [completedSteps, setCompletedSteps] = useState<number[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [previewImages, setPreviewImages] = useState<string[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchAllData = async () => {
    setIsRefreshing(true);
    try {
      const claimsRes = await fetch(`${API_BASE_URL}/claims`);
      if (claimsRes.ok) { setClaims(await claimsRes.json()); }
      const queueRes = await fetch(`${API_BASE_URL}/queue`);
      if (queueRes.ok) { setQueue(await queueRes.json()); }
      const analyticsRes = await fetch(`${API_BASE_URL}/analytics`);
      if (analyticsRes.ok) { setAnalytics(await analyticsRes.json()); }
    } catch (error) {
      console.error("Failed to fetch data from backend.", error);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => { fetchAllData(); }, []);

  const fetchClaimDetails = async (claimId: number) => {
    try {
      const res = await fetch(`${API_BASE_URL}/claims/${claimId}`);
      if (res.ok) { setSelectedClaim(await res.json()); }
    } catch (e) { console.error("Error fetching claim details:", e); }
  };

  const handleManualVerdict = async (claimId: number, verdict: "approved" | "rejected") => {
    try {
      const res = await fetch(`${API_BASE_URL}/queue/${claimId}/verdict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict, notes: reviewerNotes })
      });
      if (res.ok) { setReviewerNotes(""); await fetchAllData(); setSelectedClaim(null); }
      else { alert("Failed to submit manual review decision."); }
    } catch (e) { console.error(e); alert("Error submitting verdict."); }
  };

  /* ──────────────────────── Submit new investigation ──────────────────────── */
  const handleSubmitInvestigation = async () => {
    if (!submitUserId.trim() || !submitClaim.trim() || !submitImagePaths.trim()) {
      setSubmitError("Please fill in User ID, Claim Description, and Image Path(s).");
      return;
    }
    setSubmitError(null);
    setIsSubmitting(true);
    setSubmitResult(null);
    setCurrentAgentStep(0);
    setCompletedSteps([]);

    // Simulate agent step progression while waiting for real API
    const stepInterval = setInterval(() => {
      setCurrentAgentStep(prev => {
        if (prev < AGENT_STEPS.length - 1) {
          setCompletedSteps(c => [...c, prev]);
          return prev + 1;
        }
        return prev;
      });
    }, 900);

    try {
      let res;
      if (selectedFiles.length > 0) {
        const formData = new FormData();
        formData.append("user_id", submitUserId.trim());
        formData.append("user_claim", submitClaim.trim());
        formData.append("claim_object", submitObject);
        selectedFiles.forEach((file) => {
          formData.append("files", file);
        });
        res = await fetch(`${API_BASE_URL}/claims/submit-multimodal`, {
          method: "POST",
          body: formData
        });
      } else {
        res = await fetch(`${API_BASE_URL}/claims/submit`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id: submitUserId.trim(),
            user_claim: submitClaim.trim(),
            claim_object: submitObject,
            image_paths: submitImagePaths.trim()
          })
        });
      }
      clearInterval(stepInterval);

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText);
      }

      // Complete all steps
      setCompletedSteps(AGENT_STEPS.map((_, i) => i));
      setCurrentAgentStep(AGENT_STEPS.length);

      const result = await res.json();
      // Small delay for dramatic effect after completing steps
      setTimeout(() => {
        setSubmitResult(result);
        setIsSubmitting(false);
        fetchAllData(); // Refresh dashboard data
      }, 600);
    } catch (e: any) {
      clearInterval(stepInterval);
      setSubmitError(`Investigation failed: ${e.message}`);
      setIsSubmitting(false);
      setCurrentAgentStep(-1);
      setCompletedSteps([]);
    }
  };

  const resetInvestigation = () => {
    setSubmitResult(null);
    setSubmitUserId("");
    setSubmitClaim("");
    setSubmitObject("car");
    setSubmitImagePaths("");
    setCurrentAgentStep(-1);
    setCompletedSteps([]);
    setSubmitError(null);
    setPreviewImages([]);
    setSelectedFiles([]);
  };

  // File handling for drag & drop
  const handleFiles = (files: FileList) => {
    const paths: string[] = [];
    const previews: string[] = [];
    const fileList: File[] = [];
    Array.from(files).forEach((file, idx) => {
      paths.push(`images/${file.name}`);
      previews.push(URL.createObjectURL(file));
      fileList.push(file);
    });
    setSubmitImagePaths(paths.join(";"));
    setPreviewImages(previews);
    setSelectedFiles(fileList);
  };

  // Badge helpers
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
    if (score >= 90) return <span className="text-xs font-semibold text-emerald-400 font-mono">{score}%</span>;
    if (score >= 70) return <span className="text-xs font-semibold text-amber-400 font-mono">{score}%</span>;
    return <span className="text-xs font-semibold text-red-400 font-mono">{score}%</span>;
  };

  const getFraudBadge = (score: number) => {
    if (score > 60)
      return <span className="inline-flex px-2 py-0.5 rounded text-xs font-bold bg-red-500/10 text-red-400 border border-red-500/20 font-mono">{score}/100</span>;
    if (score > 30)
      return <span className="inline-flex px-2 py-0.5 rounded text-xs font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20 font-mono">{score}/100</span>;
    return <span className="inline-flex px-2 py-0.5 rounded text-xs font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">{score}/100</span>;
  };

  const getSeverityBadge = (sev: string) => {
    switch (sev?.toLowerCase()) {
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
    if (riskFilter === "high") matchesRisk = c.fraud_score > 60 || c.user_risk_score > 60;
    else if (riskFilter === "medium") matchesRisk = (c.fraud_score > 30 && c.fraud_score <= 60) || (c.user_risk_score > 30 && c.user_risk_score <= 60);
    else if (riskFilter === "low") matchesRisk = c.fraud_score <= 30 && c.user_risk_score <= 30;
    return matchesSearch && matchesStatus && matchesObject && matchesRisk;
  });

  // Extract similar claims from RAG logs
  const getRAGSimilarClaims = () => {
    if (!selectedClaim || !selectedClaim.audit_logs) return [];
    const similarLog = selectedClaim.audit_logs.find(
      (log: any) => log.agent_name === "Similar Claims Retrieval Agent"
    );
    return similarLog?.outputs?.similar_claims || [];
  };
  const similarClaims = getRAGSimilarClaims();

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground font-sans">
      {/* ──────────── Sidebar Navigation ──────────── */}
      <aside className="w-64 border-r border-border bg-[#090a0c] flex flex-col justify-between p-6">
        <div>
          {/* Logo */}
          <div className="flex items-center gap-2.5 mb-8">
            <div className="p-2 bg-primary/20 text-primary rounded-lg border border-primary/30 animate-pulse-ring">
              <Shield className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight text-white">AURELIX</h1>
              <p className="text-[10px] text-muted tracking-widest uppercase font-mono">Claims Intelligence</p>
            </div>
          </div>

          {/* Menu */}
          <nav className="space-y-1">
            {/* New Investigation - THE DEMO HERO */}
            <button
              onClick={() => { setActiveTab("investigate"); setSelectedClaim(null); }}
              className={`w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium rounded-lg transition-all ${
                activeTab === "investigate"
                  ? "bg-gradient-to-r from-primary/20 to-primary/5 text-primary border border-primary/30 shadow-lg shadow-primary/5"
                  : "text-muted hover:text-white hover:bg-card/50"
              }`}
            >
              <Zap className="w-4 h-4" />
              <span>New Investigation</span>
              {activeTab !== "investigate" && (
                <span className="ml-auto px-1.5 py-0.5 rounded text-[9px] bg-primary/20 text-primary border border-primary/30 font-bold animate-glow-pulse">
                  LIVE
                </span>
              )}
            </button>

            <div className="h-px bg-border/40 my-2" />

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
              Investigation Log
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
                Human Review
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
        <div className="border-t border-border pt-4 text-[11px] text-muted space-y-1.5">
          <p className="font-mono flex items-center gap-1.5">
            <Sparkles className="w-3 h-3 text-primary" /> Gemini 2.5 Flash
          </p>
          <p className="font-mono flex items-center gap-1.5">
            <Brain className="w-3 h-3 text-emerald-400" /> 9 Agents • LangGraph
          </p>
          <div className="flex items-center justify-between mt-1">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Connected
            </span>
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

      {/* ──────────── Main Content Workspace ──────────── */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-background">
        {/* Top Header */}
        <header className="h-14 border-b border-border bg-[#090a0c]/80 backdrop-blur flex items-center justify-between px-8 z-10 flex-shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="text-md font-semibold text-white capitalize">
              {activeTab === "investigate" ? "AI Investigation Workspace" :
               activeTab === "queue" ? "Human Override Queue" : `${activeTab} Workspace`}
            </h2>
            {activeTab === "investigate" && (
              <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded font-mono font-bold">
                AUTONOMOUS MODE
              </span>
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
            <div className="h-8 w-px bg-border" />
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-full bg-primary/20 text-primary flex items-center justify-center font-bold text-xs border border-primary/30">
                AI
              </div>
              <span className="text-xs font-medium text-white">Investigator Agent</span>
            </div>
          </div>
        </header>

        {/* ──────────── Dynamic Tab Body ──────────── */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* ════════════════════ TAB: NEW INVESTIGATION ════════════════════ */}
          {activeTab === "investigate" && (
            <div className="max-w-6xl mx-auto space-y-8 animate-fadeInUp">
              {/* Hero header */}
              {!isSubmitting && !submitResult && (
                <div className="text-center mb-8">
                  <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 text-primary border border-primary/20 text-xs font-mono font-semibold mb-4">
                    <Zap className="w-3.5 h-3.5" /> AUTONOMOUS CLAIMS INVESTIGATION ENGINE
                  </div>
                  <h2 className="text-2xl font-bold text-white tracking-tight">
                    Start a New Investigation
                  </h2>
                  <p className="text-sm text-muted mt-2 max-w-lg mx-auto leading-relaxed">
                    Upload damage evidence and claim details. Our 9-agent AI pipeline will autonomously analyze, verify, and deliver an explainable decision.
                  </p>
                </div>
              )}

              {/* ─── Input Form ─── */}
              {!isSubmitting && !submitResult && (
                <div className="grid grid-cols-2 gap-8 animate-fadeInUp">
                  {/* Left: Claim Details */}
                  <div className="bg-card border border-border rounded-2xl p-6 space-y-5">
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                      <FileText className="w-4 h-4 text-primary" /> Claim Information
                    </h3>

                    <div className="space-y-4">
                      <div>
                        <label className="text-[10px] text-muted uppercase font-mono font-semibold tracking-wider block mb-1.5">User ID</label>
                        <input
                          type="text"
                          value={submitUserId}
                          onChange={e => setSubmitUserId(e.target.value)}
                          placeholder="e.g. user_050"
                          className="w-full text-sm px-4 py-2.5 bg-background border border-border rounded-xl outline-none text-white placeholder-muted/50 focus:border-primary/50 transition-colors"
                        />
                      </div>

                      <div>
                        <label className="text-[10px] text-muted uppercase font-mono font-semibold tracking-wider block mb-1.5">Damaged Object</label>
                        <select
                          value={submitObject}
                          onChange={e => setSubmitObject(e.target.value)}
                          className="w-full text-sm px-4 py-2.5 bg-background border border-border rounded-xl outline-none text-white cursor-pointer focus:border-primary/50 transition-colors"
                        >
                          <option value="car">🚗 Car / Vehicle</option>
                          <option value="laptop">💻 Laptop / Electronics</option>
                          <option value="package">📦 Package / Shipment</option>
                        </select>
                      </div>

                      <div>
                        <label className="text-[10px] text-muted uppercase font-mono font-semibold tracking-wider block mb-1.5">Claim Description</label>
                        <textarea
                          value={submitClaim}
                          onChange={e => setSubmitClaim(e.target.value)}
                          placeholder="Describe the damage in detail. Paste the customer conversation or claim text..."
                          rows={5}
                          className="w-full text-sm px-4 py-3 bg-background border border-border rounded-xl outline-none text-white placeholder-muted/50 focus:border-primary/50 resize-none leading-relaxed transition-colors"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Right: Image Upload */}
                  <div className="bg-card border border-border rounded-2xl p-6 space-y-5">
                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                      <Camera className="w-4 h-4 text-emerald-400" /> Evidence Images
                    </h3>

                    {/* Drop zone */}
                    <div
                      onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                      onDragLeave={() => setDragActive(false)}
                      onDrop={(e) => { e.preventDefault(); setDragActive(false); if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files); }}
                      onClick={() => fileInputRef.current?.click()}
                      className={`border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center text-center cursor-pointer transition-all ${
                        dragActive
                          ? "border-primary bg-primary/5"
                          : "border-border/60 hover:border-primary/40 hover:bg-card-hover/30"
                      }`}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/*"
                        multiple
                        className="hidden"
                        onChange={(e) => { if (e.target.files?.length) handleFiles(e.target.files); }}
                      />
                      <div className={`w-14 h-14 rounded-2xl flex items-center justify-center mb-4 transition-colors ${
                        dragActive ? "bg-primary/20 text-primary" : "bg-card-hover text-muted"
                      }`}>
                        <Upload className="w-6 h-6" />
                      </div>
                      <p className="text-xs font-semibold text-white">
                        Drop images here or <span className="text-primary">browse</span>
                      </p>
                      <p className="text-[10px] text-muted mt-1">PNG, JPG, WebP — multiple files supported</p>
                    </div>

                    {/* Preview thumbnails */}
                    {previewImages.length > 0 && (
                      <div className="grid grid-cols-3 gap-3">
                        {previewImages.map((src, idx) => (
                          <div key={idx} className="relative rounded-xl overflow-hidden border border-border aspect-square bg-background">
                            <img src={src} alt={`evidence-${idx}`} className="w-full h-full object-cover" />
                            <span className="absolute bottom-1 left-1 px-1.5 py-0.5 text-[9px] bg-black/70 text-white rounded font-mono">
                              img_{idx + 1}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Manual path input fallback */}
                    <div>
                      <label className="text-[10px] text-muted uppercase font-mono font-semibold tracking-wider block mb-1.5">
                        Image Path(s) <span className="text-muted/50">— semicolon separated</span>
                      </label>
                      <input
                        type="text"
                        value={submitImagePaths}
                        onChange={e => setSubmitImagePaths(e.target.value)}
                        placeholder="images/claim_001.jpg;images/claim_002.jpg"
                        className="w-full text-xs px-4 py-2.5 bg-background border border-border rounded-xl outline-none text-white placeholder-muted/50 font-mono focus:border-primary/50 transition-colors"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Error message */}
              {submitError && (
                <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3 animate-fadeIn">
                  <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-semibold text-red-400">Investigation Error</p>
                    <p className="text-[11px] text-muted mt-0.5">{submitError}</p>
                  </div>
                  <button onClick={() => setSubmitError(null)} className="ml-auto text-muted hover:text-white">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              )}

              {/* Submit button */}
              {!isSubmitting && !submitResult && (
                <div className="flex justify-center animate-fadeInUp" style={{ animationDelay: "0.15s" }}>
                  <button
                    onClick={handleSubmitInvestigation}
                    className="group relative px-8 py-3 bg-gradient-to-r from-primary to-violet-600 hover:from-primary-hover hover:to-violet-700 text-white font-bold text-sm rounded-xl shadow-lg shadow-primary/20 transition-all hover:shadow-xl hover:shadow-primary/30 hover:scale-[1.02] active:scale-[0.98]"
                  >
                    <span className="flex items-center gap-2">
                      <Zap className="w-4 h-4" />
                      Launch Autonomous Investigation
                      <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
                    </span>
                  </button>
                </div>
              )}

              {/* ─── Agent Processing Pipeline Animation ─── */}
              {isSubmitting && (
                <div className="space-y-6 animate-fadeInUp">
                  <div className="text-center">
                    <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary border border-primary/20 text-xs font-mono font-bold">
                      <Loader2 className="w-4 h-4 animate-spin" /> AUTONOMOUS INVESTIGATION IN PROGRESS
                    </div>
                    <p className="text-xs text-muted mt-2">9 specialized AI agents are analyzing your claim...</p>
                  </div>

                  <div className="bg-card border border-border rounded-2xl p-6">
                    <div className="space-y-3">
                      {AGENT_STEPS.map((step, idx) => {
                        const isCompleted = completedSteps.includes(idx);
                        const isCurrent = currentAgentStep === idx;
                        const isPending = !isCompleted && !isCurrent;
                        const StepIcon = step.icon;

                        return (
                          <div
                            key={step.key}
                            className={`flex items-center gap-4 px-4 py-3 rounded-xl transition-all duration-500 ${
                              isCurrent ? "bg-primary/5 border border-primary/20 animate-shimmer" :
                              isCompleted ? "bg-emerald-500/[0.03] border border-emerald-500/10" :
                              "border border-transparent opacity-40"
                            }`}
                          >
                            {/* Step indicator */}
                            <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 transition-all ${
                              isCurrent ? "bg-primary/20 text-primary animate-pulse-ring" :
                              isCompleted ? "bg-emerald-500/20 text-emerald-400" :
                              "bg-card-hover text-muted"
                            }`}>
                              {isCompleted ? <CheckCircle className="w-4 h-4" /> :
                               isCurrent ? <Loader2 className="w-4 h-4 animate-spin" /> :
                               <StepIcon className="w-4 h-4" />}
                            </div>

                            {/* Step details */}
                            <div className="flex-1 min-w-0">
                              <p className={`text-xs font-semibold ${isCurrent ? "text-primary" : isCompleted ? "text-emerald-400" : "text-muted"}`}>
                                {step.name}
                              </p>
                              {isCurrent && (
                                <div className="flex items-center gap-1 mt-0.5">
                                  <span className="w-1 h-1 rounded-full bg-primary animate-typing-dots" />
                                  <span className="w-1 h-1 rounded-full bg-primary animate-typing-dots" style={{ animationDelay: "0.2s" }} />
                                  <span className="w-1 h-1 rounded-full bg-primary animate-typing-dots" style={{ animationDelay: "0.4s" }} />
                                </div>
                              )}
                            </div>

                            {/* Status */}
                            <div className="flex-shrink-0">
                              {isCompleted && (
                                <span className="text-[10px] font-mono font-semibold text-emerald-400">DONE</span>
                              )}
                              {isCurrent && (
                                <span className="text-[10px] font-mono font-semibold text-primary">RUNNING</span>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              )}

              {/* ─── Investigation Results ─── */}
              {submitResult && (
                <div className="space-y-8 animate-fadeInUp">
                  {/* Result header */}
                  <div className="text-center">
                    <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-full text-xs font-mono font-bold border ${
                      submitResult.claim_status === "supported"
                        ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                        : submitResult.claim_status === "contradicted"
                        ? "bg-red-500/10 text-red-400 border-red-500/20"
                        : "bg-amber-500/10 text-amber-400 border-amber-500/20"
                    }`}>
                      {submitResult.claim_status === "supported" ? <CheckCircle className="w-4 h-4" /> :
                       submitResult.claim_status === "contradicted" ? <XCircle className="w-4 h-4" /> :
                       <AlertCircle className="w-4 h-4" />}
                      INVESTIGATION COMPLETE — {submitResult.claim_status.toUpperCase().replace("_", " ")}
                    </div>
                    <h2 className="text-xl font-bold text-white mt-3">
                      Claim #{submitResult.id} — {submitResult.user_id}
                    </h2>
                  </div>

                  {/* Score Cards */}
                  <div className="grid grid-cols-4 gap-6">
                    <div className="glass-card rounded-2xl p-6 flex flex-col items-center">
                      <ScoreRing score={submitResult.confidence_score} label="Confidence" color={submitResult.confidence_score >= 80 ? "emerald" : submitResult.confidence_score >= 60 ? "amber" : "red"} />
                    </div>
                    <div className="glass-card rounded-2xl p-6 flex flex-col items-center">
                      <ScoreRing score={submitResult.fraud_score} label="Fraud Risk" color={submitResult.fraud_score > 60 ? "red" : submitResult.fraud_score > 30 ? "amber" : "emerald"} />
                    </div>
                    <div className="glass-card rounded-2xl p-6 flex flex-col items-center">
                      <ScoreRing score={submitResult.user_risk_score} label="User Risk" color={submitResult.user_risk_score > 60 ? "red" : submitResult.user_risk_score > 30 ? "amber" : "emerald"} />
                    </div>
                    <div className="glass-card rounded-2xl p-6 flex flex-col items-center gap-3">
                      <div className={`w-16 h-16 rounded-2xl flex items-center justify-center ${
                        submitResult.claim_status === "supported" ? "bg-emerald-500/20 text-emerald-400" :
                        submitResult.claim_status === "contradicted" ? "bg-red-500/20 text-red-400" :
                        "bg-amber-500/20 text-amber-400"
                      }`}>
                        {submitResult.claim_status === "supported" ? <CheckCircle className="w-8 h-8" /> :
                         submitResult.claim_status === "contradicted" ? <XCircle className="w-8 h-8" /> :
                         <AlertCircle className="w-8 h-8" />}
                      </div>
                      <span className="text-[10px] text-muted uppercase tracking-widest font-semibold">Final Verdict</span>
                      <span className="text-sm font-bold text-white capitalize">{submitResult.claim_status.replace("_", " ")}</span>
                    </div>
                  </div>

                  {/* Details Grid */}
                  <div className="grid grid-cols-2 gap-6">
                    {/* Left: Vision Analysis + Evidence */}
                    <div className="space-y-6">
                      <div className="bg-card border border-border rounded-2xl p-6">
                        <h4 className="text-xs font-bold text-white mb-4 flex items-center gap-2">
                          <Eye className="w-4 h-4 text-violet-400" /> Vision Analysis Results
                        </h4>
                        <div className="grid grid-cols-3 gap-4">
                          <div>
                            <span className="text-[9px] text-muted block uppercase font-semibold">Object</span>
                            <span className="text-sm text-white font-semibold capitalize mt-1 block">{submitResult.claim_object}</span>
                          </div>
                          <div>
                            <span className="text-[9px] text-muted block uppercase font-semibold">Damaged Part</span>
                            <span className="text-sm text-white font-semibold mt-1 block">{submitResult.object_part}</span>
                          </div>
                          <div>
                            <span className="text-[9px] text-muted block uppercase font-semibold">Issue</span>
                            <span className="text-sm text-white font-semibold mt-1 block">{submitResult.issue_type}</span>
                          </div>
                        </div>
                        <div className="mt-4 flex items-center gap-4">
                          <div>
                            <span className="text-[9px] text-muted block uppercase font-semibold">Severity</span>
                            <div className="mt-1">{getSeverityBadge(submitResult.severity)}</div>
                          </div>
                          <div>
                            <span className="text-[9px] text-muted block uppercase font-semibold">Image Valid</span>
                            <span className={`text-sm font-semibold mt-1 block ${submitResult.valid_image ? "text-emerald-400" : "text-red-400"}`}>
                              {submitResult.valid_image ? "✓ Verified" : "✗ Invalid"}
                            </span>
                          </div>
                          <div>
                            <span className="text-[9px] text-muted block uppercase font-semibold">Evidence Met</span>
                            <span className={`text-sm font-semibold mt-1 block ${
                              submitResult.evidence_standard_met === true || submitResult.evidence_standard_met === "true" ? "text-emerald-400" : "text-red-400"
                            }`}>
                              {submitResult.evidence_standard_met === true || submitResult.evidence_standard_met === "true" ? "✓ Yes" : "✗ No"}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Risk flags */}
                      <div className="bg-card border border-border rounded-2xl p-6">
                        <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-2">
                          <ShieldAlert className="w-4 h-4 text-amber-400" /> Risk Flags
                        </h4>
                        <div className="flex flex-wrap gap-2">
                          {submitResult.risk_flags?.split(";").filter(Boolean).map((flag: string, idx: number) => (
                            <span key={idx} className={`text-[10px] px-2.5 py-1 rounded-lg font-mono font-semibold border ${
                              flag === "none" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                              "bg-amber-500/10 text-amber-400 border-amber-500/20"
                            }`}>
                              {flag.replace(/_/g, " ")}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Right: Justification + Images */}
                    <div className="space-y-6">
                      <div className="bg-card border border-border rounded-2xl p-6">
                        <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-2">
                          <Brain className="w-4 h-4 text-primary" /> AI Reasoning &amp; Justification
                        </h4>
                        <p className="text-xs text-muted leading-relaxed font-mono bg-background p-4 rounded-xl border border-border">
                          {submitResult.claim_status_justification}
                        </p>
                      </div>

                      <div className="bg-card border border-border rounded-2xl p-6">
                        <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-2">
                          <ImageIcon className="w-4 h-4 text-emerald-400" /> Submitted Evidence
                        </h4>
                        <div className="grid grid-cols-2 gap-3">
                          {submitResult.image_paths?.split(";").map((img_path: string, idx: number) => {
                            const imgName = img_path.split("/").pop() || `img_${idx + 1}`;
                            const isSupporting = submitResult.supporting_image_ids?.includes(`img_${idx + 1}`) || submitResult.supporting_image_ids === "all";
                            return (
                              <div
                                key={idx}
                                className={`p-4 bg-background border rounded-xl flex flex-col items-center justify-center text-center relative ${
                                  isSupporting ? "border-emerald-500/40 bg-emerald-500/[0.02]" : "border-border"
                                }`}
                              >
                                {previewImages[idx] ? (
                                  <img src={previewImages[idx]} alt={imgName} className="w-full h-20 object-cover rounded-lg mb-2" />
                                ) : (
                                  <ImageIcon className={`w-8 h-8 ${isSupporting ? "text-emerald-400" : "text-muted"}`} />
                                )}
                                <span className="text-[10px] font-mono text-muted truncate max-w-full mt-1">{imgName}</span>
                                {isSupporting && submitResult.claim_status === "supported" && (
                                  <span className="absolute top-1.5 right-1.5 px-1 rounded text-[8px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold font-mono">
                                    MATCH
                                  </span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Agent Timeline (completed) */}
                  <div className="bg-card border border-border rounded-2xl p-6">
                    <h4 className="text-xs font-bold text-white mb-4 flex items-center gap-2">
                      <Layers className="w-4 h-4 text-primary" /> Autonomous Agent Execution Timeline
                    </h4>
                    <div className="flex items-center gap-0">
                      {AGENT_STEPS.map((step, idx) => {
                        const StepIcon = step.icon;
                        return (
                          <React.Fragment key={step.key}>
                            <div className="flex flex-col items-center gap-1.5 min-w-[80px]">
                              <div className="w-9 h-9 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center">
                                <StepIcon className="w-4 h-4" />
                              </div>
                              <span className="text-[9px] text-muted text-center leading-tight max-w-[80px]">{step.name.split(" ")[0]}</span>
                            </div>
                            {idx < AGENT_STEPS.length - 1 && (
                              <div className="flex-1 h-px bg-emerald-500/30 min-w-[16px]" />
                            )}
                          </React.Fragment>
                        );
                      })}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex justify-center gap-4">
                    <button
                      onClick={resetInvestigation}
                      className="px-6 py-2.5 bg-card hover:bg-card-hover border border-border text-white font-semibold text-sm rounded-xl transition-colors flex items-center gap-2"
                    >
                      <Zap className="w-4 h-4" /> New Investigation
                    </button>
                    <button
                      onClick={() => { setActiveTab("claims"); fetchClaimDetails(submitResult.id); }}
                      className="px-6 py-2.5 bg-primary/10 hover:bg-primary/20 border border-primary/20 text-primary font-semibold text-sm rounded-xl transition-colors flex items-center gap-2"
                    >
                      View in Database <ArrowRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ════════════════════ TAB: DASHBOARD ════════════════════ */}
          {activeTab === "dashboard" && (
            <div className="space-y-8">
              {/* KPI Cards Grid */}
              <div className="grid grid-cols-5 gap-6">
                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Total Ingested</p>
                  <h3 className="text-2xl font-bold text-white mt-2">{analytics.kpis.total_claims}</h3>
                  <div className="text-[10px] text-muted mt-1.5 flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3 text-primary" /> Active in database
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Verified Supported</p>
                  <h3 className="text-2xl font-bold text-emerald-400 mt-2">{analytics.kpis.supported_claims}</h3>
                  <div className="text-[10px] text-emerald-500/80 mt-1.5 flex items-center gap-1 font-mono">
                    <CheckCircle className="w-3 h-3" /> Auto-verified claims
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Verified Contradicted</p>
                  <h3 className="text-2xl font-bold text-red-400 mt-2">{analytics.kpis.contradicted_claims}</h3>
                  <div className="text-[10px] text-red-500/80 mt-1.5 flex items-center gap-1 font-mono">
                    <XCircle className="w-3 h-3" /> Visual mismatch detected
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Manual Review</p>
                  <h3 className="text-2xl font-bold text-amber-400 mt-2">{queue.length}</h3>
                  <div className="text-[10px] text-amber-500/80 mt-1.5 flex items-center gap-1 font-mono">
                    <ShieldAlert className="w-3 h-3" /> Awaiting review
                  </div>
                </div>

                <div className="bg-card border border-border rounded-xl p-5 shadow-sm">
                  <p className="text-xs font-semibold text-muted tracking-wider uppercase">Average Trust</p>
                  <h3 className="text-2xl font-bold text-primary mt-2">{analytics.kpis.average_confidence}%</h3>
                  <div className="text-[10px] text-primary mt-1.5 flex items-center gap-1 font-mono">
                    <TrendingUp className="w-3 h-3" /> System confidence score
                  </div>
                </div>
              </div>

              {/* Charts */}
              <div className="grid grid-cols-3 gap-8">
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
                        No processing records available yet. Ingesting claims...
                      </div>
                    )}
                  </div>
                </div>

                {/* Risk alerts */}
                <div className="bg-card border border-border rounded-xl p-6 flex flex-col">
                  <h4 className="text-sm font-bold text-white mb-4">Risk & Fraud Alerts</h4>
                  <div className="flex-1 space-y-3 overflow-y-auto max-h-64 pr-2">
                    {claims.filter(c => c.fraud_score > 30).slice(0, 5).map((claim, idx) => (
                      <div
                        key={idx}
                        onClick={() => { setSelectedClaim(claim); fetchClaimDetails(claim.id); }}
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
                          onClick={() => { setSelectedClaim(claim); fetchClaimDetails(claim.id); }}
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

          {/* ════════════════════ TAB: CLAIMS LIST ════════════════════ */}
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
                    <select value={objectFilter} onChange={(e) => setObjectFilter(e.target.value)}
                      className="bg-transparent border-none outline-none text-white font-medium cursor-pointer">
                      <option value="all">All</option>
                      <option value="car">Car</option>
                      <option value="laptop">Laptop</option>
                      <option value="package">Package</option>
                    </select>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted border border-border bg-background px-3 py-1.5 rounded-lg">
                    <Filter className="w-3.5 h-3.5" />
                    <span>Verdict:</span>
                    <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                      className="bg-transparent border-none outline-none text-white font-medium cursor-pointer">
                      <option value="all">All</option>
                      <option value="supported">Supported</option>
                      <option value="contradicted">Contradicted</option>
                      <option value="not_enough_information">Not Enough Info</option>
                    </select>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted border border-border bg-background px-3 py-1.5 rounded-lg">
                    <Filter className="w-3.5 h-3.5" />
                    <span>Risk Level:</span>
                    <select value={riskFilter} onChange={(e) => setRiskFilter(e.target.value)}
                      className="bg-transparent border-none outline-none text-white font-medium cursor-pointer">
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
                          onClick={() => { setSelectedClaim(claim); fetchClaimDetails(claim.id); }}
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

          {/* ════════════════════ TAB: HUMAN REVIEW QUEUE ════════════════════ */}
          {activeTab === "queue" && (
            <div className="space-y-6">
              <div className="bg-card border border-border rounded-xl p-6 shadow-sm">
                <h3 className="text-sm font-bold text-white mb-2">Manual Verification Queue</h3>
                <p className="text-xs text-muted leading-relaxed">
                  These claims were escalated because they fell below the auto-confidence threshold (70/100), had suspicious risk flags,
                  or showed evidence of image manipulation. Assess the visual logs below to override or confirm agent status.
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
                        <tr key={idx} className="hover:bg-card-hover/40 transition-colors">
                          <td
                            className="py-4 px-6 font-mono text-primary font-semibold cursor-pointer"
                            onClick={() => { setSelectedClaim(claim); fetchClaimDetails(claim.id); }}
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
                              onClick={() => { setSelectedClaim(claim); fetchClaimDetails(claim.id); }}
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
                            Human review queue is currently empty. All clear!
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ════════════════════ TAB: ANALYTICS ════════════════════ */}
          {activeTab === "analytics" && (
            <div className="space-y-8">
              <div className="grid grid-cols-2 gap-8">
                {/* Verdict Distribution */}
                <div className="bg-card border border-border rounded-xl p-6">
                  <h4 className="text-sm font-bold text-white mb-4">Verdict Distribution</h4>
                  <div className="h-64 flex items-center justify-between">
                    <div className="w-1/2 h-full">
                      {analytics.status_distribution.length > 0 ? (
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie data={analytics.status_distribution} dataKey="count" nameKey="status"
                              cx="50%" cy="50%" innerRadius={60} outerRadius={80} paddingAngle={5}>
                              {analytics.status_distribution.map((entry: any, index: number) => {
                                const colors: Record<string, string> = {
                                  supported: "#10b981", contradicted: "#ef4444", not_enough_information: "#f59e0b"
                                };
                                return <Cell key={`cell-${index}`} fill={colors[entry.status] || "#8b5cf6"} />;
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
                        const labels: Record<string, string> = {
                          supported: "Supported (Auto-Approved)",
                          contradicted: "Contradicted (Auto-Rejected)",
                          not_enough_information: "Insufficient Information"
                        };
                        const bgColors: Record<string, string> = {
                          supported: "bg-emerald-500", contradicted: "bg-danger", not_enough_information: "bg-amber-500"
                        };
                        return (
                          <div key={idx} className="flex items-center justify-between text-xs">
                            <div className="flex items-center gap-2">
                              <span className={`w-3 h-3 rounded-full ${bgColors[entry.status] || "bg-primary"}`} />
                              <span className="text-muted">{labels[entry.status] || entry.status}</span>
                            </div>
                            <span className="font-mono text-white font-bold">{entry.count}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>

                {/* Objects Distribution */}
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
                            {analytics.object_distribution.map((_: any, index: number) => {
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

      {/* ──────────── CLAIM DETAILS SLIDE-OVER PANEL ──────────── */}
      {selectedClaim && (
        <div className="w-130 border-l border-border bg-[#090a0c] flex flex-col h-full overflow-hidden shadow-2xl relative z-20 animate-slideInRight">
          {/* Details header */}
          <div className="p-6 border-b border-border flex items-center justify-between flex-shrink-0">
            <div>
              <span className="text-[10px] text-primary bg-primary/10 border border-primary/20 px-2 py-0.5 rounded font-mono font-bold">
                INVESTIGATION WORKSPACE
              </span>
              <h3 className="text-sm font-bold text-white mt-1.5 font-mono">{selectedClaim.user_id}</h3>
            </div>
            <button
              onClick={() => setSelectedClaim(null)}
              className="text-muted hover:text-white hover:bg-card p-1.5 rounded-lg transition-colors"
            >
              <X className="w-5 h-5" />
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

            {/* Execution Timeline */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-4 flex items-center gap-1.5">
                <Layers className="w-4 h-4 text-primary" /> Autonomous Agent Chronology
              </h4>

              <div className="relative border-l-2 border-border/50 ml-3 pl-5 space-y-4 text-xs">
                {/* 1. Intake */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 flex items-center justify-center font-bold text-[8px]">✓</span>
                  <div>
                    <h5 className="font-semibold text-white">1. Claim Ingestion Agent</h5>
                    <p className="text-[10px] text-muted mt-0.5">Parsed Customer Chat. Object detected: {selectedClaim.claim_object}.</p>
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
                    <h5 className="font-semibold text-white">2. Image Quality Agent</h5>
                    <p className="text-[10px] text-muted mt-0.5">
                      {selectedClaim.valid_image ? "Metadata and frames parsed. Quality validated." : "Quality concerns flagged."}
                    </p>
                  </div>
                </div>

                {/* 3. Vision */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 flex items-center justify-center font-bold text-[8px]">✓</span>
                  <div>
                    <h5 className="font-semibold text-white">3. Vision Analysis Agent (Gemini Vision)</h5>
                    <p className="text-[10px] text-muted mt-0.5">Extracted: {selectedClaim.issue_type} on {selectedClaim.object_part}. Severity: {selectedClaim.severity}.</p>
                  </div>
                </div>

                {/* 4. Evidence Compliance */}
                <div className="relative">
                  <span className={`absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full flex items-center justify-center font-bold text-[8px] ${
                    selectedClaim.evidence_standard_met === "true" || selectedClaim.evidence_standard_met === true
                      ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/50"
                      : "bg-red-500/20 text-red-400 border border-red-500/50"
                  }`}>
                    {selectedClaim.evidence_standard_met === "true" || selectedClaim.evidence_standard_met === true ? "✓" : "!"}
                  </span>
                  <div>
                    <h5 className="font-semibold text-white">4. Evidence Retrieval Agent</h5>
                    <p className="text-[10px] text-muted mt-0.5">
                      Checked requirements: {selectedClaim.evidence_standard_met === "true" || selectedClaim.evidence_standard_met === true ? "Standard verified." : "Compliance standards failed."}
                    </p>
                  </div>
                </div>

                {/* RAG Search */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 flex items-center justify-center font-bold text-[8px]">✓</span>
                  <div>
                    <h5 className="font-semibold text-white">5. Similar Claims Retrieval (Vector RAG)</h5>
                    <p className="text-[10px] text-muted mt-0.5">Vector database searched. Similar verified logs extracted.</p>
                  </div>
                </div>

                {/* User Risk */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 flex items-center justify-center font-bold text-[8px]">✓</span>
                  <div>
                    <h5 className="font-semibold text-white">6. User Risk Agent</h5>
                    <p className="text-[10px] text-muted mt-0.5">History analyzed. Historical Risk Score: {selectedClaim.user_risk_score}/100.</p>
                  </div>
                </div>

                {/* Fraud Intelligence */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/50 flex items-center justify-center font-bold text-[8px]">✓</span>
                  <div>
                    <h5 className="font-semibold text-white">7. Fraud Intelligence Agent</h5>
                    <p className="text-[10px] text-muted mt-0.5">Coordinated checks complete. Fraud index: {selectedClaim.fraud_score}/100.</p>
                  </div>
                </div>

                {/* Decision Agent */}
                <div className="relative">
                  <span className="absolute -left-[27px] top-0 w-3.5 h-3.5 rounded-full bg-primary/20 text-primary border border-primary/50 flex items-center justify-center font-bold text-[8px]">✓</span>
                  <div>
                    <h5 className="font-semibold text-white">8. Decision Agent (Gemini 2.5 Flash)</h5>
                    <p className="text-[10px] text-muted mt-0.5">Autonomously resolved status to {selectedClaim.claim_status.toUpperCase()}.</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Visual Evidence Viewer */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-1.5">
                <ImageIcon className="w-4 h-4 text-emerald-400" /> Submitted Claims Images
              </h4>
              <div className="grid grid-cols-2 gap-3">
                {selectedClaim.image_paths.split(";").map((img_path: string, idx: number) => {
                  const imgName = img_path.split("/").pop() || `img_${idx+1}`;
                  const isSupporting = selectedClaim.supporting_image_ids.includes(`img_${idx+1}`) || selectedClaim.supporting_image_ids === "all" || selectedClaim.supporting_image_ids === "none";
                  return (
                    <div
                      key={idx}
                      className={`p-4 bg-background border rounded-lg flex flex-col items-center justify-center text-center group relative transition-colors ${
                        isSupporting ? "border-emerald-500/40 bg-emerald-500/[0.02]" : "border-border"
                      }`}
                    >
                      <ImageIcon className={`w-8 h-8 ${isSupporting ? "text-emerald-400" : "text-muted"}`} />
                      <span className="text-[10px] font-mono text-muted truncate max-w-full mt-2">{imgName}</span>
                      {isSupporting && selectedClaim.claim_status === "supported" && (
                        <span className="absolute top-1.5 right-1.5 px-1 rounded text-[8px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold font-mono">
                          SUPPORTING
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Similar Claims RAG Search Results */}
            {similarClaims && similarClaims.length > 0 && (
              <div className="bg-card border border-border p-5 rounded-xl">
                <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-1.5">
                  <FileSearch className="w-4 h-4 text-primary" /> Similar Verified Claims (RAG Context)
                </h4>
                <div className="space-y-3">
                  {similarClaims.map((match: any, idx: number) => (
                    <div key={idx} className="bg-background border border-border p-3 rounded-lg text-xs">
                      <div className="flex items-center justify-between font-mono mb-2">
                        <span className="font-semibold text-primary">{match.user_id}</span>
                        <span className="text-[10px] bg-primary/10 border border-primary/20 px-1.5 py-0.5 rounded text-primary font-bold">
                          Match: {Math.round(match.similarity_score * 100)}%
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-muted uppercase text-[9px] font-semibold">{match.claim_object}</span>
                        <span className="text-muted">•</span>
                        <span className="text-muted font-medium">{match.object_part} ({match.issue_type})</span>
                        <span className="text-muted">•</span>
                        <span>{getStatusBadge(match.claim_status)}</span>
                      </div>
                      <p className="text-[11px] text-muted italic">&quot;{match.justification || match.claim_status_justification}&quot;</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Customer Chat Transcript log */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-4 flex items-center gap-1.5">
                <FileSearch className="w-4 h-4 text-amber-400" /> Claims Transcript Logs
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

            {/* Explainable AI justification */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-2 flex items-center gap-1.5">
                <CheckCircle className="w-4 h-4 text-emerald-400" /> Explainability &amp; Reasoning Report
              </h4>
              <p className="text-xs text-muted leading-relaxed font-mono bg-background p-4 rounded-lg border border-border">
                {selectedClaim.claim_status_justification}
              </p>
            </div>

            {/* Raw Audit Logs JSON */}
            <div className="bg-card border border-border p-5 rounded-xl">
              <h4 className="text-xs font-bold text-white mb-3 flex items-center gap-1.5">
                <FileJson className="w-4 h-4 text-muted" /> Audit Log Metadata
              </h4>
              <details className="text-xs cursor-pointer">
                <summary className="text-[10px] text-muted hover:text-white font-mono uppercase">
                  Show Internal Agent Schemas (Pydantic / LangGraph)
                </summary>
                <div className="mt-3 p-3 bg-background rounded-lg border border-border text-[10px] font-mono text-muted overflow-x-auto max-h-60">
                  <pre>{JSON.stringify({
                    claim_id: selectedClaim.id,
                    user_id: selectedClaim.user_id,
                    evidence_retrieval: {
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
                    <ShieldAlert className="w-4 h-4" /> Human Verification Override
                  </h4>
                  <p className="text-[10px] text-muted mt-1 leading-relaxed">
                    Escalation trigger: <span className="text-red-400">{selectedClaim.escalation_reason}</span>
                  </p>
                </div>

                <div className="space-y-2">
                  <label className="text-[10px] text-muted block uppercase font-mono font-semibold">Reviewer Notes</label>
                  <textarea
                    placeholder="Enter manual override justification..."
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
                    Approve Override
                  </button>
                  <button
                    onClick={() => handleManualVerdict(selectedClaim.id, "rejected")}
                    className="flex-1 py-2 text-xs font-bold bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                  >
                    Reject Override
                  </button>
                </div>
              </div>
            )}

            {/* Human Override Verdict Logged */}
            {selectedClaim.manual_verdict && (
              <div className="bg-card border border-border p-5 rounded-xl border-l-4 border-primary">
                <h4 className="text-xs font-bold text-white flex items-center gap-1.5">
                  <User className="w-4 h-4 text-primary" /> Human Review Verdict
                </h4>
                <div className="mt-2 text-xs leading-relaxed space-y-1">
                  <p className="text-muted">
                    Verdict: <span className={`font-semibold capitalize ${selectedClaim.manual_verdict === "approved" ? "text-emerald-400" : "text-red-400"}`}>
                      {selectedClaim.manual_verdict.toUpperCase()}
                    </span>
                  </p>
                  <p className="text-muted">
                    Reviewer Notes: <span className="italic">&quot;{selectedClaim.manual_reviewer_notes || "None"}&quot;</span>
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

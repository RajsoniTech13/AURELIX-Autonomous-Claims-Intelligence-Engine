"use client";

import { useEffect, useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  CheckCircle2, Clock, ShieldCheck, AlertTriangle, UserX, 
  Search, FileText, Image as ImageIcon, Check, Activity, Code
} from "lucide-react";

// `skipped` is a real outcome, not an error: when preflight finds no usable image the
// perception request is never made, because a claim with nothing to look at cannot
// produce a grounded finding. Showing it as skipped rather than complete keeps the UI
// honest about which claims actually cost a model call.
type StageStatus = "pending" | "running" | "complete" | "failed" | "skipped";
type PipelineStages = Record<string, StageStatus>;

interface LiveInvestigationViewerProps {
  stages: PipelineStages;
  claimId?: string;
  files: File[];
  completedTime?: number;
  claimResult?: any;
}

const nodeVariants = {
  hidden: { opacity: 0, scale: 0.9 },
  visible: { opacity: 1, scale: 1 },
  active: { scale: 1.05, boxShadow: "0px 0px 15px rgba(139, 92, 246, 0.4)" }
};

const lineVariants = {
  hidden: { pathLength: 0, opacity: 0 },
  visible: { pathLength: 1, opacity: 1, transition: { duration: 0.5 } }
};

export function LiveInvestigationViewer({ stages, files, completedTime, claimResult }: LiveInvestigationViewerProps) {
  const [selectedLog, setSelectedLog] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll logs
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [stages]);

  const Node = ({ id, label, icon: Icon, delay = 0, isParallel = false }: any) => {
    const status = stages[id] || "pending";
    const isActive = status === "running";
    const isComplete = status === "complete";
    const isSkipped = status === "skipped";
    const isFailed = status === "failed";

    return (
      <motion.div
        variants={nodeVariants}
        initial="hidden"
        animate={isActive ? "active" : "visible"}
        transition={{ delay, duration: 0.3 }}
        className={`relative flex items-center gap-3 p-3 rounded-lg border ${
          isActive
            ? "bg-primary/10 border-primary shadow-[0_0_15px_rgba(139,92,246,0.15)] z-10"
            : isFailed
              ? "bg-destructive/10 border-destructive/50"
              : isComplete
                ? "bg-muted/10 border-border/50 opacity-70"
                : isSkipped
                  ? "bg-muted/5 border-dashed border-border/40 opacity-60"
                  : "bg-background border-border/20 opacity-40"
        } ${isParallel ? 'w-full' : 'w-64 mx-auto'}`}
      >
        <div className={`h-8 w-8 rounded-md flex items-center justify-center shrink-0 ${
          isActive ? "bg-primary text-primary-foreground"
            : isFailed ? "bg-destructive/20 text-destructive"
            : isComplete ? "bg-emerald-500/20 text-emerald-500"
            : "bg-muted text-muted-foreground"
        }`}>
          {isFailed ? <AlertTriangle className="h-4 w-4" />
            : isComplete ? <Check className="h-4 w-4" />
            : isActive ? <Activity className="h-4 w-4 animate-pulse" />
            : <Icon className="h-4 w-4" />}
        </div>
        <div className="flex flex-col flex-1 truncate">
          <span className={`text-sm font-medium truncate ${isActive ? "text-primary" : ""}`}>{label}</span>
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
            {isActive ? "Executing..."
              : isFailed ? "Failed"
              : isSkipped ? "Skipped — no usable image"
              : isComplete ? "Completed"
              : "Waiting"}
          </span>
        </div>
        {isActive && (
          <span className="absolute -top-1 -right-1 flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
          </span>
        )}
      </motion.div>
    );
  };

  const fileUrl = files.length > 0 ? URL.createObjectURL(files[0]) : null;

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] bg-background -mx-6 -mt-6">
      
      {/* Top Header */}
      <div className="h-14 border-b border-border/50 flex items-center justify-between px-6 shrink-0 bg-card/30">
        <div className="flex items-center gap-3">
          <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <h2 className="text-sm font-semibold uppercase tracking-wider">Live Investigation Trace</h2>
        </div>
        {completedTime && (
          <div className="text-xs font-mono bg-emerald-500/10 text-emerald-500 px-2 py-1 rounded border border-emerald-500/20">
            Execution Time: {completedTime.toFixed(2)}s
          </div>
        )}
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Left Pane: Evidence Viewer */}
        <div className="w-[300px] border-r border-border/50 bg-card/10 flex flex-col shrink-0">
          <div className="px-4 py-3 border-b border-border/50 text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <ImageIcon className="h-3.5 w-3.5" /> Context
          </div>
          <div className="p-4 flex-1 overflow-y-auto space-y-4">
            <div className="space-y-2">
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider">Primary Evidence</span>
              {fileUrl ? (
                <div className="rounded-lg overflow-hidden border border-border/50 bg-black aspect-video relative group">
                  <img src={fileUrl} alt="Evidence" className="object-contain w-full h-full opacity-80 group-hover:opacity-100 transition-opacity" />
                  <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity flex items-end p-2">
                    <span className="text-[10px] font-mono text-white/80">{files[0].name}</span>
                  </div>
                </div>
              ) : (
                <div className="aspect-video bg-muted/20 border border-border/30 rounded-lg flex items-center justify-center text-muted-foreground text-xs">
                  No image provided
                </div>
              )}
            </div>
            
            {files.length > 1 && (
              <div className="grid grid-cols-2 gap-2">
                {files.slice(1).map((f, i) => (
                  <div key={i} className="aspect-square bg-muted/20 rounded border border-border/30 overflow-hidden relative">
                    <img src={URL.createObjectURL(f)} alt={`Ev ${i}`} className="object-cover w-full h-full opacity-70" />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Center Pane: Orchestration Graph */}
        <div className="flex-1 flex flex-col relative bg-[#0a0a0c] overflow-y-auto custom-scrollbar p-8">
          <div className="max-w-xl mx-auto w-full flex flex-col items-center space-y-6 pb-20">
            <Node id="preflight" label="Preflight — Quality Gate" icon={ImageIcon} delay={0.1} />

            <div className="h-8 w-px bg-border/50" />

            <div className="w-full relative border border-primary/40 rounded-xl p-6 bg-primary/5">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#0a0a0c] px-3 text-[10px] font-mono text-primary border border-primary/40 rounded-full">
                1 MULTIMODAL REQUEST
              </div>
              <Node id="perception" label="Perception" icon={Search} isParallel delay={0.2} />
            </div>

            <div className="h-8 w-px bg-border/50" />

            <div className="w-full relative border border-border/30 rounded-xl p-6 bg-card/5">
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-[#0a0a0c] px-3 text-[10px] font-mono text-muted-foreground border border-border/30 rounded-full">
                DETERMINISTIC — NO MODEL
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Node id="policy_verification" label="Policy Check" icon={ShieldCheck} isParallel delay={0.3} />
                <Node id="user_risk" label="User Risk" icon={UserX} isParallel delay={0.4} />
                <Node id="alignment" label="Claim vs Evidence" icon={FileText} isParallel delay={0.5} />
              </div>
            </div>

            <div className="h-8 w-px bg-border/50" />
            <Node id="decision" label="Fraud, Confidence & Verdict" icon={CheckCircle2} delay={0.6} />
          </div>
        </div>

        {/* Right Pane: Summary */}
        <div className="w-[320px] border-l border-border/50 bg-card/10 flex flex-col shrink-0">
          <div className="px-4 py-3 border-b border-border/50 text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <Activity className="h-3.5 w-3.5" /> Output Summary
          </div>
          <div className="p-5 overflow-y-auto space-y-6">
            {!claimResult ? (
              <div className="flex flex-col items-center justify-center h-40 text-muted-foreground opacity-50">
                <Activity className="h-8 w-8 mb-2 animate-pulse" />
                <span className="text-xs">Awaiting final decision...</span>
              </div>
            ) : (
              <AnimatePresence>
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
                  {/* Status */}
                  <div className={`p-4 rounded-lg border ${
                    claimResult.claim_status === 'supported' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-500' :
                    claimResult.claim_status === 'contradicted' ? 'bg-destructive/10 border-destructive/20 text-destructive' :
                    'bg-amber-500/10 border-amber-500/20 text-amber-500'
                  }`}>
                    <div className="text-[10px] uppercase tracking-wider font-semibold mb-1 opacity-80">Verdict</div>
                    <div className="text-xl font-bold capitalize tracking-tight">{claimResult.claim_status.replace(/_/g, ' ')}</div>
                    <p className="text-xs mt-2 opacity-90 leading-relaxed">{claimResult.claim_status_justification}</p>
                  </div>

                  {/* Confidence */}
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">Confidence</span>
                      <span className="font-mono">{claimResult.confidence_score}%</span>
                    </div>
                    <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                      <div 
                        className={`h-full ${claimResult.confidence_score >= 90 ? 'bg-emerald-500' : claimResult.confidence_score >= 70 ? 'bg-amber-500' : 'bg-destructive'}`}
                        style={{ width: `${claimResult.confidence_score}%` }}
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="bg-card border border-border/50 rounded p-3">
                      <div className="text-[10px] text-muted-foreground uppercase mb-1">Fraud Score</div>
                      <div className={`font-mono ${claimResult.fraud_score > 70 ? 'text-destructive' : 'text-emerald-500'}`}>
                        {claimResult.fraud_score}/100
                      </div>
                    </div>
                    <div className="bg-card border border-border/50 rounded p-3">
                      <div className="text-[10px] text-muted-foreground uppercase mb-1">User Risk</div>
                      <div className={`font-mono capitalize ${claimResult.risk_level === 'HIGH' ? 'text-destructive' : claimResult.risk_level === 'MEDIUM' ? 'text-amber-500' : 'text-emerald-500'}`}>
                        {claimResult.risk_level}
                      </div>
                    </div>
                  </div>

                  {claimResult.manual_review_required && (
                    <div className="bg-amber-500/10 border border-amber-500/20 rounded p-3 text-amber-500">
                      <div className="flex items-center gap-1.5 mb-1">
                        <ShieldCheck className="h-3.5 w-3.5" />
                        <span className="text-xs font-bold uppercase tracking-wider">Escalated</span>
                      </div>
                      <div className="text-xs opacity-90 leading-relaxed">
                        {claimResult.escalation_reason}
                      </div>
                    </div>
                  )}
                </motion.div>
              </AnimatePresence>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Pane: Logs / Raw Output */}
      <div className="h-48 border-t border-border/50 bg-[#09090b] shrink-0 flex flex-col">
        <div className="h-8 border-b border-border/30 flex items-center px-4 bg-card/30 shrink-0">
          <Code className="h-3 w-3 text-muted-foreground mr-2" />
          <span className="text-[10px] uppercase font-mono text-muted-foreground">Execution Logs</span>
        </div>
        <div className="flex-1 overflow-y-auto p-4 font-mono text-[10px] text-muted-foreground space-y-1.5 custom-scrollbar" ref={scrollRef}>
          {Object.entries(stages).map(([stage, status]) => (
            status !== "pending" && (
              <div key={stage} className="flex gap-4">
                <span className="text-primary/70 shrink-0 w-24">[{new Date().toISOString().split('T')[1].slice(0, -1)}]</span>
                <span className="text-emerald-500/70 shrink-0 w-20">[{status.toUpperCase()}]</span>
                <span className="text-foreground/80">Agent <span className="text-primary">{stage}</span> executed</span>
              </div>
            )
          ))}
          {claimResult && (
            <div className="mt-4 pt-4 border-t border-border/30">
              <span className="text-primary/70">[{new Date().toISOString().split('T')[1].slice(0, -1)}]</span>
              <span className="text-emerald-500/70 ml-4">[DONE]</span>
              <span className="text-foreground/80 ml-4">Final JSON emitted:</span>
              <pre className="mt-2 ml-[152px] text-muted-foreground overflow-x-auto p-2 bg-black/50 rounded border border-border/30">
                {JSON.stringify(claimResult, null, 2)}
              </pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

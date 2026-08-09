"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UploadCloud, ChevronRight, ChevronLeft, Image as ImageIcon, CheckCircle2, Zap, AlertTriangle } from "lucide-react";
import { submitClaimStream } from "@/lib/api";
import { LiveInvestigationViewer } from "./LiveInvestigationViewer";

type StageStatus = "pending" | "running" | "complete" | "failed" | "skipped";
type PipelineStages = Record<string, StageStatus>;

// Mirrors PIPELINE_STAGES in agent_core/service.py. Only `perception` reaches the
// network; everything after it is deterministic Python, which is why a verdict can be
// re-derived without spending quota.
const INITIAL_STAGES: PipelineStages = {
  preflight: "pending",
  duplicate_check: "pending",
  perception: "pending",
  policy_verification: "pending",
  user_risk: "pending",
  alignment: "pending",
  decision: "pending"
};

export function SubmitClaimTab({ onClaimSubmitted }: { onClaimSubmitted: (claim: any) => void }) {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stages, setStages] = useState<PipelineStages>(INITIAL_STAGES);
  const [startTime, setStartTime] = useState<number | null>(null);
  const [claimResult, setClaimResult] = useState<any>(null);
  
  const [userId, setUserId] = useState("user_002");
  const [claimObject, setClaimObject] = useState("car");
  const [userClaim, setUserClaim] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const handleNext = () => setStep(s => Math.min(s + 1, 4));
  const handlePrev = () => setStep(s => Math.max(s - 1, 1));

  const handleSubmit = async () => {
    if (files.length === 0) {
      setError("Evidence required.");
      setStep(3);
      return;
    }
    if (!userClaim.trim()) {
      setError("Description required.");
      setStep(2);
      return;
    }

    setStep(5); // Live Investigation
    setLoading(true);
    setError(null);
    setStages(INITIAL_STAGES);
    const start = performance.now();
    setStartTime(start);

    const formData = new FormData();
    formData.append("user_id", userId);
    formData.append("claim_object", claimObject);
    formData.append("user_claim", userClaim);
    files.forEach(f => formData.append("files", f));

    try {
      await submitClaimStream(formData, (event) => {
        console.log("[SSE Event Received]:", event);
        if (event.stage === "done") {
          console.log("[SSE] Done! Setting claim result.");
          setLoading(false);
          setClaimResult(event.claim);
        } else if (event.stage && event.status) {
          console.log(`[SSE] Updating stage ${event.stage} to ${event.status}`);
          setStages(prev => ({ ...prev, [event.stage]: event.status }));
        }
      });
    } catch (err: any) {
      setError(err.message || "Investigation failed.");
      setLoading(false);
    }
  };

  if (step === 5) {
    return (
      <div className="space-y-4">
        {error && (
          <div className="p-4 rounded-md bg-destructive/15 text-destructive border border-destructive/20 font-mono text-sm">
            ERROR: {error}
          </div>
        )}
        <LiveInvestigationViewer 
          stages={stages} 
          files={files}
          completedTime={startTime && !loading ? (performance.now() - startTime) / 1000 : undefined}
          claimResult={claimResult}
        />
      </div>
    );
  }

  const steps = [
    { id: 1, name: "Customer" },
    { id: 2, name: "Details" },
    { id: 3, name: "Evidence" },
    { id: 4, name: "Launch" },
  ];

  return (
    <div className="max-w-3xl mx-auto mt-4">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">New Investigation</h2>
          <p className="text-sm text-muted-foreground mt-1">Configure parameters for autonomous AI review.</p>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono">
          {steps.map(s => (
            <div key={s.id} className="flex items-center gap-2">
              <span className={`flex items-center justify-center h-6 w-6 rounded-full border ${
                step === s.id ? "bg-primary text-primary-foreground border-primary" 
                : step > s.id ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20" 
                : "border-border text-muted-foreground"
              }`}>
                {step > s.id ? <CheckCircle2 className="h-3.5 w-3.5" /> : s.id}
              </span>
              {s.id !== 4 && <span className="w-8 h-px bg-border/50 hidden sm:block" />}
            </div>
          ))}
        </div>
      </div>

      {error && (
        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="mb-6 p-4 bg-destructive/10 text-destructive border border-destructive/20 rounded-lg text-sm flex items-center gap-2">
          <AlertTriangle className="h-4 w-4" /> {error}
        </motion.div>
      )}

      <div className="bg-card border border-border/50 rounded-xl overflow-hidden shadow-lg shadow-black/20">
        <div className="p-8 min-h-[300px]">
          <AnimatePresence mode="wait">
            {step === 1 && (
              <motion.div key="1" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-foreground">Customer Context</h3>
                  <p className="text-xs text-muted-foreground">Used for history checks and fraud profiling.</p>
                </div>
                <div className="space-y-2">
                  <label className="text-xs uppercase tracking-wider font-semibold text-muted-foreground">Policyholder ID</label>
                  <Input 
                    value={userId} 
                    onChange={e => setUserId(e.target.value)} 
                    className="max-w-sm bg-background border-border/50 focus-visible:ring-primary h-10"
                  />
                </div>
              </motion.div>
            )}

            {step === 2 && (
              <motion.div key="2" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-foreground">Incident Details</h3>
                  <p className="text-xs text-muted-foreground">Classify the object and provide raw testimony.</p>
                </div>
                <div className="grid gap-6">
                  <div className="space-y-2">
                    <label className="text-xs uppercase tracking-wider font-semibold text-muted-foreground">Object Category</label>
                    <Select value={claimObject} onValueChange={(val) => setClaimObject(val || "")}>
                      <SelectTrigger className="max-w-sm bg-background border-border/50 h-10">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="car">Vehicle</SelectItem>
                        <SelectItem value="laptop">Electronics (Laptop)</SelectItem>
                        <SelectItem value="package">Freight / Package</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs uppercase tracking-wider font-semibold text-muted-foreground">Claimant Testimony</label>
                    <Textarea
                      value={userClaim}
                      onChange={e => setUserClaim(e.target.value)}
                      placeholder="e.g., I hit a pole while reversing..."
                      className="min-h-[120px] bg-background border-border/50 resize-none focus-visible:ring-primary"
                    />
                  </div>
                </div>
              </motion.div>
            )}

            {step === 3 && (
              <motion.div key="3" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-foreground">Visual Evidence</h3>
                  <p className="text-xs text-muted-foreground">AURELIX Vision Agents require clear, well-lit photography.</p>
                </div>
                <div className="space-y-4">
                  <div className="border border-dashed border-border rounded-xl p-12 flex flex-col items-center justify-center bg-muted/5 hover:bg-muted/10 transition-colors relative group">
                    <UploadCloud className="h-8 w-8 text-muted-foreground mb-4 group-hover:text-primary transition-colors" />
                    <Input type="file" multiple accept="image/*" onChange={e => setFiles(Array.from(e.target.files || []))} className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" />
                    <p className="text-sm font-medium">Click or drag images here</p>
                    <p className="text-xs text-muted-foreground mt-1">JPEG, PNG, WebP</p>
                  </div>
                  {files.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {files.map((f, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs bg-card border border-border/50 rounded p-2">
                          <ImageIcon className="h-3 w-3 text-primary shrink-0" />
                          <span className="truncate max-w-[150px]">{f.name}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </motion.div>
            )}

            {step === 4 && (
              <motion.div key="4" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
                <div>
                  <h3 className="text-lg font-medium text-foreground">Final Verification</h3>
                  <p className="text-xs text-muted-foreground">Ready to deploy 7 autonomous agents.</p>
                </div>
                
                <div className="bg-background border border-border/50 rounded-lg p-5 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground tracking-wider mb-1">Target Identity</div>
                      <div className="font-mono text-sm">{userId}</div>
                    </div>
                    <div>
                      <div className="text-[10px] uppercase text-muted-foreground tracking-wider mb-1">Object Class</div>
                      <div className="text-sm capitalize">{claimObject}</div>
                    </div>
                  </div>
                  <div className="pt-3 border-t border-border/30">
                    <div className="text-[10px] uppercase text-muted-foreground tracking-wider mb-1">Raw Testimony</div>
                    <div className="text-sm opacity-90 leading-relaxed bg-muted/20 p-3 rounded">{userClaim}</div>
                  </div>
                  <div className="pt-3 border-t border-border/30">
                    <div className="text-[10px] uppercase text-muted-foreground tracking-wider mb-1">Attachments</div>
                    <div className="text-sm font-medium text-primary flex items-center gap-2">
                      <ImageIcon className="h-4 w-4" /> {files.length} valid images queued
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        
        <div className="px-8 py-5 border-t border-border/50 bg-muted/5 flex items-center justify-between">
          <button 
            onClick={handlePrev} 
            disabled={step === 1}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50 transition-colors"
          >
            <ChevronLeft className="h-4 w-4" /> Back
          </button>
          
          {step < 4 ? (
            <button 
              onClick={handleNext}
              className="flex items-center gap-2 bg-foreground text-background hover:bg-foreground/90 px-5 py-2 rounded-md text-sm font-medium transition-colors"
            >
              Continue <ChevronRight className="h-4 w-4" />
            </button>
          ) : (
            <button 
              onClick={handleSubmit}
              className="flex items-center gap-2 bg-primary text-primary-foreground hover:bg-primary/90 px-6 py-2 rounded-md text-sm font-semibold transition-colors shadow-lg shadow-primary/20"
            >
              Launch Agents <Zap className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

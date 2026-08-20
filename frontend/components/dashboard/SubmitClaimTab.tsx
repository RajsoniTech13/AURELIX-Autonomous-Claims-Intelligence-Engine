"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UploadCloud, ChevronRight, ChevronLeft, Image as ImageIcon, FileText, CheckCircle2, Zap, AlertTriangle } from "lucide-react";
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
  document_check: "pending",
  decision: "pending"
};

export function SubmitClaimTab({
  onClaimSubmitted,
  onNavigate,
}: {
  onClaimSubmitted: (claim: any) => void;
  onNavigate?: (tab: string) => void;
}) {
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
  const [docs, setDocs] = useState<File[]>([]);

  /**
   * Per-step validity.
   *
   * Submission used to validate only at the end, then throw the user back to
   * step 2 or 3 with "Description required." — a bare fragment, after they had
   * already reached the launch screen. Each step now states its own requirement
   * and the Continue button reflects it, so the wizard cannot be completed into
   * a failure.
   */
  const stepIssue = (s: number): string | null => {
    if (s === 1 && !userId.trim()) return "Enter the policyholder ID to continue.";
    if (s === 2 && !userClaim.trim()) return "Describe what happened to continue.";
    if (s === 3 && files.length === 0) return "Attach at least one photograph to continue.";
    return null;
  };
  const blocked = stepIssue(step);

  const handleNext = () => { if (!blocked) setStep(s => Math.min(s + 1, 4)); };
  const handlePrev = () => setStep(s => Math.max(s - 1, 1));

  const handleReset = () => {
    setStep(1);
    setStages(INITIAL_STAGES);
    setClaimResult(null);
    setError(null);
    setUserClaim("");
    setFiles([]);
    setDocs([]);
  };

  const handleSubmit = async () => {
    // Belt and braces: the wizard cannot normally reach step 4 in an invalid
    // state, but a jump would otherwise spend a model request on a claim that
    // has nothing to analyse.
    for (const s of [1, 2, 3]) {
      const issue = stepIssue(s);
      if (issue) { setError(issue); setStep(s); return; }
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
    docs.forEach(f => formData.append("documents", f));

    try {
      await submitClaimStream(formData, (event) => {
        if (event.stage === "done") {
          setLoading(false);
          setClaimResult(event.claim);
        } else if (event.stage && event.status) {
          setStages(prev => ({ ...prev, [event.stage]: event.status }));
        }
      });
    } catch (err: any) {
      setError(err?.message || "The investigation could not be completed.");
      setLoading(false);
    }
  };

  if (step === 5) {
    return (
      <div className="space-y-4">
        {/* An error state that says what happened, what it means for the data,
            and what to do — not a red bar with an exception in it. */}
        {error && (
          <div className="rounded-lg border border-(--state-contra)/25 bg-(--state-contra-weak) p-4
                          flex flex-col sm:flex-row sm:items-start gap-3">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-(--state-contra)" aria-hidden />
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-medium text-(--state-contra)">
                Investigation could not be completed
              </p>
              <p className="text-[13px] leading-relaxed text-text-2 mt-1">{error}</p>
              <p className="text-[12px] text-muted-foreground mt-1.5">
                No decision was recorded. Your evidence and description are still attached.
              </p>
            </div>
            <button
              onClick={handleReset}
              className="shrink-0 h-8 px-3 rounded-md border border-line hover:bg-surface-2 text-[13px]
                         font-medium transition-colors duration-(--dur-fast)"
            >
              Start over
            </button>
          </div>
        )}
        <LiveInvestigationViewer
          stages={stages}
          files={files}
          completedTime={startTime && !loading ? (performance.now() - startTime) / 1000 : undefined}
          claimResult={claimResult}
          onOpenFullReport={() => claimResult && onClaimSubmitted(claimResult)}
          onRestart={handleReset}
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
          {/*
            No AnimatePresence here, deliberately.

            This wizard was unusable. The panels were four `&&` conditionals inside an
            `AnimatePresence mode="wait"`, which is itself nested inside the page-level
            `mode="wait"` in app/page.tsx. The outgoing panel's exit never completed, so the
            incoming one never mounted: `step` climbed 1 → 2 → 3 → 4 with every press of
            Continue while the screen kept rendering step 1. The fourth press ran a real
            analysis, spending one of twenty daily requests, from a form the user had never
            been shown. Keying a single child by `step` fixed the first transition and the
            deadlock simply moved to the second.

            `mode="wait"` buys a 180ms cross-fade. It is not worth a wizard that silently
            advances behind the user's back, so the exit animation is gone and the panel
            swaps on the key. Entry is still animated; nothing has to finish before the next
            thing can start.
          */}
          <div>
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.18 }}
              className="space-y-6"
            >
            {step === 1 && (
              <>
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
              </>
            )}

            {step === 2 && (
              <>
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
              </>
            )}

            {step === 3 && (
              <>
                <div>
                  <h3 className="text-lg font-medium text-foreground">Evidence</h3>
                  <p className="text-xs text-muted-foreground">
                    Photographs are required. Supporting paperwork is optional but is
                    cross-checked against them.
                  </p>
                </div>

                <div className="space-y-5">
                  {/* ── Photographs ─────────────────────────────────────── */}
                  <div className="space-y-3">
                    <div className="flex items-baseline justify-between">
                      <label className="text-xs uppercase tracking-wider font-semibold text-muted-foreground">
                        Photographs
                      </label>
                      <span className="text-[11px] text-muted-foreground">Required · up to 6</span>
                    </div>
                    <div className="border border-dashed border-border rounded-xl p-8 flex flex-col items-center justify-center bg-muted/5 hover:bg-muted/10 transition-colors relative group focus-within:border-primary">
                      <UploadCloud className="h-7 w-7 text-muted-foreground mb-3 group-hover:text-primary transition-colors" aria-hidden />
                      <Input
                        type="file" multiple accept="image/*"
                        aria-label="Claim photographs"
                        onChange={e => setFiles(Array.from(e.target.files || []))}
                        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                      />
                      <p className="text-sm font-medium">Click or drag photographs here</p>
                      <p className="text-xs text-muted-foreground mt-1">JPEG, PNG, WebP</p>
                    </div>
                    {files.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {files.map((f, i) => (
                          <span key={i} className="flex items-center gap-2 text-xs bg-card border border-border/50 rounded p-2">
                            <ImageIcon className="h-3 w-3 text-primary shrink-0" aria-hidden />
                            <span className="truncate max-w-[150px]">{f.name}</span>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/*
                    Supporting documents.

                    This is what turns "there is damage" into "this is the repair
                    being paid for". The invoice, estimate or report is read in the
                    SAME model request as the photographs — it costs tokens, not an
                    extra call — and is then cross-checked deterministically against
                    what the camera actually recorded.
                  */}
                  <div className="space-y-3 pt-1 border-t border-border/40">
                    <div className="flex items-baseline justify-between pt-4">
                      <label className="text-xs uppercase tracking-wider font-semibold text-muted-foreground">
                        Supporting documents
                      </label>
                      <span className="text-[11px] text-muted-foreground">Optional · up to 3</span>
                    </div>
                    <div className="border border-dashed border-border rounded-xl p-6 flex flex-col items-center justify-center bg-muted/5 hover:bg-muted/10 transition-colors relative group focus-within:border-primary">
                      <FileText className="h-6 w-6 text-muted-foreground mb-2.5 group-hover:text-primary transition-colors" aria-hidden />
                      <Input
                        type="file" multiple accept="application/pdf,image/*"
                        aria-label="Supporting documents"
                        onChange={e => setDocs(Array.from(e.target.files || []))}
                        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                      />
                      <p className="text-sm font-medium">Invoice, repair estimate, receipt or report</p>
                      <p className="text-xs text-muted-foreground mt-1">PDF, JPEG, PNG, WebP</p>
                    </div>
                    {docs.length > 0 && (
                      <div className="flex flex-wrap gap-2">
                        {docs.map((f, i) => (
                          <span key={i} className="flex items-center gap-2 text-xs bg-card border border-border/50 rounded p-2">
                            <FileText className="h-3 w-3 text-primary shrink-0" aria-hidden />
                            <span className="truncate max-w-[150px]">{f.name}</span>
                          </span>
                        ))}
                      </div>
                    )}
                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                      Paperwork is read in the same model request as the photographs, then
                      compared against them — the object it names, the parts it itemises and
                      the amount it quotes.
                    </p>
                  </div>
                </div>
              </>
            )}

            {step === 4 && (
              <>
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
                      <ImageIcon className="h-4 w-4" aria-hidden /> {files.length} photograph{files.length === 1 ? "" : "s"}
                      {docs.length > 0 && <> · {docs.length} document{docs.length === 1 ? "" : "s"}</>}
                    </div>
                  </div>
                </div>
              </>
            )}
            </motion.div>
          </div>
        </div>
        
        <div className="px-5 sm:px-8 py-5 border-t border-border/50 bg-muted/5 flex items-center justify-between gap-4">
          <button
            onClick={handlePrev}
            disabled={step === 1}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground
                       disabled:opacity-40 disabled:pointer-events-none transition-colors duration-(--dur-fast)"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden /> Back
          </button>

          <div className="flex items-center gap-3 min-w-0">
            {/* The requirement, stated next to the control it blocks, rather
                than discovered after pressing Launch. */}
            {blocked && (
              <span className="text-[12px] text-muted-foreground hidden sm:block truncate">{blocked}</span>
            )}
            {step < 4 ? (
              <button
                onClick={handleNext}
                disabled={!!blocked}
                aria-describedby={blocked ? "step-requirement" : undefined}
                className="flex items-center gap-2 bg-foreground text-background hover:bg-foreground/90
                           disabled:opacity-40 disabled:pointer-events-none px-5 py-2 rounded-md text-sm
                           font-medium transition-colors duration-(--dur-fast) shrink-0"
              >
                Continue <ChevronRight className="h-4 w-4" aria-hidden />
              </button>
            ) : (
              <button
                onClick={handleSubmit}
                className="flex items-center gap-2 bg-primary text-primary-foreground hover:bg-(--aurelix-accent-hover)
                           px-6 py-2 rounded-md text-sm font-semibold transition-colors duration-(--dur-fast) shrink-0"
              >
                Launch Agents <Zap className="h-4 w-4" aria-hidden />
              </button>
            )}
          </div>
        </div>
      </div>

      {blocked && (
        <p id="step-requirement" className="sm:hidden text-[12px] text-muted-foreground mt-3 text-center">
          {blocked}
        </p>
      )}
    </div>
  );
}

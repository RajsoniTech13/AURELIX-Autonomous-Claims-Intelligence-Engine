"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { 
  CheckCircle2, XCircle, AlertCircle, Clock, ShieldCheck, 
  ShieldX, UserX, AlertTriangle, Image as ImageIcon, 
  GitMerge, GitPullRequest, GitCommit, FileText, Zap, MessageSquare, Bot
} from "lucide-react";
import { Button } from "@/components/ui/button";

function FormattedText({ text }: { text: string }) {
  if (!text) return null;
  const paragraphs = text.includes("\n\n") ? text.split("\n\n") : text.split("\n");
  
  return (
    <div className="space-y-3">
      {paragraphs.map((p, idx) => {
        const trimmed = p.trim();
        if (!trimmed) return null;
        return (
          <p key={idx} className="text-sm leading-relaxed text-foreground/90">{trimmed.replace(/\*/g, '')}</p>
        );
      })}
    </div>
  );
}

export function ClaimReviewTab({ claim }: { claim: any }) {
  if (!claim) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-muted-foreground border border-dashed border-border/50 rounded-xl m-8">
        <GitPullRequest className="h-10 w-10 mb-4 opacity-20" />
        <p className="text-sm">No investigation selected. Select a claim from the queue.</p>
      </div>
    );
  }

  const isSupported = claim.claim_status === "supported";
  const isContradicted = claim.claim_status === "contradicted";
  const isEscalated = claim.manual_review_required;
  
  const imagePaths = claim.image_paths && claim.image_paths !== "none" ? claim.image_paths.split(";") : [];
  const logs = claim.audit_logs || [];

  return (
    <div className="max-w-6xl mx-auto space-y-6 mt-4 pb-20">
      {/* PR Header */}
      <div className="border-b border-border/50 pb-6">
        <div className="flex items-start justify-between gap-4 mb-3">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground flex items-center gap-3">
            Investigation: {claim.claim_object.charAt(0).toUpperCase() + claim.claim_object.slice(1)} Damage 
            <span className="text-muted-foreground font-mono font-normal">#INV-{claim.id?.toString().padStart(4, '0') || '0001'}</span>
          </h1>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="h-8 text-xs font-medium border-border/50">Edit Labels</Button>
            {isEscalated ? (
              <Button size="sm" className="h-8 text-xs font-medium bg-amber-500 hover:bg-amber-600 text-amber-950">Review Required</Button>
            ) : (
              <Button size="sm" className="h-8 text-xs font-medium bg-emerald-500 hover:bg-emerald-600 text-emerald-950">Approve Auto-Resolution</Button>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {isSupported ? (
            <div className="flex items-center gap-1.5 bg-emerald-500/10 text-emerald-500 px-3 py-1 rounded-full font-medium border border-emerald-500/20">
              <GitMerge className="h-4 w-4" /> Approved
            </div>
          ) : isContradicted ? (
            <div className="flex items-center gap-1.5 bg-destructive/10 text-destructive px-3 py-1 rounded-full font-medium border border-destructive/20">
              <XCircle className="h-4 w-4" /> Contradicted
            </div>
          ) : (
            <div className="flex items-center gap-1.5 bg-amber-500/10 text-amber-500 px-3 py-1 rounded-full font-medium border border-amber-500/20">
              <AlertCircle className="h-4 w-4" /> Escalated
            </div>
          )}
          <span className="text-muted-foreground">
            <span className="font-semibold text-foreground">Orchestrator</span> launched this investigation {new Date(claim.created_at || Date.now()).toLocaleString()}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        
        {/* Left Column: Timeline / PR Discussion */}
        <div className="lg:col-span-3 space-y-6">
          
          {/* Initial Intake (User) */}
          <div className="flex gap-4">
            <div className="shrink-0 h-8 w-8 rounded-full bg-muted flex items-center justify-center border border-border mt-1">
              <UserX className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="flex-1 border border-border/50 rounded-lg overflow-hidden bg-card">
              <div className="bg-muted/30 px-4 py-2 text-xs border-b border-border/50 text-muted-foreground flex items-center justify-between">
                <div>
                  <span className="font-semibold text-foreground mr-1">{claim.user_id}</span> 
                  submitted the initial claim
                </div>
                <span className="font-mono">intake_node</span>
              </div>
              <div className="p-4 space-y-4">
                <p className="text-sm italic border-l-2 border-border pl-3 text-foreground/80">{claim.user_claim}</p>
                {imagePaths.length > 0 && (
                  <div className="flex flex-wrap gap-2 pt-2">
                    {imagePaths.map((path: string, i: number) => (
                      <div key={i} className="h-24 rounded border border-border/50 overflow-hidden">
                        <img src={`http://127.0.0.1:8000/${path}`} alt="Evidence" className="h-full object-cover" />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="pl-[15px] border-l-2 border-border/50 py-2 ml-4">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground -ml-[22px] bg-background w-fit pr-4">
              <Zap className="h-3.5 w-3.5 text-primary" /> Parallel Fan-Out Execution
            </div>
          </div>

          {/* AI Agent Comments (Audit Logs) */}
          {logs.length > 0 ? logs.map((log: any, idx: number) => (
            <div key={idx} className="flex gap-4">
              <div className="shrink-0 h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 mt-1 relative">
                <Bot className="h-4 w-4 text-primary" />
                <div className="absolute -bottom-1 -right-1 bg-background rounded-full border border-border p-0.5">
                  <CheckCircle2 className="h-2 w-2 text-emerald-500" />
                </div>
              </div>
              <div className="flex-1 border border-primary/20 rounded-lg overflow-hidden bg-card/50 shadow-sm">
                <div className="bg-primary/5 px-4 py-2 text-xs border-b border-primary/10 text-muted-foreground flex items-center justify-between">
                  <div>
                    <span className="font-semibold text-primary mr-1">{log.agent_name}</span> 
                    completed analysis
                  </div>
                  <span className="font-mono opacity-50">{new Date(log.timestamp).toLocaleTimeString()}</span>
                </div>
                <div className="p-4">
                  <FormattedText text={log.reasoning} />
                </div>
              </div>
            </div>
          )) : (
            <div className="flex gap-4">
              <div className="shrink-0 h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center border border-primary/20 mt-1">
                <Bot className="h-4 w-4 text-primary" />
              </div>
              <div className="flex-1 border border-primary/20 rounded-lg overflow-hidden bg-card/50">
                <div className="bg-primary/5 px-4 py-2 text-xs border-b border-primary/10 text-muted-foreground">
                  <span className="font-semibold text-primary mr-1">Final Decision Agent</span> 
                </div>
                <div className="p-4">
                  <FormattedText text={claim.claim_status_justification} />
                  {claim.escalation_reason && (
                    <div className="mt-4 p-3 bg-amber-500/10 border-l-2 border-l-amber-500 rounded-r text-sm text-amber-500">
                      <strong>Escalation:</strong> {claim.escalation_reason}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="pl-[15px] border-l-2 border-border/50 py-2 ml-4">
            <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground -ml-[19px] bg-background w-fit pr-4">
              <GitCommit className="h-4 w-4 text-muted-foreground" /> State machine resolved and finalized.
            </div>
          </div>

        </div>

        {/* Right Column: Metadata Sidebar */}
        <div className="space-y-6">
          <div className="space-y-3">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50 pb-2">Reviewers</h3>
            <div className="space-y-2">
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div className="h-5 w-5 rounded-full bg-primary/20 flex items-center justify-center"><Bot className="h-3 w-3 text-primary" /></div>
                  <span className="font-medium text-foreground">Vision Agent</span>
                </div>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
              </div>
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div className="h-5 w-5 rounded-full bg-primary/20 flex items-center justify-center"><Bot className="h-3 w-3 text-primary" /></div>
                  <span className="font-medium text-foreground">Policy Agent</span>
                </div>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
              </div>
              <div className="flex items-center justify-between text-sm">
                <div className="flex items-center gap-2">
                  <div className="h-5 w-5 rounded-full bg-primary/20 flex items-center justify-center"><Bot className="h-3 w-3 text-primary" /></div>
                  <span className="font-medium text-foreground">Fraud Agent</span>
                </div>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
              </div>
            </div>
          </div>

          <div className="space-y-3">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50 pb-2">Labels</h3>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline" className={`border-emerald-500/30 text-emerald-500 bg-emerald-500/10`}>Policy: {claim.policy_status}</Badge>
              <Badge variant="outline" className={`border-primary/30 text-primary bg-primary/10`}>Object: {claim.claim_object}</Badge>
              <Badge variant="outline" className={`border-amber-500/30 text-amber-500 bg-amber-500/10 capitalize`}>Risk: {claim.risk_level}</Badge>
            </div>
          </div>

          <div className="space-y-3">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50 pb-2">AI Confidence</h3>
            <div>
              <div className="flex justify-between text-sm mb-1 font-medium">
                <span>Final Decision</span>
                <span className="font-mono">{claim.confidence_score}%</span>
              </div>
              <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
                <div 
                  className={`h-full ${claim.confidence_score >= 90 ? 'bg-emerald-500' : claim.confidence_score >= 70 ? 'bg-amber-500' : 'bg-destructive'}`}
                  style={{ width: `${claim.confidence_score}%` }}
                />
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

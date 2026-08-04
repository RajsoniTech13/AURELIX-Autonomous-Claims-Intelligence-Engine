"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getReviewQueue, submitVerdict } from "@/lib/api";
import { 
  Loader2, Search, Filter, ShieldAlert, CheckCircle2, 
  XCircle, AlertCircle, Clock, ChevronRight, User, Hash 
} from "lucide-react";
import { Textarea } from "@/components/ui/textarea";

export function ReviewQueueTab() {
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [processingId, setProcessingId] = useState<number | null>(null);
  const [notes, setNotes] = useState<{ [id: number]: string }>({});
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const fetchQueue = async () => {
    try {
      setLoading(true);
      const data = await getReviewQueue();
      setQueue(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || "Failed to load queue.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, []);

  const handleVerdict = async (claimId: number, verdict: string) => {
    try {
      setProcessingId(claimId);
      await submitVerdict(claimId, verdict, notes[claimId] || "");
      await fetchQueue(); 
    } catch (err: any) {
      setError(`Failed to submit verdict for claim ${claimId}.`);
    } finally {
      setProcessingId(null);
      setExpandedId(null);
    }
  };

  const getPriorityColor = (score: number) => {
    if (score < 50) return "text-destructive bg-destructive/10 border-destructive/20";
    if (score < 70) return "text-amber-500 bg-amber-500/10 border-amber-500/20";
    return "text-blue-500 bg-blue-500/10 border-blue-500/20";
  };

  const getPriorityLabel = (score: number) => {
    if (score < 50) return "High Priority";
    if (score < 70) return "Medium Priority";
    return "Low Priority";
  };

  if (loading && queue.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] text-muted-foreground space-y-4">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
        <span className="text-sm font-mono uppercase tracking-wider">Syncing Queue...</span>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6 mt-4 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/50 pb-6">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground flex items-center gap-2">
            <ShieldAlert className="h-6 w-6 text-amber-500" />
            Manual Review Queue
          </h2>
          <p className="text-sm text-muted-foreground mt-1">Investigate {queue.length} claims escalated by AURELIX AI.</p>
        </div>
        
        <div className="flex items-center gap-3">
          <div className="relative group">
            <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground group-focus-within:text-primary transition-colors" />
            <input 
              type="text" 
              placeholder="Search by ID, User, or Context..." 
              className="h-9 w-[280px] bg-background border border-border/50 rounded-md pl-9 pr-4 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 transition-all placeholder:text-muted-foreground/50"
            />
          </div>
          <Button variant="outline" size="sm" className="h-9 gap-2 text-muted-foreground border-border/50 hover:bg-muted/30">
            <Filter className="h-4 w-4" /> Filter
          </Button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive text-sm rounded-md flex items-center gap-2">
          <AlertCircle className="h-4 w-4" /> {error}
        </div>
      )}

      {/* Jira/Linear style List */}
      <div className="bg-card border border-border/50 rounded-lg overflow-hidden shadow-sm">
        <div className="flex items-center px-4 py-2 bg-muted/30 border-b border-border/50 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          <div className="w-[100px]">ID</div>
          <div className="flex-1">Investigation Details</div>
          <div className="w-[120px]">Priority</div>
          <div className="w-[120px] text-right">Age</div>
        </div>

        {queue.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-muted-foreground bg-background">
            <CheckCircle2 className="h-10 w-10 mb-3 opacity-20 text-emerald-500" />
            <p className="text-sm font-medium">Inbox Zero</p>
            <p className="text-xs mt-1">All escalations have been resolved.</p>
          </div>
        ) : (
          <div className="divide-y divide-border/30 bg-background">
            {queue.map(claim => (
              <div key={claim.id} className="group flex flex-col hover:bg-muted/10 transition-colors">
                
                {/* Row Header */}
                <div 
                  className="flex items-center px-4 py-3 cursor-pointer"
                  onClick={() => setExpandedId(expandedId === claim.id ? null : claim.id)}
                >
                  <div className="w-[100px] flex items-center gap-1.5 text-muted-foreground font-mono text-xs">
                    <Hash className="h-3 w-3" />
                    {claim.id.toString().padStart(4, '0')}
                  </div>
                  
                  <div className="flex-1 flex flex-col pr-4">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge variant="outline" className="text-[9px] uppercase font-bold py-0 h-4 bg-background border-border/50">{claim.claim_object}</Badge>
                      <span className="font-medium text-sm text-foreground group-hover:text-primary transition-colors">
                        Review escalated {claim.claim_object} damage claim
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <div className="flex items-center gap-1 bg-muted/30 px-1.5 py-0.5 rounded">
                        <User className="h-3 w-3" /> {claim.user_id}
                      </div>
                      <span className="text-border">•</span>
                      <span className="truncate max-w-md" title={claim.escalation_reason}>
                        <span className="font-semibold text-destructive/80 mr-1">Flag:</span>
                        {claim.escalation_reason}
                      </span>
                    </div>
                  </div>

                  <div className="w-[120px]">
                    <Badge variant="outline" className={`text-[10px] py-0 h-5 border shadow-sm ${getPriorityColor(claim.confidence_score)}`}>
                      {getPriorityLabel(claim.confidence_score)}
                    </Badge>
                  </div>

                  <div className="w-[120px] flex items-center justify-end gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1"><Clock className="h-3 w-3" /> 2h</span>
                    <ChevronRight className={`h-4 w-4 transition-transform ${expandedId === claim.id ? "rotate-90" : ""}`} />
                  </div>
                </div>

                {/* Expanded Action Area */}
                {expandedId === claim.id && (
                  <div className="px-14 py-4 bg-muted/5 border-t border-border/20 flex gap-6 animate-fadeIn">
                    <div className="flex-1 space-y-3">
                      <div className="text-xs">
                        <span className="font-semibold text-muted-foreground uppercase tracking-wider block mb-1">AI Reasoning Context</span>
                        <p className="text-foreground/80 leading-relaxed bg-background p-3 rounded-md border border-border/50">
                          {claim.claim_status_justification || "No additional context provided."}
                        </p>
                      </div>
                      <div className="text-xs">
                        <span className="font-semibold text-muted-foreground uppercase tracking-wider block mb-1">Internal Notes</span>
                        <Textarea 
                          placeholder="Document your review decision..." 
                          className="h-20 text-xs resize-none bg-background border-border/50 focus-visible:ring-primary"
                          value={notes[claim.id] || ""}
                          onChange={(e) => setNotes({ ...notes, [claim.id]: e.target.value })}
                        />
                      </div>
                    </div>
                    
                    <div className="w-[200px] shrink-0 border-l border-border/50 pl-6 flex flex-col gap-2 justify-end">
                      <Button 
                        disabled={processingId === claim.id}
                        onClick={() => handleVerdict(claim.id, "approved")}
                        className="w-full gap-2 bg-emerald-500 hover:bg-emerald-600 text-emerald-950 font-semibold shadow-sm"
                      >
                        {processingId === claim.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                        Approve Claim
                      </Button>
                      <Button 
                        disabled={processingId === claim.id}
                        onClick={() => handleVerdict(claim.id, "rejected")}
                        variant="outline"
                        className="w-full gap-2 border-destructive/30 text-destructive hover:bg-destructive/10"
                      >
                        {processingId === claim.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <XCircle className="h-4 w-4" />}
                        Reject Claim
                      </Button>
                    </div>
                  </div>
                )}
                
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

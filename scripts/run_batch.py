import os
import sys
import csv
import traceback

# Add project root to python path to import app modules correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.config import settings
from backend.app.db.session import init_db, SessionLocal
from backend.app.db.models import Claim, AuditLog
from backend.app.agents.orchestrator import run_claims_orchestrator

def run_batch_processing():
    print("--- AURELIX Batch Processing starting ---")
    
    # 1. Initialize database tables
    print("Initializing database tables...")
    init_db()
    
    # Index historical claims for similarity search RAG
    from backend.app.services.vector_store import index_historical_claims
    index_historical_claims("claims/sample_claims.csv")
    
    # 2. Open input CSV
    claims_csv_path = settings.CLAIMS_CSV
    output_csv_path = settings.OUTPUT_CSV
    
    if not os.path.exists(claims_csv_path):
        print(f"Error: Input claims file '{claims_csv_path}' not found.")
        sys.exit(1)
        
    print(f"Reading claims from: {claims_csv_path}")
    claims_to_process = []
    with open(claims_csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            claims_to_process.append(row)
            
    print(f"Found {len(claims_to_process)} claims to process.")
    
    processed_results = []
    db = SessionLocal()
    
    try:
        for idx, raw_claim in enumerate(claims_to_process):
            user_id = raw_claim.get("user_id", "")
            image_paths = raw_claim.get("image_paths", "")
            user_claim = raw_claim.get("user_claim", "")
            claim_object = raw_claim.get("claim_object", "")
            
            print(f"\n[{idx+1}/{len(claims_to_process)}] Processing claim for user: {user_id} ({claim_object})")
            
            # Run LangGraph Orchestrator
            try:
                state_res = run_claims_orchestrator({
                    "user_id": user_id,
                    "image_paths": image_paths,
                    "user_claim": user_claim,
                    "claim_object": claim_object
                })
            except Exception as e:
                print(f"Error executing orchestrator: {e}")
                traceback.print_exc()
                continue
                
            # Extract final metrics
            decision = state_res["decision"]
            vision = state_res["vision"]
            quality = state_res["quality"]
            compliance = state_res["compliance"]
            fraud = state_res["fraud"]
            user_risk = state_res["user_risk"]
            escalation = state_res["escalation"]
            
            # Map values to Output CSV formats (need true/false as lowercase strings)
            ev_met_str = "true" if compliance["evidence_standard_met"] else "false"
            val_img_str = "true" if quality["image_valid"] else "false"
            
            # Format lists as semicolon-separated
            q_flags = quality["quality_flags"]
            risk_flags = user_risk["risk_flags"]
            
            # If manual review escalates, we might add manual_review_required flag to risk flags
            all_risk_flags = list(set(q_flags + risk_flags + (["manual_review_required"] if escalation["manual_review_required"] else [])))
            if "none" in all_risk_flags and len(all_risk_flags) > 1:
                all_risk_flags.remove("none")
            risk_flags_str = ";".join(all_risk_flags) if all_risk_flags else "none"
            
            # Format supporting image ids
            sup_imgs = vision["supporting_image_ids"]
            sup_imgs_str = ";".join(sup_imgs) if sup_imgs else "none"
            
            # Store in result dictionary for CSV
            output_row = {
                "user_id": user_id,
                "image_paths": image_paths,
                "user_claim": user_claim,
                "claim_object": claim_object,
                "evidence_standard_met": ev_met_str,
                "evidence_standard_met_reason": compliance["reason"],
                "risk_flags": risk_flags_str,
                "issue_type": vision["issue_type"],
                "object_part": vision["object_part"],
                "claim_status": decision["claim_status"],
                "claim_status_justification": decision["justification"],
                "supporting_image_ids": sup_imgs_str,
                "valid_image": val_img_str,
                "severity": vision["severity"]
            }
            
            processed_results.append(output_row)
            
            # Store in DB
            claim_db = Claim(
                user_id=user_id,
                image_paths=image_paths,
                user_claim=user_claim,
                claim_object=claim_object,
                evidence_standard_met=compliance["evidence_standard_met"],
                evidence_standard_met_reason=compliance["reason"],
                risk_flags=risk_flags_str,
                issue_type=vision["issue_type"],
                object_part=vision["object_part"],
                claim_status=decision["claim_status"],
                claim_status_justification=decision["justification"],
                supporting_image_ids=sup_imgs_str,
                valid_image=quality["image_valid"],
                severity=vision["severity"],
                confidence_score=state_res["confidence"]["confidence_score"],
                fraud_score=fraud["fraud_score"],
                user_risk_score=user_risk["user_risk_score"],
                escalation_reason=escalation["escalation_reason"] if escalation["manual_review_required"] else None
            )
            
            db.add(claim_db)
            db.flush() # get claim ID for audit logs
            
            # Add audit logs
            for log in state_res["audit_logs"]:
                audit_db = AuditLog(
                    claim_id=claim_db.id,
                    agent_name=log["agent_name"],
                    inputs=log.get("inputs"),
                    outputs=log.get("outputs"),
                    reasoning=log.get("reasoning")
                )
                db.add(audit_db)
                
        db.commit()
        print("\nAll claims written and committed to database successfully.")
        
    except Exception as e:
        db.rollback()
        print(f"Transaction failed, database rolled back: {e}")
        traceback.print_exc()
    finally:
        db.close()
        
    # 3. Write output CSV
    headers = [
        "user_id", "image_paths", "user_claim", "claim_object", 
        "evidence_standard_met", "evidence_standard_met_reason", 
        "risk_flags", "issue_type", "object_part", "claim_status", 
        "claim_status_justification", "supporting_image_ids", 
        "valid_image", "severity"
    ]
    
    print(f"Writing processed claims results to: {output_csv_path}")
    with open(output_csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for res_row in processed_results:
            writer.writerow(res_row)
            
    print(f"Successfully processed and generated output.csv with {len(processed_results)} rows.")

if __name__ == "__main__":
    run_batch_processing()

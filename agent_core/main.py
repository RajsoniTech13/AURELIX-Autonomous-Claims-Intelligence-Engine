import os
import sys
import csv
import traceback
from dotenv import load_dotenv

# Load env variables from .env if present
load_dotenv()

# Ensure agent-core directory is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent_core.orchestrator.graph import process_claim
from agent_core.services.vector_store import index_historical_claims
from agent_core.evaluation.evaluate import evaluate_predictions

def main():
    print("=== AURELIX agent-core CLI Starting ===")
    
    # 1. Resolve file paths
    base_dir = os.path.dirname(os.path.abspath(__file__))
    claims_csv = os.path.join(base_dir, "data", "claims.csv")
    user_history_csv = os.path.join(base_dir, "data", "user_history.csv")
    evidence_csv = os.path.join(base_dir, "data", "evidence_requirements.csv")
    sample_claims_csv = os.path.join(base_dir, "data", "sample_claims.csv")
    output_csv = os.path.join(base_dir, "output", "output.csv")
    report_md = os.path.join(base_dir, "output", "evaluation_report.md")
    
    # Verify input exists
    for fpath in [claims_csv, user_history_csv, evidence_csv, sample_claims_csv]:
        if not os.path.exists(fpath):
            print(f"Error: Required file not found: {fpath}")
            sys.exit(1)
            
    # 2. Build lookup maps for decoupling CSV logic from agents
    print("Loading historical data tables...")
    user_history_lookup = {}
    with open(user_history_csv, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_history_lookup[row["user_id"]] = row
            
    evidence_rules_lookup = {}
    with open(evidence_csv, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            evidence_rules_lookup[row["claim_object"].lower()] = row
            
    # 3. Index sample claims into Vector store for similarity searches
    index_historical_claims(sample_claims_csv)
    
    # 4. Open and process claims
    print(f"Reading claims from {claims_csv}...")
    claims_to_process = []
    with open(claims_csv, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            claims_to_process.append(row)
            
    print(f"Processing {len(claims_to_process)} claims...")
    processed_results = []
    
    for idx, raw_claim in enumerate(claims_to_process):
        user_id = raw_claim.get("user_id", "")
        image_paths = raw_claim.get("image_paths", "")
        user_claim = raw_claim.get("user_claim", "")
        claim_object = raw_claim.get("claim_object", "")
        
        print(f"[{idx+1}/{len(claims_to_process)}] Processing claim for {user_id} ({claim_object})...")
        
        # Look up records to pass to agents
        u_history = user_history_lookup.get(user_id)
        e_rules = evidence_rules_lookup.get(claim_object.lower())
        
        try:
            state_res = process_claim(
                user_id=user_id,
                image_paths=image_paths,
                user_claim=user_claim,
                claim_object=claim_object,
                user_history=u_history,
                evidence_rules=e_rules
            )
        except Exception as e:
            print(f"Error processing claim {user_id}: {e}")
            traceback.print_exc()
            continue
            
        # Map state back to output CSV format
        decision = state_res["decision"]
        vision = state_res["vision"]
        quality = state_res["quality"]
        compliance = state_res["compliance"]
        fraud = state_res["fraud"]
        user_risk = state_res["user_risk"]
        escalation = state_res["escalation"]
        
        ev_met_str = "true" if compliance["evidence_standard_met"] else "false"
        val_img_str = "true" if quality["image_valid"] else "false"
        
        # Combine risk flags exactly like the original runner
        q_flags = quality["quality_flags"]
        risk_flags = user_risk["risk_flags"]
        all_risk_flags = list(set(q_flags + risk_flags + (["manual_review_required"] if escalation["manual_review_required"] else [])))
        if "none" in all_risk_flags and len(all_risk_flags) > 1:
            all_risk_flags.remove("none")
        risk_flags_str = ";".join(all_risk_flags) if all_risk_flags else "none"
        
        sup_imgs = vision["supporting_image_ids"]
        sup_imgs_str = ";".join(sup_imgs) if sup_imgs else "none"
        
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

    # 5. Write to output CSV
    headers = [
        "user_id", "image_paths", "user_claim", "claim_object", 
        "evidence_standard_met", "evidence_standard_met_reason", 
        "risk_flags", "issue_type", "object_part", "claim_status", 
        "claim_status_justification", "supporting_image_ids", 
        "valid_image", "severity"
    ]
    
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    print(f"Saving outputs to {output_csv}...")
    with open(output_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in processed_results:
            writer.writerow(row)
            
    print("Running in-memory validation on sample_claims.csv for accuracy report...")
    sample_to_process = []
    with open(sample_claims_csv, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sample_to_process.append(row)
            
    validation_results = []
    for idx, raw_claim in enumerate(sample_to_process):
        user_id = raw_claim.get("user_id", "")
        image_paths = raw_claim.get("image_paths", "")
        user_claim = raw_claim.get("user_claim", "")
        claim_object = raw_claim.get("claim_object", "")
        
        # Look up records
        u_history = user_history_lookup.get(user_id)
        e_rules = evidence_rules_lookup.get(claim_object.lower())
        
        try:
            state_res = process_claim(
                user_id=user_id,
                image_paths=image_paths,
                user_claim=user_claim,
                claim_object=claim_object,
                user_history=u_history,
                evidence_rules=e_rules
            )
        except Exception as e:
            print(f"Error processing validation claim {user_id}: {e}")
            continue
            
        decision = state_res["decision"]
        vision = state_res["vision"]
        quality = state_res["quality"]
        compliance = state_res["compliance"]
        fraud = state_res["fraud"]
        user_risk = state_res["user_risk"]
        escalation = state_res["escalation"]
        
        ev_met_str = "true" if compliance["evidence_standard_met"] else "false"
        val_img_str = "true" if quality["image_valid"] else "false"
        
        q_flags = quality["quality_flags"]
        risk_flags = user_risk["risk_flags"]
        all_risk_flags = list(set(q_flags + risk_flags + (["manual_review_required"] if escalation["manual_review_required"] else [])))
        if "none" in all_risk_flags and len(all_risk_flags) > 1:
            all_risk_flags.remove("none")
        risk_flags_str = ";".join(all_risk_flags) if all_risk_flags else "none"
        
        sup_imgs = vision["supporting_image_ids"]
        sup_imgs_str = ";".join(sup_imgs) if sup_imgs else "none"
        
        val_row = {
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
        validation_results.append(val_row)
        
    validation_csv = os.path.join(base_dir, "output", "validation_output.csv")
    with open(validation_csv, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in validation_results:
            writer.writerow(row)
            
    print("Starting system evaluation...")
    evaluate_predictions(
        sample_path=sample_claims_csv,
        output_path=validation_csv,
        report_path=report_md
    )
    print("=== AURELIX CLI Processing Completed ===")

if __name__ == "__main__":
    main()

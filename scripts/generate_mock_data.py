import csv
import os

def generate_user_history():
    users = set()
    # Read users from claims.csv
    claims_path = "claims/claims.csv"
    if os.path.exists(claims_path):
        with open(claims_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("user_id"):
                    users.add(row["user_id"])
    
    # Read users from sample_claims.csv as well
    sample_path = "claims/sample_claims.csv"
    if os.path.exists(sample_path):
        with open(sample_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("user_id"):
                    users.add(row["user_id"])
                    
    # Generate some user history data
    user_history_file = "claims/user_history.csv"
    
    # Let's create a dictionary of some specific known users to align with sample_claims.csv
    # e.g. user_005 has "claim_mismatch;user_history_risk;manual_review_required"
    # user_008 has "possible_manipulation;user_history_risk;manual_review_required"
    # user_020 has "cropped_or_obstructed;damage_not_visible;user_history_risk;manual_review_required"
    # user_031 has "user_history_risk;manual_review_required"
    # user_033 has "claim_mismatch;user_history_risk;manual_review_required"
    # user_034 has "damage_not_visible;text_instruction_present;user_history_risk;manual_review_required"
    
    special_users = {
        "user_005": {"claim_count": 8, "rejected_claims": 4, "manual_review_history": 3, "history_flags": "high_rejection_rate;suspicious_claims"},
        "user_008": {"claim_count": 5, "rejected_claims": 2, "manual_review_history": 2, "history_flags": "prior_suspicious_evidence"},
        "user_020": {"claim_count": 6, "rejected_claims": 3, "manual_review_history": 4, "history_flags": "blurry_uploads_frequent"},
        "user_031": {"claim_count": 4, "rejected_claims": 1, "manual_review_history": 2, "history_flags": "frequent_claims"},
        "user_033": {"claim_count": 9, "rejected_claims": 5, "manual_review_history": 3, "history_flags": "severity_exaggeration;high_rejection_rate"},
        "user_034": {"claim_count": 7, "rejected_claims": 3, "manual_review_history": 3, "history_flags": "prior_text_in_images"},
        "user_040": {"claim_count": 12, "rejected_claims": 6, "manual_review_history": 5, "history_flags": "harassment_threats;high_rejection_rate"},
        "user_036": {"claim_count": 3, "rejected_claims": 1, "manual_review_history": 1, "history_flags": "pushy_behavior"},
    }

    with open(user_history_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "claim_count", "rejected_claims", "manual_review_history", "history_flags"])
        
        # Ensure all users are represented
        all_users = sorted(list(users))
        if not all_users:
            # Fallback if no claims file read
            all_users = [f"user_{i:03d}" for i in range(1, 100)]
            
        for u in all_users:
            if u in special_users:
                writer.writerow([
                    u,
                    special_users[u]["claim_count"],
                    special_users[u]["rejected_claims"],
                    special_users[u]["manual_review_history"],
                    special_users[u]["history_flags"]
                ])
            else:
                # Normal user
                # We can generate mild histories
                import random
                random.seed(hash(u))
                c_count = random.randint(1, 3)
                r_claims = random.randint(0, 1) if c_count > 1 else 0
                m_review = random.randint(0, 1)
                writer.writerow([u, c_count, r_claims, m_review, "none"])
    print(f"Generated {user_history_file}")

def generate_evidence_requirements():
    evidence_file = "claims/evidence_requirements.csv"
    with open(evidence_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["claim_object", "required_image_count", "required_visibility", "required_viewing_angle", "required_evidence_type"])
        writer.writerow(["car", "2", "front_bumper;rear_bumper;windshield;side_mirror;door;hood", "full_context;close_up", "photo"])
        writer.writerow(["laptop", "1", "screen;keyboard;hinge;trackpad;body;corner;lid", "front;close_up;side", "photo"])
        writer.writerow(["package", "1", "package_corner;seal;box;package_side;contents;label", "any", "photo"])
    print(f"Generated {evidence_file}")

if __name__ == "__main__":
    generate_user_history()
    generate_evidence_requirements()

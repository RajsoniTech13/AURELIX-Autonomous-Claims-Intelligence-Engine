import os
import sys
from PIL import Image

# Ensure agent-core directory is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "agent_core")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from agent_core.orchestrator.graph import process_claim

def run_test_case(name, image_filename, user_claim, claim_object, expected_status=None, expected_compliance=None):
    print(f"\n--- Testing {name} ---")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(base_dir, "test_images", image_filename)
    
    # Load PIL image
    images = []
    if os.path.exists(image_path):
        try:
            images.append(Image.open(image_path))
            print(f"Loaded image: {image_path}")
        except Exception as e:
            print(f"Error loading image: {e}")
            
    # Mock user history and evidence rules
    user_history = {
        "user_id": "test_user",
        "claims_submitted": "1",
        "claims_rejected": "0",
        "user_risk_score": "10",
        "risk_flags": "none"
    }
    evidence_rules = {
        "claim_object": claim_object,
        "required_image_count": "1",
        "required_visibility": "front_bumper;rear_bumper;windshield;side_mirror;door;hood;screen;keyboard;hinge;trackpad;body;corner;lid;package_corner;seal;box;package_side;contents;label"
    }
    
    # Run claim graph
    res = process_claim(
        user_id="test_user",
        image_paths=image_filename,
        user_claim=user_claim,
        claim_object=claim_object,
        user_history=user_history,
        evidence_rules=evidence_rules,
        images=images
    )
    
    status = res["decision"]["claim_status"]
    compliance = res["compliance"]["evidence_standard_met"]
    quality_flags = res["quality"]["quality_flags"]
    
    print(f"Decision Status: {status}")
    print(f"Evidence Standard Met: {compliance}")
    print(f"Quality Flags: {quality_flags}")
    print(f"Justification: {res['decision']['justification']}")
    
    if expected_status is not None:
        assert status == expected_status, f"Expected status {expected_status}, but got {status}"
    if expected_compliance is not None:
        assert compliance == expected_compliance, f"Expected compliance {expected_compliance}, but got {compliance}"
        
    print(f"✓ {name} Passed!")

def main():
    print("=== Starting Standalone Submission Verdict Tests ===")
    
    # TEST 1: Car damage image -> supported
    run_test_case(
        name="TEST 1: Car Damage Image",
        image_filename="car_damage.jpg",
        user_claim="I found a dent on my front bumper after parking outside.",
        claim_object="car",
        expected_status="supported",
        expected_compliance=True
    )
    
    # TEST 2: Cat image -> contradicted
    run_test_case(
        name="TEST 2: Cat Image (Wrong Object)",
        image_filename="cat.jpg",
        user_claim="I have deep dent on my front bumper.",
        claim_object="car",
        expected_status="contradicted",
        expected_compliance=True
    )
    
    # TEST 3: Blank image -> not_enough_information
    run_test_case(
        name="TEST 3: Blank Image (Invalid)",
        image_filename="blank.jpg",
        user_claim="My laptop has screen crack.",
        claim_object="laptop",
        expected_status="not_enough_information",
        expected_compliance=False
    )
    
    # TEST 4: Blurred image -> evidence_standard_met=false
    run_test_case(
        name="TEST 4: Blurred Image",
        image_filename="blurred.jpg",
        user_claim="My delivery package has crushed corner.",
        claim_object="package",
        expected_status="not_enough_information",
        expected_compliance=False
    )
    
    print("\n=== All Verdict Tests Passed Successfully! ===")

if __name__ == "__main__":
    main()

# ClaimGuard AI

## Multi-Agent Damage Claim Verification Platform

### Objective

Build an enterprise-grade AI-powered claims verification platform that evaluates damage claims using:

* Images (Primary Source of Truth)
* Claim Conversation
* User History
* Evidence Requirements

The system should determine whether a claim is:

* Supported
* Contradicted
* Not Enough Information

while providing explainable reasoning, confidence scores, fraud signals, severity assessment, and human-review escalation.

---

# Core Principle

Images are the primary source of truth.

User history may contribute risk context but must never override clear visual evidence.

All decisions must be explainable and grounded in image observations.

---

# Target Product Vision

This should feel like a production-ready InsurTech / LogisticsTech platform that could be adopted by:

* Insurance Companies
* E-commerce Companies
* Laptop Warranty Providers
* Logistics Companies
* Claim Processing Teams

The goal is NOT to build a CSV generator.

The goal is to build a realistic AI Claims Review System.

---

# Tech Stack

## Frontend

* Next.js 15
* TypeScript
* Tailwind CSS
* Shadcn UI

## Backend

* FastAPI
* Python

## AI Orchestration

* LangGraph

## Database

* PostgreSQL (Neon)

## Cache

* Redis (Optional)

## Deployment

Frontend:

* Vercel

Backend:

* Render

Database:

* Neon PostgreSQL

---

# System Architecture

User
↓
Claim Submission
↓
ClaimGuard AI Orchestrator (LangGraph)

├── Claim Understanding Agent
├── Vision Analysis Agent
├── Image Quality Agent
├── Evidence Compliance Agent
├── Fraud Detection Agent
├── User Risk Agent
├── Confidence Agent
├── Decision Agent
└── Human Review Agent

↓

Final Decision Engine

↓

Dashboard + CSV Output + Audit Logs

---

# AI Agent Workflow

## Agent 1: Claim Understanding Agent

### Responsibility

Extract structured information from user conversation.

### Input

User Claim Conversation

### Output

{
object: car/laptop/package,
claimed_issue: scratch/crack/etc,
claimed_part: screen/door/etc,
summary: ...
}

### Examples

"My laptop screen cracked during delivery"

↓

{
object: laptop,
issue: crack,
part: screen
}

---

## Agent 2: Vision Analysis Agent

### Responsibility

Analyze all uploaded images.

### Detect

* Visible Damage
* Issue Type
* Object Part
* Severity
* Supporting Images

### Output

{
issue_type,
object_part,
severity,
supporting_images
}

---

## Agent 3: Image Quality Agent

### Responsibility

Verify image usability.

### Detect

* blurry_image
* cropped_or_obstructed
* low_light_or_glare
* wrong_angle
* wrong_object
* wrong_object_part

### Output

{
image_valid,
quality_flags
}

This agent should execute before decision making.

---

## Agent 4: Evidence Compliance Agent

### Responsibility

Read evidence_requirements.csv dynamically.

### Checks

* Required image count
* Required object visibility
* Required viewing angle
* Required evidence type

### Output

{
evidence_standard_met,
reason
}

Do NOT hardcode evidence rules.

Always retrieve them dynamically.

---

## Agent 5: Fraud Detection Agent

### Responsibility

Detect suspicious claims.

### Signals

* Claim mismatch
* Wrong object
* Wrong object part
* Damage not visible
* Possible manipulation
* Non-original image
* Conflicting evidence

### Output

{
fraud_flags,
fraud_score
}

Fraud score range:

0-100

---

## Agent 6: User Risk Agent

### Responsibility

Analyze user_history.csv

### Inputs

* claim count
* rejected claims
* manual review history
* history flags

### Output

{
user_risk_score,
user_history_risk
}

Important:

User history must NEVER override visual evidence.

It only contributes risk context.

---

## Agent 7: Confidence Agent

### Responsibility

Calculate confidence.

### Inputs

* Vision confidence
* Evidence quality
* Fraud signals
* History signals

### Output

{
confidence_score
}

Range:

0-100

Rules:

90+ → High Confidence

70-89 → Moderate Confidence

Below 70 → Human Review Recommended

---

## Agent 8: Decision Agent

### Responsibility

Generate final verdict.

Allowed values:

* supported
* contradicted
* not_enough_information

### Output

{
claim_status,
justification
}

---

## Agent 9: Human Review Agent

### Responsibility

Escalate uncertain claims.

Trigger if:

* confidence < 70
* conflicting evidence
* manipulation suspected
* severe fraud indicators

Output:

manual_review_required

---

# Required Outputs

Generate:

output.csv

Columns:

* user_id
* image_paths
* user_claim
* claim_object
* evidence_standard_met
* evidence_standard_met_reason
* risk_flags
* issue_type
* object_part
* claim_status
* claim_status_justification
* supporting_image_ids
* valid_image
* severity

---

# Winning Features

## Feature 1

Explainable AI

Every decision must include:

* What image was used
* What damage was detected
* Why the decision was made

Example:

"Image img_2 clearly shows a crack on the laptop screen matching the user's claim."

---

## Feature 2

Confidence Score

Display:

91%

instead of just:

Supported

---

## Feature 3

Fraud Score

Display:

Fraud Score: 23/100

or

Fraud Score: 82/100

---

## Feature 4

Manual Review Queue

Separate dashboard page:

Claims requiring human intervention.

---

## Feature 5

Visual Evidence Viewer

Show:

* Uploaded Images
* Highlighted Supporting Images
* Final Decision

---

## Feature 6

Agent Execution Timeline

Display:

✓ Claim Parsed

✓ Images Analyzed

✓ Evidence Checked

✓ Fraud Checked

✓ Decision Generated

This demonstrates agentic behavior.

---

## Feature 7

Audit Logs

Store:

* Timestamp
* Agent Outputs
* Decision
* Confidence
* Risk Flags

---

# UI Pages

## Dashboard

Metrics:

* Total Claims
* Supported
* Contradicted
* Manual Review
* Average Confidence

---

## Claim Review Page

Display:

* Images
* Conversation
* Agent Outputs
* Confidence
* Fraud Score
* Final Decision

---

## Manual Review Queue

Display:

Claims requiring review.

---

## Analytics Page

Charts:

* Claim Volume
* Fraud Distribution
* Decision Distribution
* Confidence Distribution

---

# Evaluation Folder

Create:

evaluation/

Files:

evaluation_report.md

Include:

## Metrics

* Sample accuracy
* Precision
* Recall
* F1

## Operational Analysis

* Total model calls
* Image count
* Approximate token usage
* Approximate cost
* Runtime
* Rate limit strategy
* Caching strategy
* Retry strategy

---

# Submission Deliverables

Submit:

1. code.zip

Contains:

* Source code
* README
* Prompts
* Configurations
* evaluation/

2. output.csv

Predictions for claims.csv

3. chat_transcript

Development conversation transcript

---

# AI Judge Interview Talking Points

Use this explanation:

"The platform is designed around the principle that images are the primary source of truth. User history contributes risk context but never overrides visual evidence. Evidence requirements are retrieved dynamically from policy rules. Multi-agent reasoning is used to separate claim understanding, vision analysis, fraud detection, risk assessment, and final decision making. Low-confidence cases are escalated through a human-in-the-loop workflow to ensure reliability and auditability."

---

# Final Goal

Build a production-style AI claims verification platform that demonstrates:

* Multi-Agent Reasoning
* Explainability
* Fraud Detection
* Confidence Scoring
* Human Review Workflow
* Policy-Based Evidence Validation
* Enterprise Architecture

The project should feel deployable in a real insurance or logistics environment, not just a hackathon demo.

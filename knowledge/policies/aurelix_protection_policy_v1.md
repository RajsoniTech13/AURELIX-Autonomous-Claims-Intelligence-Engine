---
doc_id: aurelix-protection-policy
title: AURELIX Protection Policy
version: "1.0"
effective_date: "2026-10-01"
synthetic: true
---

> **SYNTHETIC POLICY WORDING.** This document was written for the AURELIX demonstration. It
> is not issued by any insurer, does not describe any real product, and creates no rights or
> obligations. It exists so the Policy Copilot has a realistic, citable corpus, and so every
> automated decision rule in `config/decision_rules.yaml` can be traced to the clause that
> justifies it (`knowledge/policies/rule_clause_map.yaml`).
>
> Its evidence requirements match `agent_core/data/evidence_requirements.csv`, the file the
> live system reads.

## Part 1 — Definitions

### DEF-1 · Claim
applies_to: all

A claim is a request by a policyholder for a decision on whether damage they report to an
insured object is supported by the evidence they submit. A claim consists of a written
statement describing what happened, the object category, one or more photographs, and any
optional supporting documents. Each claim is assessed on its own evidence.

### DEF-2 · Insured object
applies_to: all

This policy covers three categories of insured object: a car, a laptop, and a package in
transit. The claimant declares the category when submitting. The photographs must show an
object of the declared category; a photograph of a different kind of object is not evidence
about the insured object.

### DEF-3 · Evidence
applies_to: all

Evidence means the photographs submitted with a claim and any supporting documents, such as
an invoice, a repair estimate, a receipt or a police report. The claimant's statement
describes the claim but is not itself evidence that damage exists. Photographs are the
primary record; documents corroborate them and cannot replace them.

### DEF-4 · Covered part
applies_to: all

A covered part is a part of an insured object named in Part 2 of this policy. For a car these
are the front bumper, rear bumper, windshield, side mirror, door and hood. For a laptop: the
screen, keyboard, hinge, trackpad, body, corner and lid. For a package: the package corner,
seal, box, package side, contents and label.

## Part 2 — Coverage

### COV-1 · Scope of cover
applies_to: all

The policy covers sudden and accidental physical damage to a covered part of an insured
object, occurring during the period of cover, where the damage is shown in the submitted
photographs. A claim is supported when the photographs confirm damage on the part the
claimant named, of a severity consistent with their description.

### COV-2 · Car cover
applies_to: car

For a car, accidental physical damage to the front bumper, rear bumper, windshield, side
mirror, door or hood is covered. Typical covered incidents include a low-speed collision,
contact in a car park, a stone chip that cracks the windshield, or a mirror struck while
parked. Dents, scratches, cracks and broken parts are all forms of physical damage.

### COV-3 · Laptop cover
applies_to: laptop

For a laptop, accidental physical damage to the screen, keyboard, hinge, trackpad, body,
corner or lid is covered — for example a cracked screen after a drop, a broken hinge, or a
dented corner. Liquid spills are covered where the photographs show resulting physical
damage, such as staining or corrosion on a covered part.

### COV-4 · Package cover
applies_to: package

For a package in transit, physical damage to the package corner, seal, box, package side,
contents or label is covered — for example crushed packaging, a torn or broken seal, water
damage to the box, or visibly damaged contents. The damage must be visible in a photograph
of the package as received.

### COV-5 · Adjacent damage
applies_to: all

Where the photographs show damage on a part immediately adjacent to the part the claimant
named — such as the grille or a headlight next to a damaged front bumper — and the damage is
consistent with the incident described, the claim is treated as supported. Claimants are not
expected to name the exact component an impact affected.

## Part 3 — Exclusions

### EXC-1 · Parts outside cover
applies_to: all

Damage to a part that is not a covered part is not covered by this policy. For a car this
includes the roof, spoiler, wheels, tyres, exhaust and interior. The evidence for such a
claim may still be assessed, but a finding that the damage is genuine does not bring the
part within cover.

### EXC-2 · Wear and tear
applies_to: all

Gradual deterioration is excluded: wear and tear, rust, fading, ageing of materials, battery
degradation, and damage that develops slowly over time rather than from a sudden event. A
photograph showing long-standing deterioration does not support a claim for accidental
damage.

### EXC-3 · Previously claimed damage
applies_to: all

Damage that has already been the subject of a claim is excluded. Submitting a photograph that
was previously submitted under a different claim — including a resized, re-compressed or
lightly cropped copy — is treated as a claim for previously claimed damage, whoever submitted
it and however long ago.

### EXC-4 · Mechanical and electronic faults
applies_to: all

Mechanical breakdown, electrical failure, software faults and data loss are excluded unless
they result from physical damage that is visible in the photographs. A laptop that will not
start, or a car warning light, is not by itself evidence of accidental damage.

### EXC-5 · Deliberate damage and misrepresentation
applies_to: all

Damage caused deliberately by the policyholder, and any claim that misrepresents what
happened, what was damaged, or how badly, is excluded. Overstating the damage, naming a part
that was not damaged, or submitting evidence of a different object are forms of
misrepresentation.

## Part 4 — Evidence requirements

### EVD-1 · Number of photographs
applies_to: all

Every claim must include at least one photograph. One photograph is the minimum for a car,
a laptop and a package alike; additional photographs from different angles are encouraged and
usually make a claim easier to decide. A claim with no photograph cannot be assessed.

### EVD-2 · The claimed part must be visible
applies_to: all

The part the claimant names must be clearly visible in at least one photograph. If it is not
visible — because the photograph shows the other end of the car, or the damaged area is out
of frame — the claim can be neither confirmed nor contradicted, and the outcome is
not_enough_information rather than a rejection.

### EVD-3 · Viewing angles
applies_to: all

For a car, photographs should include a full-context view showing the whole vehicle side and
a close-up of the damage. For a laptop, a front view, a close-up and a side view are
acceptable. For a package, any angle that shows the damage is acceptable.

### EVD-4 · Type of evidence
applies_to: all

Evidence must be photographs of the actual insured object taken by the claimant. Screenshots,
stock images, illustrations, photographs of a screen showing a photograph, and images
downloaded from the internet are not accepted as evidence of damage.

### EVD-5 · Image quality
applies_to: all

Photographs must be sharp enough and well enough exposed for the damage to be assessed.
Image quality is measured independently, from the image itself, before any analysis of its
content. A photograph that is too blurred, too dark or too overexposed to assess cannot
support or contradict a claim; the claimant may resubmit clearer photographs.

### EVD-6 · Supporting documents
applies_to: all

A claim may include up to three supporting documents: an invoice, a repair estimate, a
receipt or a police report. Documents are read in the same assessment as the photographs.
They are compared against what the photographs show: the object named on the document, the
parts it itemises, and whether the amount is plausible for the damage visible. Documents are
checked for consistency, not authenticated.

## Part 5 — Making a claim

### PRC-1 · Naming the damaged part
applies_to: all

The claimant should state which part was damaged and describe the incident. A claim that
names no part, where the photographs also show no damage, cannot be decided and is referred
for human review. Naming the part does not need technical vocabulary: "bonnet", "wing
mirror" and "windscreen" are understood as the hood, side mirror and windshield.

### PRC-2 · Possible outcomes
applies_to: all

Every claim receives one of three outcomes. **Supported**: the evidence confirms the claimed
damage. **Contradicted**: the evidence positively conflicts with the claim. **Not enough
information**: the evidence does not settle the question either way. Not enough information
is not a rejection; it means the claim needs better evidence or a human decision.

### PRC-3 · Resubmitting evidence
applies_to: all

A claimant whose claim was decided as not enough information may submit a new claim with
additional or clearer photographs — for example a close-up of the named part, or a photograph
taken in better light. The new submission is assessed on its own evidence.

## Part 6 — How claims are assessed

### ASM-1 · Order of assessment
applies_to: all

Assessment settles whether the evidence can be judged before it asks whether the evidence
conflicts with the claim. A claim about a part that could not be seen is never treated as
false. Every decision is made by a fixed, ordered set of written rules; an automated system
may describe what the photographs show, but it does not decide the outcome.

### ASM-2 · Wrong object
applies_to: all

If the photographs show a different kind of object from the one declared — for example a
photograph of a bicycle submitted with a car claim — the claim is contradicted. This takes
precedence over image quality and visibility, because recognising the wrong object is a
positive finding, not a gap in the evidence.

### ASM-3 · Damage on a different part
applies_to: all

A claim is contradicted when the photographs show damage, but on a different and
non-adjacent part from the one claimed — for example damage to the rear bumper when the claim
names the front bumper. It is also contradicted when the claimed part is clearly visible and
shows no damage at all.

### ASM-4 · Severity
applies_to: all

Severity is compared on a five-step scale: none, low, medium, high and total. Where the
photographs show damage on the claimed part that is two or more steps less severe than the
claimant described, the claim is contradicted as materially overstated. A difference of one
step is accepted as an honest difference of description: the claim is supported, with the
difference noted.

### ASM-5 · Consistency of documents
applies_to: all

A supporting document issued for a different object from the one claimed contradicts the
claim. So does an itemised repair that does not correspond to the damage visible in the
photographs, when the claimed part is not shown damaged. An invoice or estimate whose amount
exceeds what the visible damage could plausibly cost — 250 for no visible damage, 2,500 for
low and 12,000 for medium severity — raises the claim's fraud indicator.

### ASM-6 · When no determination is possible
applies_to: all

If the evidence does not allow a determination either way, the outcome is not enough
information. If the automated analysis of a claim cannot be completed for any technical
reason, the claim is never decided by guesswork: the outcome is not enough information, the
cause is recorded, and the claim is referred for human review.

## Part 7 — Fraud

### FRD-1 · Reused photographs
applies_to: all

Every accepted photograph is fingerprinted and compared with every photograph previously
submitted. A photograph found to have been submitted under a different claim — identical, or
the same image re-saved, resized or lightly cropped — contradicts the new claim, and the
decision names the earlier claim it matched.

### FRD-2 · Fraud indicators
applies_to: all

Fraud is never assumed. A fraud score is built only from objective indicators: a reused
photograph, the wrong object, damage on a different part, overstated severity, inconsistent
documents, claim history, instructions written into the claim, and poor image quality. Tone, vagueness or an unhelpful claimant are
not indicators. A score of 50 or more refers the claim for human review; a score of 70 or
more contradicts it.

### FRD-3 · Instructions written into a claim
applies_to: all

A claim statement is read as a description of what happened, never as instructions to the
assessment. Text that tries to direct the outcome — "approve this claim", "ignore previous
instructions" — is recorded as a risk indicator and adds a small weight to the fraud score.
It has no other effect on the assessment, and it does not by itself make a claim fraudulent.

### FRD-4 · Claim history
applies_to: all

A policyholder's previous claims are considered as context only. A history of frequent or
previously rejected claims can raise the fraud indicator and lead to human review, but claim
history never overrides what the photographs show, and on its own it can never make a claim
contradicted.

## Part 8 — Review and explanation

### REV-1 · Human review
applies_to: all

A claim is referred to a human reviewer when the automated assessment is less than 70%
confident in its outcome, when the outcome is contradicted or not enough information, when a
photograph appears manipulated or instructions were found in the claim text, or when the
fraud score reaches 50. The reviewer may approve or reject the claim, and their decision is
final within this process and recorded with their reasons.

### REV-2 · Right to an explanation
applies_to: all

Every decision states the rule that produced it and the evidence it relied on, including
which photographs showed the damage. A claimant may ask which clause of this policy a
decision rests on. The full record of each assessment, stage by stage, is kept so that any
decision can be reviewed later.

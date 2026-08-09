# AURELIX — Evaluation Report (synthetic benchmark)

> **SYNTHETIC DEVELOPMENT/EVALUATION DATA.** Every claim narrative is invented and
> every image is a procedurally generated illustration. These figures measure the
> pipeline against known labels; they are **not** a prediction of accuracy on real
> claim photographs, which bring lighting, occlusion, reflections and motion blur
> that this set does not contain.

- Ground truth: `/Users/raj.v.soni/GITHUB/HackerRank Hackathon/agent_core/data/synthetic/ground_truth.csv`
- Predictions: `/Users/raj.v.soni/GITHUB/HackerRank Hackathon/agent_core/output/results_detail.json`

## Headline

| metric | value |
| :--- | ---: |
| Cases scored | 44 / 44 |
| **Accuracy** | **88.6%** |
| Macro F1 | 86.0% |
| Weighted F1 | 88.5% |
| Mean confidence | 70 |
| Mean fraud score | 20 |

## Per class

| class | support | TP | FP | FN | precision | recall | F1 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| supported | 19 | 18 | 2 | 1 | 90.0% | 94.7% | 92.3% |
| contradicted | 18 | 16 | 2 | 2 | 88.9% | 88.9% | 88.9% |
| not_enough_information | 7 | 5 | 1 | 2 | 83.3% | 71.4% | 76.9% |

## Confusion matrix

Rows are ground truth, columns are predictions.

| actual \ predicted | supported | contradicted | not_enough_information |
| :--- | ---: | ---: | ---: |
| **supported** | 18 | 1 | 0 |
| **contradicted** | 1 | 16 | 1 |
| **not_enough_information** | 1 | 1 | 5 |

## By failure category

The number that matters: aggregate accuracy hides which specific failure mode is broken.

| category | correct | total | rate |
| :--- | ---: | ---: | ---: |
| adjacent_part | 3 | 3 | 100% |
| injection | 1 | 1 | 100% |
| injection_mismatch | 1 | 1 | 100% |
| match | 13 | 14 | 93% |
| no_damage | 2 | 2 | 100% |
| part_mismatch | 6 | 7 | 86% |
| part_not_visible | 3 | 3 | 100% |
| poor_image | 2 | 4 | 50% |
| severity_inflation | 4 | 5 | 80% |
| severity_overstatement | 1 | 1 | 100% |
| wrong_object | 2 | 2 | 100% |
| wrong_object_document | 1 | 1 | 100% |

## Notable failures

| claim | category | expected | got | part_match | object_match | Δsev | observed | rules |
| :--- | :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |
| SYN-014 | match | supported | contradicted | mismatch | match | None | quarter_panel | R040_part_mismatch,FRAUD:part_mismatch_with_damage_elsewhere |
| SYN-021 | part_mismatch | contradicted | not_enough_information | not_visible | match | None | rear_bumper | R020_claimed_part_not_visible |
| SYN-029 | severity_inflation | contradicted | supported | exact | match | 1 | door | R050_supported_with_overstatement |
| SYN-032 | poor_image | not_enough_information | contradicted | mismatch | match | None | windshield | R040_part_mismatch,FRAUD:poor_image_quality,FRAUD:part_mismatch_with_damage_elsewhere |
| SYN-033 | poor_image | not_enough_information | supported | exact | match | None | screen | R052_supported |


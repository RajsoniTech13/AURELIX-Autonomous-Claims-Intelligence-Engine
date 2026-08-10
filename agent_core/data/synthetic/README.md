# SYNTHETIC DEVELOPMENT / EVALUATION DATA

**These are not real insurance claims.** Every narrative is invented and every image
is a procedurally generated illustration produced by
`agent_core/tools/render_objects.py`. No real claimant, vehicle, device, parcel, or
photograph is represented.

## Files

| file | role |
|---|---|
| `claims_synthetic.csv` | **Input.** What the pipeline and the model see. |
| `ground_truth.csv` | **Labels.** Never sent to a model, ever. |
| `images/` | Rendered claim images. |

## What this set can and cannot tell you

It exercises the full pipeline against known labels: batching, claim isolation,
part normalisation, alignment, and the decision rules. It is a regression harness.

It is **not** a measurement of real-world vision accuracy. These are clean vector
illustrations. Real claim photographs bring lighting, reflections, motion blur,
occlusion, dirt, and damage that does not look like a drawn ellipse. Numbers from
this set should never be quoted as the system's accuracy on real claims.

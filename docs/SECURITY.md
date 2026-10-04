# AURELIX — Security

What AURELIX defends against, how, what it does **not** defend against, and the test that
proves each claim. Written for a reviewer who wants to check rather than trust: every
"proved by" names a test in `tests/` that fails if the defence is removed.

Scope: the deployed demo (Next.js on Vercel, FastAPI on Render free tier, SQLite), the
claim pipeline (one Gemini perception call, deterministic rules), and the Policy Copilot
(retrieval over the operator's policy + a text model behind the gateway).

---

## 1. Who can do what

Authentication is a 15-minute JWT access token plus a rotating refresh token
(`platform_backend/services/auth.py`). Authorisation is one FastAPI dependency per route
(`platform_backend/security.py`).

| resource | claimant | reviewer / admin | anonymous |
|---|---|---|---|
| submit a claim | as themselves (form `user_id` ignored) | on a policyholder's behalf | 401 |
| read a claim, its job, its explanation | their own; others are **404** | all | 401 |
| review queue, verdicts, analytics | 403 | yes | 401 |
| Policy Copilot, LLM metrics | 403 | yes | 401 |
| photographs and documents | signed URL from a claim they may read | same | 403 |
| `/health`, `/ready`, `/demo/status`, auth config | yes | yes | yes |
| legacy `POST /claims/submit` (reads server paths) | 403 | admin only | 401 |

Another claimant's claim is a 404, not a 403: a 403 would confirm the claim exists.

**Proved by** `tests/test_auth.py`: `test_every_protected_route_refuses_an_anonymous_caller`
(14 routes), `test_a_claimant_cannot_use_reviewer_tools`,
`test_another_claimants_claim_does_not_exist_for_you`,
`test_another_claimants_job_does_not_exist_for_you`,
`test_a_claimant_always_submits_as_themselves`,
`test_the_legacy_server_path_submission_is_admin_only`. Two of these were mutation-checked:
removing the ownership check, or the link-expiry check, makes them fail.

### Tokens

| | access token | refresh token |
|---|---|---|
| form | JWT, HS256, `iss=aurelix`, `typ=access` | 32 random bytes, opaque |
| lifetime | 15 min | 7 days |
| stored | browser memory only | browser `localStorage`; server keeps **SHA-256 only** |
| revocable | no (expires) | yes: rotation, sign-out, reuse detection |

- `algorithms=["HS256"]` is pinned, so an `alg: none` token is rejected —
  `test_an_unsigned_alg_none_token_is_rejected`. Forged, expired, wrong-type, wrong-issuer and
  unknown-role tokens are 401 — `test_a_bad_token_is_401`.
- Every refresh rotates the token; presenting a rotated one revokes the whole family, so a
  stolen copy dies the moment either holder uses it —
  `test_reusing_a_rotated_refresh_token_ends_the_whole_session`,
  `test_sign_out_revokes_the_refresh_token`, `test_refresh_tokens_are_stored_hashed`.
- The signing key comes from `AURELIX_JWT_SECRET` (≥ 32 chars, `test_a_short_signing_key_is_refused`).
  Unset, a random per-process key is used: tokens die at restart. There is no default key in
  the repository to forge tokens with.

### Passwords

Argon2id at the OWASP minimum, `m=19456 (19 MiB), t=2, p=1`
([Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html),
read 2026-10-04). argon2-cffi's default of 64 MiB per hash is too much per sign-in on a 512 MB
instance. Minimum length 12. Unknown usernames are verified against a dummy hash so timing does
not reveal which accounts exist, and every failure returns the same "Invalid credentials.".
Five failed sign-ins per username per 15 minutes, then 429.
— `test_passwords_are_stored_as_argon2id_never_plain`, `test_every_sign_in_failure_looks_the_same`,
`test_repeated_failed_sign_ins_are_rate_limited`, `test_seed_passwords_must_be_long`.

No account and no password is committed. Accounts come from `AURELIX_SEED_USERS` at startup.

### Demo sign-in

`POST /api/v1/auth/demo` creates a **fresh account per visitor**: two visitors trying the
claimant view never see each other's claims. Demo accounts have no password and cannot use the
password sign-in. Admin is not a demo role. 20 demo sign-ins per client address per hour.
Switch off with `AURELIX_DEMO_LOGIN=0`.
— `test_each_demo_visitor_gets_their_own_claimant`,
`test_a_demo_account_cannot_be_signed_into_with_a_password`, `test_admin_is_not_a_demo_role`,
`test_demo_sign_in_can_be_switched_off`.

### Photographs and documents

An `<img>` tag cannot send an `Authorization` header, so evidence is served by URLs signed with
HMAC-SHA256 over the file name and an expiry (15 minutes), using a key derived from — not equal
to — the token key. URLs are minted only inside a claim response, after the ownership check.
Served `Cache-Control: private` so a shared cache never hands one claimant's photo to another.
— `test_photographs_are_served_only_by_a_signed_url_from_the_claim` (no signature, forged
signature, signature for another file: all 403), `test_an_expired_photograph_link_stops_working`,
`test_photographs_are_not_cached_by_shared_caches`.

Uploads were already hardened before Phase 7: count and size caps, decompression-bomb guard,
format sniffed from the bytes not the filename or Content-Type, generated file names, and a
traversal-proof serving route — `tests/test_uploads.py`.

### Headers

Every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer` (a signed URL must not leak to another site in a Referer),
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (the API serves JSON and
images, never a page to render), HSTS, and a restrictive `Permissions-Policy`. Token responses
are `Cache-Control: no-store`. — `test_security_headers_are_on_every_response`,
`test_token_responses_are_never_cached`.

---

## 2. OWASP Top 10 for LLM Applications (2025)

The list as published at [genai.owasp.org/llm-top-10](https://genai.owasp.org/llm-top-10/),
read 2026-10-04.

### LLM01:2025 Prompt Injection

**Does.** Two model-facing inputs, both treated as data:
- *Claim text (perception).* Fenced inside a labelled per-claim block; forged block markers are
  stripped; the model reports instruction-like text as a structured field, which becomes a risk
  flag and a small fraud-score weight and **never a verdict by itself**. Isolation is verified
  after the call: a response that cites another claim's image is rejected.
- *Reviewer question (copilot).* Fenced as data with forged fence markers stripped, under a
  fixed system prompt. The defence that does not depend on the model behaving: **only clauses
  that were retrieved can be shown as citations**, and an answer with no valid citation is not
  shown at all.

**Proved by** `test_claimant_cannot_forge_a_block_boundary`,
`test_citing_an_image_the_claim_does_not_own_is_rejected`,
`test_injection_flag_does_not_by_itself_contradict`, `test_injection_demands_the_wrong_verdict`
(benchmark cases must want a *different* verdict, or resisting is indistinguishable from luck),
`test_injected_instructions_cannot_reach_the_screen` (the model is made to obey the injection
completely; the invented citation still never reaches the screen), `test_the_fence_strips_forged_delimiters`.
Live: five injection probes against Groq in `evaluation/rag/copilot_live.md` — none produced an
unretrieved citation.

**Does not.** No classifier screens inputs before they reach a model. The answer *text* of the
copilot is not checked against its citations (see LLM09). Only 2 benchmark injection cases and 5
live probes — not a red-team corpus.

### LLM02:2025 Sensitive Information Disclosure

**Does.** Claims are scoped to their owner (§1). The copilot retrieves only operator policy
clauses — never claims, never another claimant's text. Telemetry stores counts and labels only:
the `llm_calls` table has no column that could hold prompt or claim text. Photographs require a
signed, expiring URL. Logs never record tokens.

**Proved by** `test_the_copilot_only_ever_sees_policy_clauses`,
`test_the_calls_table_has_no_column_that_could_hold_claim_text`,
`test_a_record_holds_counts_and_labels_only`, the ownership tests in §1.

**Does not.** Claim photographs and text are sent to Google (Gemini) for perception and policy
questions to Groq — third-party processors under their terms. EXIF metadata is not stripped from
stored photographs. The sign-in screen warns demo visitors not to upload real documents.

### LLM03:2025 Supply Chain

**Does.** Every Python dependency added in Phase 7 is pinned to the version whose source was
read (`openai==2.43.0`, `fastembed==0.8.1`, `onnxruntime==1.30.0`, `pyjwt==2.15.1`,
`argon2-cffi==25.1.0`). The embedding model is a named public model (`BAAI/bge-small-en-v1.5`,
MIT) fetched by fastembed from its published source at build time. Optional SDKs (`anthropic`)
are not installed in the deployment at all. `pip-audit` runs in CI (Phase 7 A4).

**Does not.** No `--require-hashes` lockfile, so a compromised index could serve a different
artifact for a pinned version. Model weights are not checksum-verified beyond what the download
library does. Older dependencies are floored (`numpy>=2.0`), not pinned.

### LLM04:2025 Data and Model Poisoning

**Does.** No model is trained or fine-tuned. The only retrieval corpus the copilot reads is the
operator's policy, versioned in git, parsed strictly (a malformed clause fails the build), and
mapped to the decision rules by a test that fails on any gap. Claimant text is never indexed
into it. The duplicate-image index is never seeded with test data in a deployed build.

**Proved by** `tests/test_policy_corpus.py` (16 tests, including
`test_every_decision_rule_is_justified_by_a_clause` and
`test_every_covered_part_the_system_checks_is_named_in_the_policy`),
`test_the_deployed_build_does_not_seed_the_duplicate_detector_with_test_data`.

**Does not.** The corpus is not signed; anyone with write access to the repository can change
the policy the copilot cites.

### LLM05:2025 Improper Output Handling

**Does.** No model output is executed, rendered as HTML, or trusted unchecked. Every structured
response is constrained by the provider's schema mode *and* validated with Pydantic; a
truncated, refused, empty or schema-invalid answer is an error, never a guess. Perception values
are clamped to the frozen output vocabulary. The UI renders model text as plain text. **The
model never decides a claim**: verdicts, fraud scores and confidence are deterministic Python.

**Proved by** `test_an_unusable_answer_is_invalid_response_never_a_guess`,
`test_citations_outside_the_retrieved_set_are_stripped`, `test_no_fabrication.py` (no hardcoded
verdict can be returned when the model fails), `test_output_contract.py`.

**Does not.** Nothing further — model output has no path to code execution or markup here.

### LLM06:2025 Excessive Agency

**Does.** Neither model has tools, functions or write access. Perception returns observations;
the copilot returns text and citation ids. The claim pipeline makes exactly one model call per
claim and the rule engine decides. Reviewer actions (approve/reject) are made by a person and
recorded with the reviewer's account name.

**Proved by** `test_one_claim_is_still_one_request_and_one_record`,
`test_the_backend_service_makes_the_same_single_call`, the import-graph guardrails in
`test_backend_pipeline.py`, `test_a_verdict_records_which_reviewer_made_it`.

**Does not.** Nothing further. (A bounded, read-only Investigator Assistant is Phase B, with its
own tool allow-list, step cap and tests that claimant text cannot trigger tools.)

### LLM07:2025 System Prompt Leakage

**Does.** System prompts hold no secret, credential or private rule — they are in this public
repository. Authorisation is enforced by code, never by prompt instructions, so a leaked prompt
grants nothing. Asked to reveal its prompt, the copilot returned "not found" in the live probe.

**Does not.** Output is not filtered for prompt echoes; a model could repeat instructions in an
answer. That is acceptable only because the prompts contain nothing sensitive.

### LLM08:2025 Vector and Embedding Weaknesses

**Does.** One trusted corpus, single tenant, filtered **before** ranking (`kind: clause`) so other
documents in the collection cannot be retrieved. Saved vectors carry the identity of the model
that made them and are refused by any other model. Embeddings are computed locally — no text
leaves the server to be embedded. The copilot is reviewer-only.

**Proved by** `test_numpy_store_ranks_by_cosine_and_filters_before_ranking`,
`test_numpy_store_round_trips_and_refuses_another_vector_space`,
`test_the_copilot_only_ever_sees_policy_clauses`.

**Does not.** No multi-tenant isolation exists to test (Phase C). Embedding inversion is not a
concern for a public policy document, and is not addressed.

### LLM09:2025 Misinformation

**Does.** The copilot answers only from retrieved clauses, must cite them, refuses with zero
model calls when no clause is close enough, and suppresses any uncited answer. Measured live:
32/32 answerable questions answered with a correct citation, 8/8 unanswerable refused
(`evaluation/rag/copilot_live.md`). Claim verdicts carry the rule that produced them and an
explanation endpoint returns the policy clause behind it — deterministically.

**Does not.** The answer *text* is not verified against the cited clause (no entailment check):
a model could cite the right clause and paraphrase it wrongly. The golden set and the policy
share an author. The policy is synthetic and says so.

### LLM10:2025 Unbounded Consumption

**Does.** Layered limits, from cheapest to most expensive:
- the copilot's retrieval gate answers off-policy questions with **zero** model calls;
- one model request per claim; preflight skips the call entirely when no image is usable;
- per-account limits: 12 claim submissions/hour, 30 copilot questions/hour;
- per-visitor demo cap and reserve floor on the shared Gemini budget (`DEMO_MODE`), now
  enforced on every submission route — the async v1 route used to bypass it;
- question length ≤ 500 chars, copilot output ≤ 700 tokens, upload count and size caps;
- a persisted per-model quota ledger; a model known to be spent is skipped without a request.

**Proved by** `test_claim_submissions_are_rate_limited_per_account`,
`test_the_v1_route_can_no_longer_bypass_the_demo_cap`,
`test_a_rejected_upload_does_not_use_up_a_demo_analysis`,
`test_an_off_topic_question_is_refused_with_zero_model_calls`,
`test_empty_or_oversized_questions_are_rejected`, `test_a_claim_with_no_usable_image_costs_nothing`,
`tests/test_uploads.py` caps.

**Does not.** Limits are in-process: with several workers each enforces its own window (Phase B:
Redis token bucket). Limits key on account and client address; a determined attacker with many
addresses can create many demo accounts.

---

## 3. Known weaknesses, stated plainly

1. **Refresh tokens live in `localStorage`.** An XSS bug would expose them. Mitigations: no HTML
   rendering of user or model text, rotation with reuse detection, 7-day expiry. The stronger
   design — an httpOnly, `SameSite=Strict` cookie — needs the API on the same site as the
   frontend (`api.aurelix.space`); across Vercel and Render it would be a third-party cookie,
   which Safari blocks.
2. **Access tokens cannot be revoked early.** Sign-out and deactivation take effect within 15
   minutes, when the access token expires.
3. **The public demo is open by design.** Anyone can create a demo reviewer and approve or
   reject any claim in the demo database. That is the point of a demo, and the reason demo
   sign-in has an off switch.
4. **Storage is ephemeral on the free tier.** Accounts, refresh tokens and claims are lost on a
   redeploy; users simply sign in again.
5. **No MFA, no password reset, no account management UI.** Accounts are seeded by the operator.
6. **Without `AURELIX_JWT_SECRET`, every restart signs everyone out** — including Render's free
   instance waking from sleep.

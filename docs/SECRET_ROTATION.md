# Credential exposure and rotation

## What was exposed

`agent_core/README.md:54` contained:

```
GEMINI_API_KEY=AQ.Ab8RN...   # Or use OPENAI_API_KEY
```

Present in commits `ff084a1` and `e4ce2159`.

**Severity: low.** This was initially assessed as moderate. After rotation, the replacement
key is also 53 characters and also begins `AQ.Ab8RN` — so this is a **structural prefix shared
by all Gemini API keys of this generation**, not a fragment of the secret. Comparable to
leaking `sk-` from an OpenAI key.

**Status: rotated on 2026-08-08.** The exposed key is dead. Nothing below is urgent; steps 3
and 4 are hygiene.

What was *not* exposed: `.env` is untracked, and `.gitignore` already covers `.env`,
`.env.local`, and `.env*.local` (lines 34-38). A scan of all four commits for `AIza*`,
`sk-*`, and `AQ.Ab8RN*` patterns found no other secrets.

## Step 1 — Rotate the key (do this first, and do it yourself)

I can't do this part; it needs your Google account.

1. Go to https://aistudio.google.com/apikey
2. Delete the key beginning `AQ.Ab8RN`.
3. Create a new key.
4. Update your local `.env` (`cp .env.example .env` if you don't have one).

Rotate before purging history. Once the key is dead, the committed prefix is worthless and
the cleanup below stops being urgent.

## Step 2 — Remove the line from the working tree

Already done. `agent_core/README.md` now points at `.env.example` instead.

## Step 3 — Purge from git history (optional once rotated)

The prefix is still reachable in the two historical commits. If you want it gone:

```bash
pip install git-filter-repo
```

Then, from a fresh clone (`git filter-repo` refuses to run on a repo with existing remotes
configured unless cloned fresh):

```bash
git clone --no-local . ../aurelix-clean && cd ../aurelix-clean
```

Write the replacement rule and apply it:

```bash
printf 'GEMINI_API_KEY=AQ.Ab8RN...==>GEMINI_API_KEY=<see .env.example>\n' > /tmp/redact.txt
git filter-repo --replace-text /tmp/redact.txt
```

This rewrites every commit hash. If the repo has been pushed anywhere or shared, coordinate
before force-pushing — collaborators will need to re-clone.

**If this repo has only ever been local and unshared, rotating the key is sufficient.** The
history rewrite is cleanup, not remediation.

## Step 4 — Prevent recurrence

- `.env.example` is the only place credentials are described. It contains no values.
- `.gitignore` already blocks `.env*`.
- Consider a pre-commit secret scan (`gitleaks`, `detect-secrets`) — proposed for the
  Phase 6 CI pipeline.

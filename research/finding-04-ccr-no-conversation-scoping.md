# Finding 04 — CCR retrieval has no conversation scoping

**Status:** mechanism verified, but **SEVERITY DOWNGRADED — likely not a defect** · **Cost:** zero
**Date:** 2026-08-21 · **Version:** `headroom-ai` 0.36.2

---

## VERDICT (revised 2026-08-21, after critique)

**Downgraded. Probably by design, and of negligible practical consequence.** Kept for the record
because the mechanism is real and the reasoning is worth preserving — not as a submission candidate.

Three arguments against it, in descending force:

1. **No accidental path.** A hash from conversation Y never enters conversation X's context. The
   model only ever sees markers Headroom placed in its own conversation. Exploitation requires a
   deliberate attacker supplying a foreign hash — it cannot happen by accident.
2. **The attacker gains nothing.** The realistic vector is prompt injection (agent reads a poisoned
   file / page / MCP output). But a prompt-injected coding agent already has shell access and can
   read other projects' files directly. CCR adds no capability such an attacker lacks.
3. **Content-derived hashes make scoping counterproductive.** The key is `blake3(original)[:24]`, so
   identical content across conversations yields one shared entry — deliberate deduplication.
   Retrieving hash `H` always returns content whose hash is `H`; you cannot obtain data other than
   what the hash already denotes. This is a capability-token model (an unguessable URL), which is a
   legitimate design, and per-conversation scoping would break the dedup it enables.

Residual substance is limited to a **shared multi-user backend** (Redis), which was never verified
to exist in practice. Building on an unverified deployment scenario is not defensible.

**What I got wrong:** I wrote this up as a leak before working through the threat model. The
content-derived key structure — visible in the code from the start — is strong evidence the absence
of scoping is intentional rather than an oversight.

## Original claim (retained for the record)

The CCR store is **global to the proxy process**. Retrieval is authorised by *hash existence
alone* — never by "does this hash belong to the conversation asking for it?" Any conversation can
retrieve any other conversation's cached originals, given the hash.

## Evidence — verified end-to-end

`repro/xconv_leak.py`, driving the proxy with a scriptable fake upstream that simulates a model
choosing to call `headroom_retrieve`:

```
Conversation A ("tenant A: list customer records"):
  60 unique CCR hashes created
  secret visible to A's own model = False        <-- offloaded into CCR, not shown to A
  hash holding the secret = cf61cbf74e12

Conversation B ("tenant B: what is the weather today?"):
  model calls headroom_retrieve(cf61cbf74e12)
  B forwarded-upstream contains tenant A's secret : True
  -> conversation B RECEIVED tenant A's data

Plain HTTP, no conversation at all:
  GET /v1/retrieve/cf61cbf74e12 returns the secret : True
```

Conversation B was a single unrelated user turn. It received data from a different conversation
that its own model had never been shown.

## Mechanism

`headroom/ccr/tool_injection.py:322` — `verify_ownership()` is named as if it checks ownership, but
its docstring and implementation only check `store.exists(hash)`:

> "Drop any detected hash the compression store doesn't recognize. … Uses the same `store.exists()`
> check the retrieve endpoint itself performs, so a hash that survives this filter is provably
> redeemable right now"

Its actual purpose (issue #2836) is to reject *other tools'* look-alike markers, not to enforce
per-conversation ownership. `ResponseHandler._execute_retrieval()`
(`headroom/ccr/response_handler.py:183`) performs no conversation or session check either — it takes
a hash and returns the entry.

There is no conversation/session identifier stored alongside a CCR entry, so the check cannot
currently be made.

## Hash exposure

Retrieval requires knowing a 12-hex-char (48-bit) hash, which is not brute-forceable. But hashes leak:

| Endpoint (loopback-gated, unauthenticated) | Hash-like tokens exposed |
|---|---|
| `/v1/retrieve/stats` | 18 |
| `/transformations/feed` | 4 |

Hashes are also **content-derived** (`blake3(original)[:24]`), so anyone who can guess the exact
content can compute the hash — a confirmation oracle ("is this precise file cached?").

## Threat model — stated honestly

| Deployment | Severity | Reasoning |
|---|---|---|
| Single user, one machine | **Low** | All conversations belong to the same person. Still a correctness issue: data crosses project/session boundaries the user never intended (work vs. personal, client A vs. client B repos). |
| Prompt injection | **Medium** | A malicious file, web page, or MCP tool output can instruct the model to call `headroom_retrieve` with a specific hash. Requires the attacker to know or compute the hash. |
| Shared / multi-user backend | **Potentially high** | The Rust CCR store ships a **Redis backend** (`crates/headroom-core/src/ccr/backends/redis.rs`) and the project markets org-wide deployments. A store shared across users would leak across *users*, not just conversations. **NOT verified — no such deployment was tested.** |

## What I checked and could NOT confirm

- **Plaintext at rest: not reproduced.** After a clean shutdown the SQLite file was header-only
  (4096 bytes) and the secret appeared in none of `ccr_store.db`, `-wal`, or `-shm`. I am **not**
  claiming a data-at-rest exposure.
- `ccr_store.db` is mode `0644` (world-readable), whereas `probe_recorder.py:41` deliberately
  chmods its directory to `0700` because "recordings contain full conversation content in
  plaintext." The CCR store holds the same class of content with weaker permissions — an internal
  inconsistency in the project's own threat model, but of limited impact while the file stays empty.

## Reproduce

```bash
python research/repro/scriptable_upstream.py &
ANTHROPIC_TARGET_API_URL=http://127.0.0.1:8799 HEADROOM_SKIP_UPSTREAM_CHECK=1 \
  headroom proxy --port 8830 &
python research/repro/xconv_leak.py
```

## The extension that follows

**Conversation-scoped CCR.** Bind each entry to the conversation that created it, and require a
match at retrieval:

- derive a stable conversation identity from the request (the frozen prefix hash is already
  computed for cache purposes — reuse it rather than adding a new concept),
- store it with the entry; reject retrievals whose identity does not match,
- make `verify_ownership()` actually verify ownership, matching its name.

This is a genuine design contribution rather than a patch, it is testable deterministically, and it
composes with finding 01's recoverability contract.

## Open work

- [ ] Confirm the Redis backend shares a keyspace across users in a realistic org deployment.
- [ ] Check whether OpenAI/Gemini retrieval paths share the gap (expected: yes, same store).
- [ ] Measure the cost of scoping — does it reduce legitimate cross-turn reuse?
- [ ] Responsible disclosure: this should go upstream privately before publication.

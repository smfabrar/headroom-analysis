"""Query-Conditioned Retention (QCR) harness.

Measures, through the LIVE proxy path (ground truth = forwarded bytes), whether
the item a user asks about survives compression of a scalar array.

Deterministic. No API key, no LLM: the upstream is a fake recorder.

Grid:  content type x array size N x target position x question style
Arm is selected by whatever the proxy is configured with, so the SAME harness
runs the baseline and (later) the query-aware build. Nothing here knows about
the extension -- that is deliberate, so the benchmark cannot be tuned to it.

Usage:
    CAPTURE=... PORT=8841 ARM=baseline python research/repro/qcr_harness.py
"""
from __future__ import annotations
import json, os, sys, urllib.request, csv, time

PORT = os.environ.get("PORT", "8841")
CAP = os.environ["CAPTURE"]
ARM = os.environ.get("ARM", "baseline")
OUT = os.environ.get("OUT", "research/data/qcr_results.csv")

# ----------------------------------------------------------------- generators
def invoice_ids(n):
    return [f"INV-2026-{i:04d}" for i in range(1, n + 1)]

def file_paths(n):
    mods = ["auth", "billing", "session", "worker", "cache", "proxy", "codec"]
    kinds = ["manager", "handler", "client", "store", "router", "utils"]
    return [f"src/{mods[i % 7]}/{kinds[(i // 7) % 6]}_{i:03d}.py" for i in range(n)]

def log_lines(n):
    lvl = ["INFO", "WARN", "DEBUG"]
    return [f"2026-08-14T09:{i//60:02d}:{i%60:02d}Z {lvl[i%3]} worker-{i%16} "
            f"processed batch {4000+i} in {50+i%90}ms" for i in range(n)]

def test_names(n):
    mods = ["session_manager", "billing_engine", "auth_flow", "cache_layer"]
    acts = ["refresh_expired_token", "reject_bad_signature", "retry_on_429",
            "evict_lru_entry", "parse_iso_timestamp"]
    return [f"tests/unit/test_{mods[i%4]}.py::test_{acts[i%5]}_{i:03d}" for i in range(n)]

def numeric_ids(n):
    return [str(8800000 + i * 37) for i in range(n)]

GENERATORS = {
    "invoice_ids": invoice_ids, "file_paths": file_paths, "log_lines": log_lines,
    "test_names": test_names, "numeric_ids": numeric_ids,
}

# ------------------------------------------------------------------ questions
# NEEDLE  : names the target verbatim -> the case query-aware retention targets
# CONTROL : relevance is the WRONG criterion -> must NOT regress
NEEDLE = {
    "invoice_ids": lambda t: f"Is {t} in the list? Report its status.",
    "file_paths":  lambda t: f"Is {t} present? Why does it fail to import?",
    "log_lines":   lambda t: f"Explain this log entry: {t}",
    "test_names":  lambda t: f"Did {t} fail in this run?",
    "numeric_ids": lambda t: f"Is record {t} present? Who owns it?",
}
CONTROLS = {
    "count":  "How many items are in this list in total?",
    "first":  "List the first ten items in order.",
    "spread": "Describe the overall distribution and range of these items.",
}

# ------------------------------------------------------------------- plumbing
def _tool_result_of(body_json):
    """Extract the tool_result payload from a forwarded Anthropic body."""
    tr = None
    for m in body_json.get("messages", []):
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tr = b.get("content")
    if tr is None:
        return ""
    return tr if isinstance(tr, str) else json.dumps(tr)

def probe(question, items, conv_salt):
    """Send one request; return the forwarded tool_result content.

    conv_salt makes every cell a FRESH conversation. Required: compression only
    runs in full on session cold start (see research/finding-02).
    """
    # Headroom's compressed-result cache is keyed on (content, target_ratio)
    # -- the query is NOT part of the key (content_router.py:5273). Sending the
    # same array with a different question therefore REPLAYS the first cell's
    # compression. Appending a cell-unique sentinel gives every cell its own
    # cache key so the arms measure compression, not cache replay.
    items = list(items) + [f"__cell__{conv_salt}"]
    body = {
        "model": "claude-sonnet-4-5-20250929", "max_tokens": 64,
        "system": f"Session {conv_salt}.",
        "messages": [
            {"role": "user", "content": question},
            {"role": "assistant",
             "content": [{"type": "tool_use", "id": "t", "name": "q", "input": {}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": json.dumps(items)},
                {"type": "text", "text": question}]},
        ],
    }
    raw = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/messages", data=raw,
        headers={"Content-Type": "application/json", "x-api-key": "t",
                 "anthropic-version": "2023-06-01"})
    for attempt in range(8):
        try:
            urllib.request.urlopen(req, timeout=120).read()
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 529, 503):      # proxy admission control, not a
                time.sleep(1.5 * (attempt + 1))  # compression signal -- back off
                continue
            raise
    else:
        raise RuntimeError("rate limited after 8 retries")
    # Match the capture line to THIS request by its unique salt. Reading the
    # last line is unsafe: any request that does not append a line (cache hit,
    # retry, reordering) would silently attribute a previous cell's bytes to
    # this one.
    marker = f"Session {conv_salt}."
    hit = None
    for line in open(CAP).read().strip().split("\n"):
        if not line:
            continue
        if marker in line:
            hit = json.loads(line)
    if hit is None:
        raise RuntimeError(f"no forwarded capture matched salt {conv_salt!r}")
    fwd = json.loads(hit["body"])
    return _tool_result_of(fwd), len(raw), len(hit["body"])

# ----------------------------------------------------------------------- grid
SIZES = [20, 60, 150, 400, 1000]
def positions(n):
    """head, early, stride-aligned, stride-gap, middle, late, tail."""
    return sorted({0, 3, max(1, n//4), max(1, n//4)+1, n//2, (3*n)//4, n-1})

def main():
    rows, t0 = [], time.time()
    for ctype, gen in GENERATORS.items():
        for n in SIZES:
            items = gen(n)
            for p in positions(n):
                target = items[p]
                # --- needle arm
                q = NEEDLE[ctype](target)
                salt = f"{ctype}-{n}-{p}-needle-{time.time_ns():019d}"
                out, raw_in, raw_out = probe(q, items, salt)
                kept = [x for x in items if x in out]
                rows.append(dict(arm=ARM, content_type=ctype, n=n, pos=p,
                                 question="needle", target=target,
                                 target_kept=int(target in out), n_kept=len(kept),
                                 bytes_in=raw_in, bytes_out=raw_out,
                                 compressed=int(len(kept) < n)))
                print(f"{ctype:<12} n={n:<5} p={p:<5} needle  kept={len(kept):<4} "
                      f"target={'HIT ' if target in out else 'MISS'}  "
                      f"{raw_in}->{raw_out}B", flush=True)
            # --- control arm: position-independent, one per control question
            for cname, cq in CONTROLS.items():
                salt = f"{ctype}-{n}-{cname}-{time.time_ns():019d}"
                out, raw_in, raw_out = probe(cq, items, salt)
                kept = [x for x in items if x in out]
                head10 = sum(1 for x in items[:10] if x in out)
                rows.append(dict(arm=ARM, content_type=ctype, n=n, pos=-1,
                                 question=cname, target="", target_kept="",
                                 n_kept=len(kept), bytes_in=raw_in, bytes_out=raw_out,
                                 compressed=int(len(kept) < n), head10_kept=head10))
                print(f"{ctype:<12} n={n:<5} {cname:<7} control kept={len(kept):<4} "
                      f"head10={head10}", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cols = ["arm","content_type","n","pos","question","target","target_kept",
            "n_kept","bytes_in","bytes_out","compressed","head10_kept"]
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({c: r.get(c, "") for c in cols})

    nd = [r for r in rows if r["question"] == "needle"]
    hits = sum(r["target_kept"] for r in nd)
    comp = [r for r in nd if r["compressed"]]
    chits = sum(r["target_kept"] for r in comp)
    print("\n" + "="*64)
    print(f"arm={ARM}  cells={len(rows)}  elapsed={time.time()-t0:.0f}s -> {OUT}")
    print(f"needle cells                 : {len(nd)}")
    print(f"  retained (all cells)       : {hits}/{len(nd)} = {hits/max(1,len(nd)):.1%}")
    print(f"  cells where compression fired: {len(comp)}")
    if comp:
        print(f"  retained | compressed      : {chits}/{len(comp)} = {chits/len(comp):.1%}")
        exp = sum(r['n_kept']/r['n'] for r in comp)/len(comp)
        print(f"  chance baseline E[K/N]     : {exp:.1%}")

if __name__ == "__main__":
    main()

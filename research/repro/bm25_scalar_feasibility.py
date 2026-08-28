"""Can BM25 separate items in a SCALAR array?

Kill-criterion test for improvement-01. A dict item is a rich record; a bare
scalar like "INV-2026-0044" is a near-degenerate BM25 document. If BM25 cannot
rank the queried item into the top-K budget, the mechanism must be something
simpler (exact/substring match), and the proposal changes shape.

Deterministic. No API key. Run:
    /Users/fahim/Desktop/headroom/.venv-run/bin/python research/repro/bm25_scalar_feasibility.py
"""
import random
from headroom.relevance import BM25Scorer

N = 200          # array size
K = 15           # Headroom's max_items_after_crush default
random.seed(1234)

# ---------------------------------------------------------------- generators
def invoice_ids(n):
    return [f"INV-2026-{i:04d}" for i in range(1, n + 1)]

def file_paths(n):
    mods = ["auth", "billing", "session", "worker", "cache", "proxy", "codec"]
    kinds = ["manager", "handler", "client", "store", "router", "utils"]
    out = []
    for i in range(n):
        out.append(f"src/{mods[i % len(mods)]}/{kinds[(i // 7) % len(kinds)]}_{i:03d}.py")
    return out

def log_lines(n):
    lvl = ["INFO", "WARN", "DEBUG"]
    return [f"2026-08-14T09:{i//60:02d}:{i%60:02d}Z {lvl[i%3]} worker-{i%16} "
            f"processed batch {4000+i} in {50+i%90}ms" for i in range(n)]

def test_names(n):
    mods = ["session_manager", "billing_engine", "auth_flow", "cache_layer"]
    acts = ["refresh_expired_token", "reject_bad_signature", "retry_on_429",
            "evict_lru_entry", "parse_iso_timestamp"]
    return [f"tests/unit/test_{mods[i%4]}.py::test_{acts[i%5]}_{i:03d}"
            for i in range(n)]

def numeric_ids(n):
    return [str(8800000 + i * 37) for i in range(n)]

# ------------------------------------------------------- query constructors
# EXACT: agent quotes the identifier verbatim (the common real case)
# DESCR: agent describes it semantically, no literal token overlap
CASES = [
    ("invoice_ids", invoice_ids,
     lambda t: f"What is the status of invoice {t}? Was it paid?",
     lambda t: "Which invoice was rejected by the payment processor?"),
    ("file_paths", file_paths,
     lambda t: f"Why does {t} raise an ImportError on startup?",
     lambda t: "Which billing module has the circular import problem?"),
    ("log_lines", log_lines,
     lambda t: f"Explain this log entry: {t}",
     lambda t: "Which worker took the longest to process a batch?"),
    ("test_names", test_names,
     lambda t: f"Why is {t} failing after the token refactor?",
     lambda t: "Which session test broke after the token refactor?"),
    ("numeric_ids", numeric_ids,
     lambda t: f"Look up record {t} and tell me its owner.",
     lambda t: "Which record has a null owner field?"),
]

scorer = BM25Scorer()
# sample target positions: head / stride-aligned / stride-gap / tail
TARGETS = [0, 3, 47, 48, 99, 137, 198]

def rank_of(items, query, target_idx):
    scores = scorer.score_batch(items, query)
    vals = [getattr(s, "score", s) for s in scores]
    order = sorted(range(len(items)), key=lambda i: -vals[i])
    return order.index(target_idx) + 1, vals

print(f"N={N}  K={K}  random baseline = K/N = {K/N:.1%}\n")
print(f"{'content type':<14} {'query':<7} {'in top-K':>9} {'median rank':>12} {'worst rank':>11}")
print("-" * 60)

summary = {}
for name, gen, qexact, qdescr in CASES:
    items = gen(N)
    for qkind, qfn in (("exact", qexact), ("descr", qdescr)):
        ranks = []
        for t in TARGETS:
            r, vals = rank_of(items, qfn(items[t]), t)
            ranks.append(r)
        ranks.sort()
        hits = sum(1 for r in ranks if r <= K)
        med = ranks[len(ranks)//2]
        print(f"{name:<14} {qkind:<7} {hits}/{len(TARGETS):<7} {med:>12} {ranks[-1]:>11}")
        summary[(name, qkind)] = (hits, len(TARGETS))

ex_h = sum(h for (n,k),(h,t) in summary.items() if k=="exact")
ex_t = sum(t for (n,k),(h,t) in summary.items() if k=="exact")
de_h = sum(h for (n,k),(h,t) in summary.items() if k=="descr")
de_t = sum(t for (n,k),(h,t) in summary.items() if k=="descr")
print("-" * 60)
print(f"EXACT-mention queries : {ex_h}/{ex_t} = {ex_h/ex_t:.0%} retained in top-K")
print(f"DESCRIPTIVE queries   : {de_h}/{de_t} = {de_h/de_t:.0%} retained in top-K")
print(f"Headroom today (K/N)  : {K/N:.0%} (position-independent, query-independent)")

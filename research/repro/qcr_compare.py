"""Compare two QCR arms cell-by-cell.

Two jobs:
1. PARITY  -- with the gate off, the rebuilt binary must reproduce the
   original baseline exactly. Any drift means the change is not inert
   by default and the comparison is contaminated.
2. EFFECT  -- with the gate on, report retention by stratum plus the
   control-question regression guard and the token-cost check.
"""
import csv, sys, collections

def load(p):
    rows = list(csv.DictReader(open(p)))
    for r in rows:
        for k in ("n", "pos", "n_kept", "bytes_in", "bytes_out", "compressed"):
            if r[k] != "": r[k] = int(r[k])
        r["target_kept"] = int(r["target_kept"]) if r["target_kept"] != "" else None
    return rows

def key(r): return (r["content_type"], r["n"], r["pos"], r["question"])

def stratum(r):
    n, p, k = r["n"], r["pos"], r["n_kept"]
    hb = max(1, int(round(0.30 * k))); tb = max(1, int(round(0.15 * k)))
    if p < hb: return "head"
    if p >= n - tb: return "tail"
    return "interior"

a_path, b_path = sys.argv[1], sys.argv[2]
A = {key(r): r for r in load(a_path)}
B = {key(r): r for r in load(b_path)}
common = sorted(set(A) & set(B))
print(f"A = {a_path}\nB = {b_path}\ncommon cells: {len(common)}\n")

# ---------------------------------------------------------------- parity
diff_kept = [k for k in common if A[k]["n_kept"] != B[k]["n_kept"]]
diff_tgt  = [k for k in common if A[k]["target_kept"] != B[k]["target_kept"]]
diff_byte = [k for k in common if A[k]["bytes_out"] != B[k]["bytes_out"]]
print("PARITY (expect all zero when B is the gate-off rebuild)")
print(f"  cells differing in n_kept      : {len(diff_kept)}")
print(f"  cells differing in target_kept : {len(diff_tgt)}")
print(f"  cells differing in bytes_out   : {len(diff_byte)}")

# ---------------------------------------------------------------- effect
print("\nRETENTION BY STRATUM (needle cells)")
print(f"{'stratum':<10} {'cells':>6} {'A':>10} {'B':>10} {'delta':>9}")
print("-" * 48)
nd = [k for k in common if k[3] == "needle"]
by = collections.defaultdict(list)
for k in nd: by[stratum(A[k])].append(k)
for s in ("head", "interior", "tail"):
    g = by.get(s, [])
    if not g: continue
    ra = sum(A[k]["target_kept"] for k in g) / len(g)
    rb = sum(B[k]["target_kept"] for k in g) / len(g)
    print(f"{s:<10} {len(g):>6} {ra:>9.1%} {rb:>9.1%} {(rb-ra)*100:>+7.1f}pp")
ra = sum(A[k]["target_kept"] for k in nd) / len(nd)
rb = sum(B[k]["target_kept"] for k in nd) / len(nd)
print("-" * 48)
print(f"{'all':<10} {len(nd):>6} {ra:>9.1%} {rb:>9.1%} {(rb-ra)*100:>+7.1f}pp")

print("\nINTERIOR RETENTION BY N  (the regime that matters)")
print(f"{'N':>6} {'cells':>6} {'A':>10} {'B':>10} {'delta':>9}")
print("-" * 46)
inter = by.get("interior", [])
for n in sorted({A[k]["n"] for k in inter}):
    g = [k for k in inter if A[k]["n"] == n]
    ra = sum(A[k]["target_kept"] for k in g) / len(g)
    rb = sum(B[k]["target_kept"] for k in g) / len(g)
    print(f"{n:>6} {len(g):>6} {ra:>9.1%} {rb:>9.1%} {(rb-ra)*100:>+7.1f}pp")

print("\nTOKEN COST (needle cells; must not regress)")
ba = sum(A[k]["bytes_out"] for k in nd); bb = sum(B[k]["bytes_out"] for k in nd)
ka = sum(A[k]["n_kept"] for k in nd);    kb = sum(B[k]["n_kept"] for k in nd)
print(f"  forwarded bytes  A={ba}  B={bb}  delta={bb-ba:+d} ({(bb-ba)/ba:+.2%})")
print(f"  items retained   A={ka}  B={kb}  delta={kb-ka:+d}")

print("\nCONTROL QUESTIONS (relevance is the WRONG criterion; expect ~no change)")
print(f"{'question':<10} {'cells':>6} {'A kept':>9} {'B kept':>9} {'A head10':>10} {'B head10':>10}")
print("-" * 60)
for q in sorted({k[3] for k in common if k[3] != "needle"}):
    g = [k for k in common if k[3] == q]
    aa = sum(A[k]["n_kept"] for k in g)/len(g); bb2 = sum(B[k]["n_kept"] for k in g)/len(g)
    ah = sum(int(A[k]["head10_kept"] or 0) for k in g)/len(g)
    bh = sum(int(B[k]["head10_kept"] or 0) for k in g)/len(g)
    print(f"{q:<10} {len(g):>6} {aa:>9.1f} {bb2:>9.1f} {ah:>10.1f} {bh:>10.1f}")

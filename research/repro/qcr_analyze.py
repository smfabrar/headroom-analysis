"""Stratified analysis of QCR results.

The pooled retention rate is NOT the headline: position sampling is deliberately
biased toward head/tail (which Headroom structurally guarantees), so pooling
inflates it. Retention must be reported per position stratum.
"""
import csv, sys, collections
path = sys.argv[1] if len(sys.argv) > 1 else "research/data/qcr_baseline.csv"
rows = list(csv.DictReader(open(path)))
for r in rows:
    for k in ("n","pos","n_kept","bytes_in","bytes_out","compressed"):
        if r[k] != "": r[k] = int(r[k])
    r["target_kept"] = int(r["target_kept"]) if r["target_kept"] != "" else None

needle = [r for r in rows if r["question"] == "needle"]

def stratum(r):
    n, p, k = r["n"], r["pos"], r["n_kept"]
    head_band = max(1, int(round(0.30 * k)))      # first_fraction = 0.30 of K
    tail_band = max(1, int(round(0.15 * k)))      # last_fraction  = 0.15 of K
    if p < head_band:      return "head (guaranteed)"
    if p >= n - tail_band: return "tail (guaranteed)"
    return "interior (lottery)"

print(f"file: {path}   needle cells: {len(needle)}\n")
print("RETENTION BY POSITION STRATUM")
print(f"{'stratum':<22} {'cells':>6} {'retained':>9} {'rate':>8}")
print("-"*48)
by = collections.defaultdict(list)
for r in needle: by[stratum(r)].append(r)
for s in ("head (guaranteed)", "interior (lottery)", "tail (guaranteed)"):
    g = by.get(s, [])
    if not g: continue
    h = sum(x["target_kept"] for x in g)
    print(f"{s:<22} {len(g):>6} {h:>9} {h/len(g):>7.1%}")
allh = sum(r["target_kept"] for r in needle)
print("-"*48)
print(f"{'POOLED (misleading)':<22} {len(needle):>6} {allh:>9} {allh/len(needle):>7.1%}")

print("\n\nINTERIOR RETENTION BY ARRAY SIZE  (the regime that matters)")
print(f"{'N':>6} {'cells':>6} {'retained':>9} {'rate':>8} {'chance K/N':>11} {'kept':>6}")
print("-"*52)
inter = [r for r in needle if stratum(r) == "interior (lottery)"]
for n in sorted({r["n"] for r in inter}):
    g = [r for r in inter if r["n"] == n]
    h = sum(x["target_kept"] for x in g)
    kn = sum(x["n_kept"]/x["n"] for x in g)/len(g)
    kept = g[0]["n_kept"]
    print(f"{n:>6} {len(g):>6} {h:>9} {h/len(g):>7.1%} {kn:>10.1%} {kept:>6}")

print("\n\nINTERIOR RETENTION BY CONTENT TYPE")
print(f"{'content type':<14} {'cells':>6} {'retained':>9} {'rate':>8}")
print("-"*42)
for c in sorted({r["content_type"] for r in inter}):
    g = [r for r in inter if r["content_type"] == c]
    h = sum(x["target_kept"] for x in g)
    print(f"{c:<14} {len(g):>6} {h:>9} {h/len(g):>7.1%}")

print("\n\nCOMPRESSION (all needle cells)")
tot_in = sum(r["bytes_in"] for r in needle); tot_out = sum(r["bytes_out"] for r in needle)
print(f"  forwarded/original bytes: {tot_out}/{tot_in} = {tot_out/tot_in:.1%}  "
      f"(saving {1-tot_out/tot_in:.1%})")
print(f"  cells where compression fired: {sum(r['compressed'] for r in needle)}/{len(needle)}")

ctl = [r for r in rows if r["question"] != "needle"]
print(f"\nCONTROL CELLS: {len(ctl)}  (relevance is the WRONG criterion here)")
print(f"{'question':<10} {'cells':>6} {'mean kept':>10} {'mean head10':>12}")
print("-"*42)
for q in sorted({r["question"] for r in ctl}):
    g = [r for r in ctl if r["question"] == q]
    mk = sum(x["n_kept"] for x in g)/len(g)
    mh = sum(int(x["head10_kept"] or 0) for x in g)/len(g)
    print(f"{q:<10} {len(g):>6} {mk:>10.1f} {mh:>12.1f}")

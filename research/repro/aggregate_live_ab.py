"""Aggregate repeated live A/B runs (agent_anthropic_bench.py) into one table.

Reports every run individually plus per-arm summaries, so the reader sees
consistency across repeats instead of a single unreplicated number.

Usage:
    python3 research/repro/aggregate_live_ab.py research/data/live_ab/*.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("usage: aggregate_live_ab.py <run json> [...]")
        return 2

    arms: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(paths):
        d = json.loads(p.read_text())
        rows = d["rows"]
        if not rows:
            continue
        # turn1_bytes is the size of the FIRST compression. The defect acts
        # between turn 1 and turn 2, so measuring from rows[0] (turn 2) would
        # report zero change for a session that lost 19%.
        b0 = d.get("turn1_bytes") or rows[0]["bytes"]
        bN = rows[-1]["bytes"]
        misses = sum(1 for r in rows if r.get("cache_read", 0) == 0)
        # Group by the arm string as recorded, never by parsing the filename:
        # "baseline-noidle" must not be mangled into "baseline".
        arm = d.get("arm", "unknown")
        idle = d.get("idle_every", None)
        label = f"{arm} idle/{idle}" if idle else f"{arm} no-idle"
        arms[label].append({
            "file": p.name,
            "turn1_bytes": b0,
            "final_bytes": bN,
            "delta_pct": 100.0 * (bN - b0) / b0 if b0 else 0.0,
            "retained_first": rows[0]["retained"],
            "retained_last": rows[-1]["retained"],
            "probe_all": all(r["probe_in_context"] for r in rows),
            "correct": sum(1 for r in rows if r["correct"]),
            "turns": len(rows),
            "misses": misses,
        })

    print(f"{'arm':<10} {'run':<22} {'bytes t1->tN':<18} {'Δ%':>7} "
          f"{'items':<10} {'misses':>6} {'probe':>6} {'acc':>6}")
    print("-" * 92)
    for arm in sorted(arms):
        for r in arms[arm]:
            print(f"{arm:<10} {r['file']:<22} "
                  f"{r['turn1_bytes']}->{r['final_bytes']:<11} "
                  f"{r['delta_pct']:>6.1f} "
                  f"{r['retained_first']}->{r['retained_last']:<6} "
                  f"{r['misses']:>6} "
                  f"{'yes' if r['probe_all'] else 'NO':>6} "
                  f"{r['correct']}/{r['turns']:>3}")

    print("\nper-arm summary")
    print("-" * 92)
    for arm in sorted(arms):
        rs = arms[arm]
        deltas = [r["delta_pct"] for r in rs]
        acc = sum(r["correct"] for r in rs)
        tot = sum(r["turns"] for r in rs)
        print(f"{arm:<10} n={len(rs)}  "
              f"Δbytes mean {sum(deltas)/len(deltas):.1f}% "
              f"(min {min(deltas):.1f}%, max {max(deltas):.1f}%)  "
              f"accuracy {acc}/{tot}  "
              f"probe survived all turns: "
              f"{sum(1 for r in rs if r['probe_all'])}/{len(rs)} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

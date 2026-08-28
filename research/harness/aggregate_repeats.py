"""Aggregate repeated property_sweep runs and report only stable verdicts.

A single sweep pass cannot support a violation count: at least one cell
(anthropic/intermittent/json_string_array) was observed to hold under full-matrix
load and to fail in isolated repeats. Request latency differs under load, and
`idle_seconds` feeds Headroom's net-cost policy, so timing can change decisions.

This script classifies each cell in every repeat and reports:

  STABLE-VIOLATION   violated in every repeat        -> reportable defect
  STABLE-HOLDS       held in every repeat            -> reportable pass
  STABLE-VACUOUS     compression never fired         -> tested nothing
  FLAKY              verdict changed between repeats -> reported as flaky,
                     never counted as a pass

Usage:
    python3 research/harness/aggregate_repeats.py research/data/property_sweep_r*.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_sweep import classify, VACUOUS, HOLDS, VIOLATION, ERROR  # noqa: E402


def key(c: dict) -> tuple:
    return (c["provider"], c["regime"], c["arm"], c["content_type"])


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("usage: aggregate_repeats.py <sweep json> [<sweep json> ...]")
        return 2

    runs: list[dict[tuple, dict]] = []
    for p in paths:
        cells = json.loads(p.read_text())
        runs.append({key(c): c for c in cells})
    n = len(runs)
    print(f"aggregating {n} repeats: {', '.join(p.name for p in paths)}\n")

    all_keys = sorted({k for r in runs for k in r})
    verdicts: dict[tuple, list[str]] = defaultdict(list)
    series: dict[tuple, list[list[int]]] = defaultdict(list)
    for k in all_keys:
        for r in runs:
            c = r.get(k)
            if c is None:
                verdicts[k].append("missing")
                continue
            verdicts[k].append(classify(c))
            series[k].append(c.get("retention") or [])

    stable_viol, stable_hold, stable_vac, flaky, errs = [], [], [], [], []
    for k in all_keys:
        vs = set(verdicts[k])
        if vs == {VIOLATION}:
            stable_viol.append(k)
        elif vs == {HOLDS}:
            stable_hold.append(k)
        elif vs == {VACUOUS}:
            stable_vac.append(k)
        elif ERROR in vs or "missing" in vs:
            errs.append(k)
        else:
            flaky.append(k)

    print("=" * 96)
    print("STABLE VIOLATIONS  (property failed in every repeat)")
    print("=" * 96)
    if not stable_viol:
        print("  none")
    for k in stable_viol:
        first = [s[0] for s in series[k] if s]
        last = [s[-1] for s in series[k] if s]
        print(f"  {k[0]:<10} {k[1]:<13} {k[2]:<9} {k[3]:<20} "
              f"retained {first} -> {last}")

    print("\n" + "=" * 96)
    print("FLAKY  (verdict changed between repeats -- NOT counted as passing)")
    print("=" * 96)
    if not flaky:
        print("  none")
    for k in flaky:
        print(f"  {k[0]:<10} {k[1]:<13} {k[2]:<9} {k[3]:<20} "
              f"{verdicts[k]}  retention_last={[s[-1] for s in series[k] if s]}")

    print("\n" + "=" * 96)
    print("SUMMARY")
    print("=" * 96)
    print(f"  repeats                       : {n}")
    print(f"  cells per repeat              : {len(all_keys)}")
    print(f"  stable vacuous (tested nothing): {len(stable_vac)}")
    print(f"  stable holds                  : {len(stable_hold)}")
    print(f"  STABLE VIOLATIONS             : {len(stable_viol)}")
    print(f"  flaky                         : {len(flaky)}")
    print(f"  errors/missing                : {len(errs)}")

    checked = len(stable_hold) + len(stable_viol) + len(flaky)
    print(f"\n  meaningfully checked          : {checked}")
    if checked:
        print(f"  violation rate (stable)       : "
              f"{len(stable_viol)}/{checked} = {len(stable_viol)/checked:.0%}")

    by_arm = Counter(k[2] for k in stable_viol)
    by_prov = Counter(k[0] for k in stable_viol)
    if stable_viol:
        print(f"\n  stable violations by provider : {dict(by_prov)}")
        print(f"  stable violations by arm      : {dict(by_arm)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

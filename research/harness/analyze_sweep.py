"""Analyse property_sweep.json.

The sweep's inline reporting counts a cell as passing P1 whenever the forwarded
bytes are stable across turns. That conflates two very different outcomes:

  * VACUOUS   -- compression never fired, so nothing could decay. The property
                 holds, but the cell tested nothing.
  * HOLDS     -- compression fired AND the result was stable across turns.

Only HOLDS cells are evidence. Reporting them together would inflate the
denominator and overstate how much was actually checked.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT = REPO / "research" / "data" / "property_sweep.json"

VACUOUS, HOLDS, VIOLATION, ERROR = "vacuous", "holds", "VIOLATION", "error"


def classify(c: dict) -> str:
    if c.get("error"):
        return ERROR
    ret = c.get("retention") or []
    nb = c.get("nbytes") or []
    if not ret or not nb:
        return ERROR
    stable = all(r == ret[0] for r in ret) and all(b == nb[0] for b in nb)
    if not stable:
        return VIOLATION
    # Compression fired iff the first forwarded copy is already smaller than the
    # payload we sent -- either probes were dropped or bytes were reduced.
    # A stable cell where nothing was compressed tests nothing.
    fired = ret[0] < c.get("n_probes", 0) or nb[0] < c.get("payload_bytes", 0)
    return HOLDS if fired else VACUOUS


def key(c: dict) -> tuple:
    return (c["provider"], c["regime"], c["arm"], c["content_type"])


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    cells = json.loads(path.read_text())
    for c in cells:
        c["_class"] = classify(c)

    print("=" * 92)
    print("P1  IDEMPOTENCE -- an unchanged tool output must forward unchanged bytes")
    print("=" * 92)
    print(f"{'provider':<10} {'regime':<13} {'arm':<9} {'content':<20} "
          f"{'verdict':<10} {'retained':<14} bytes")
    print("-" * 92)
    for c in sorted(cells, key=key):
        ret = c.get("retention") or []
        nb = c.get("nbytes") or []
        series = f"{ret[0]}->{ret[-1]}" if ret else "-"
        byt = f"{nb[0]}->{nb[-1]}" if nb else "-"
        print(f"{c['provider']:<10} {c['regime']:<13} {c['arm']:<9} "
              f"{c['content_type']:<20} {c['_class']:<10} {series:<14} {byt}")

    print("\n" + "=" * 92)
    print("P2  CROSS-HANDLER EQUIVALENCE -- same payload, regime and arm")
    print("=" * 92)
    idx = {key(c): c for c in cells}
    div = 0
    for k, c in sorted(idx.items()):
        if k[0] != "anthropic":
            continue
        o = idx.get(("openai",) + k[1:])
        if not o:
            continue
        if c["_class"] in (ERROR,) or o["_class"] in (ERROR,):
            continue
        a_ret, o_ret = c.get("retention") or [], o.get("retention") or []
        if not a_ret or not o_ret:
            continue
        if a_ret[-1] != o_ret[-1] or c["_class"] != o["_class"]:
            div += 1
            print(f"  DIVERGE {k[1]:<13} {k[2]:<9} {k[3]:<20} "
                  f"anthropic={a_ret[-1]:<5}({c['_class']})  "
                  f"openai={o_ret[-1]}({o['_class']})")
    if not div:
        print("  no divergences")

    print("\n" + "=" * 92)
    print("SUMMARY")
    print("=" * 92)
    tally = Counter(c["_class"] for c in cells)
    print(f"  cells run                       : {len(cells)}")
    print(f"  vacuous (compression never fired): {tally[VACUOUS]}")
    print(f"  meaningfully checked             : {tally[HOLDS] + tally[VIOLATION]}")
    print(f"     -- property holds             : {tally[HOLDS]}")
    print(f"     -- PROPERTY VIOLATED          : {tally[VIOLATION]}")
    print(f"  errors                           : {tally[ERROR]}")
    print(f"  cross-handler divergences        : {div}")

    if tally[VIOLATION]:
        print("\n  violations:")
        for c in sorted(cells, key=key):
            if c["_class"] == VIOLATION:
                ret = c["retention"]
                print(f"    {c['provider']}/{c['regime']}/{c['arm']}/"
                      f"{c['content_type']}: {ret[0]} -> {ret[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

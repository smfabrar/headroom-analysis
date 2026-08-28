#!/usr/bin/env bash
# Reproduces the live Anthropic A/B (Table 2 of ANALYSIS.md).
#
# Three arms, each replicated N times:
#   baseline      unmodified Headroom, 330 s idle gaps (cache allowed to lapse)
#   fixed         HEADROOM_IDEMPOTENT_COMPRESSION=1, same idle gaps
#   baseline-noidle   control: unmodified, NO idle gaps, cache stays warm
#
# Every session gets a FRESH proxy and a FRESH recorder, so Headroom's
# compression cache never leaks between runs.
#
# Needs CLAUDE_API_KEY in research/.env.
# Usage: ./research/run_live_ab.sh [RUNS_PER_ARM]   (default 3)
set -euo pipefail
cd "$(dirname "$0")/.."

RUNS="${1:-3}"
OUT=research/data/live_ab
mkdir -p "$OUT"

if pgrep -f "property_sweep.py" >/dev/null 2>&1; then
  echo "ERROR: the deterministic sweep is running; it perturbs timing." >&2
  exit 1
fi

cleanup () { pkill -f recording_upstream 2>/dev/null || true
             pkill -f "headroom.cli proxy" 2>/dev/null || true; }
trap cleanup EXIT

for r in $(seq 1 "$RUNS"); do
  # Arms run back to back, never in parallel: parallel arms share machine load,
  # and load perturbs Headroom's timing-sensitive decisions (see ANALYSIS 5.1).
  ./research/run_session.sh baseline        2 "$r" 4 || echo "  (session failed)"
  ./research/run_session.sh fixed           2 "$r" 4 || echo "  (session failed)"
  ./research/run_session.sh baseline-noidle 0 "$r" 4 || echo "  (session failed)"
done

python3 research/repro/aggregate_live_ab.py "$OUT"/*.json

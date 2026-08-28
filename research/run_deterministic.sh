#!/usr/bin/env bash
# Reproduces the deterministic property benchmark (Table 1 of ANALYSIS.md).
# No API key required. ~8 min per pass. Usage: ./research/run_deterministic.sh [N_PASSES]
set -euo pipefail
cd "$(dirname "$0")/.."
N="${1:-5}"

# The sweep is load-sensitive: request latency feeds Headroom's net-cost policy,
# so a busy machine changes compression decisions. Section 5.1 of ANALYSIS.md
# documents one cell that passed under load and failed in isolation. Refuse to
# run alongside anything that would perturb timing.
if pgrep -f "agent_anthropic_bench|property_sweep.py" >/dev/null 2>&1; then
  echo "ERROR: another benchmark is running. This sweep must run in isolation." >&2
  exit 1
fi
trap 'pkill -f fake_upstream 2>/dev/null; pkill -f "headroom.cli proxy" 2>/dev/null' EXIT
for r in $(seq 1 "$N"); do
  echo "=== pass $r/$N ==="
  python3 research/harness/property_sweep.py --turns 10 --items 300 \
    --out "research/data/property_sweep_r$r.json"
done
python3 research/harness/aggregate_repeats.py research/data/property_sweep_r*.json

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

free_port () { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'; }

# run_session <arm> <idle_every> <run_index> <proxy_env>
run_session () {
  local arm="$1" idle="$2" idx="$3" penv="$4"
  local rec_port proxy_port cap
  rec_port=$(free_port); proxy_port=$(free_port)
  cap="/tmp/live_${arm}_r${idx}.jsonl"; : > "$cap"

  CAPTURE="$cap" REAL_UPSTREAM=https://api.anthropic.com REC_PORT="$rec_port" \
    python3 research/repro/recording_upstream.py > "/tmp/live_rec_${arm}_r${idx}.log" 2>&1 &
  local rec_pid=$!
  sleep 3

  env $penv HEADROOM_RATE_LIMIT_ENABLED=false \
    headroom proxy --mode token --port "$proxy_port" \
    --anthropic-api-url "http://127.0.0.1:$rec_port" \
    > "/tmp/live_proxy_${arm}_r${idx}.log" 2>&1 &
  local proxy_pid=$!
  sleep 12

  echo "[$arm] run $idx/$RUNS (proxy $proxy_port, idle_every=$idle)"
  python3 research/repro/agent_anthropic_bench.py \
    --arm "$arm" --turns 7 --idle-every "$idle" --idle-seconds 330 \
    --port "$proxy_port" --capture "$cap" \
    --out "$OUT/${arm}_r${idx}.json" || echo "  (session failed, continuing)"

  kill "$proxy_pid" "$rec_pid" 2>/dev/null || true
  sleep 2
}

for r in $(seq 1 "$RUNS"); do
  # The two idle arms run back to back rather than in parallel: parallel arms
  # share machine load, and load perturbs Headroom's timing-sensitive decisions.
  run_session baseline        2 "$r" ""
  run_session fixed           2 "$r" "HEADROOM_IDEMPOTENT_COMPRESSION=1"
  run_session baseline-noidle 0 "$r" ""
done

python3 research/repro/aggregate_live_ab.py "$OUT"/*.json

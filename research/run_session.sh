#!/usr/bin/env bash
# Run ONE live-API session with a fresh proxy and recorder.
#
#   ./research/run_session.sh <arm> <idle_every> <run_index> [turns]
#
# arm            baseline | fixed | baseline-noidle
# idle_every     insert a 330 s idle gap before every Nth probe turn (0 = never)
# run_index      replicate number, used in the output filename
#
# Each session is fully isolated: a new proxy process means an empty compression
# cache, so replicates never contaminate each other.
set -euo pipefail
cd "$(dirname "$0")/.."

ARM="${1:?arm required}"
IDLE="${2:?idle_every required}"
IDX="${3:?run index required}"
TURNS="${4:-4}"

OUT=research/data/live_ab
mkdir -p "$OUT"

# Match any arm whose name starts with "fixed" (fixed, fixed-noidle, ...).
# A bare "fixed)" would silently run fixed-noidle as an unpatched baseline.
case "$ARM" in
  fixed*) PENV="HEADROOM_IDEMPOTENT_COMPRESSION=1" ;;
  *)      PENV="" ;;
esac

free_port () { python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()'; }
REC_PORT=$(free_port); PROXY_PORT=$(free_port)
CAP="/tmp/live_${ARM}_r${IDX}.jsonl"; : > "$CAP"

CAPTURE="$CAP" REAL_UPSTREAM=https://api.anthropic.com REC_PORT="$REC_PORT" \
  python3 research/repro/recording_upstream.py > "/tmp/live_rec_${ARM}_r${IDX}.log" 2>&1 &
REC_PID=$!
sleep 3

env $PENV HEADROOM_RATE_LIMIT_ENABLED=false \
  headroom proxy --mode token --port "$PROXY_PORT" \
  --anthropic-api-url "http://127.0.0.1:$REC_PORT" \
  > "/tmp/live_proxy_${ARM}_r${IDX}.log" 2>&1 &
PROXY_PID=$!

cleanup () { kill "$PROXY_PID" "$REC_PID" 2>/dev/null || true; }
trap cleanup EXIT
sleep 12

python3 research/repro/agent_anthropic_bench.py \
  --arm "$ARM" --turns "$TURNS" --idle-every "$IDLE" --idle-seconds 330 \
  --port "$PROXY_PORT" --capture "$CAP" \
  --out "$OUT/${ARM}_r${IDX}.json"

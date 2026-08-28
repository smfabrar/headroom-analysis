"""Real Claude agent, Anthropic path, through Headroom -- does the decay bite in vivo?

Every defect found by the property sweep lives on the Anthropic handler path, but
the sweep drives synthetic payloads against a fake upstream. This drives a REAL
Claude model doing REAL tool calls through the proxy, with a recording
pass-through relaying to api.anthropic.com, so:

  * the model's answers are genuine,
  * `cache_read_input_tokens` is whatever Anthropic actually reports,
  * the forwarded bytes are captured exactly as the model received them.

Protocol
--------
Turn 1  the agent calls a `search_logs` tool; we return 300 log lines.
Turn 2+ the user asks about a specific log line that SURVIVED turn 1's
        compression -- so the answer is knowable from what the model was given.
        If re-compression later drops that line, the model can no longer answer.

Measured per turn: probes retained in the forwarded body, whether the model
answers correctly, and the cache-read tokens Anthropic reports.

Usage:
    python3 research/repro/agent_anthropic_bench.py --arm baseline --turns 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

MODEL = os.environ.get("BENCH_MODEL", "claude-sonnet-4-5-20250929")
N_LINES = int(os.environ.get("N_LINES", "300"))

SYS_PAD = ("You are a build-log triage assistant. Answer strictly from the tool "
           "output you were given. If the relevant log line is not present in "
           "your context, reply exactly: NOT IN CONTEXT. ")
SYS_PAD = (SYS_PAD * 60)[:12000]

TOOLS = [{
    "name": "search_logs",
    "description": "Search the CI build logs for worker task records.",
    "input_schema": {"type": "object",
                     "properties": {"query": {"type": "string"}},
                     "required": ["query"]},
}]


def load_key() -> str:
    env = REPO / "research" / ".env"
    for line in env.read_text().splitlines():
        m = re.match(r"^CLAUDE_API_KEY=(.*)", line.strip())
        if m:
            return m.group(1).strip().strip('"').strip("'")
    raise SystemExit("CLAUDE_API_KEY not found in research/.env")


def make_logs(salt: str):
    """300 log lines. Each carries a unique task id and a unique duration."""
    lvl = ["INFO", "WARN", "ERROR"]
    lines, facts = [], {}
    for i in range(N_LINES):
        tid = f"task_{salt}_{i:04d}"
        dur = 1000 + i * 7  # unique per line
        facts[tid] = dur
        lines.append(f"2026-08-26 12:{i//60:02d}:{i%60:02d} {lvl[i%3]} "
                     f"worker {tid} completed in {dur}ms")
    return "\n".join(lines), facts


def forwarded_tool_result(capture: Path, salt: str) -> str:
    rec = None
    for line in capture.read_text().splitlines():
        if line and salt in line:
            rec = json.loads(line)
    if not rec:
        return ""
    body = json.loads(rec["body"])
    for m in body.get("messages", []):
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    v = b.get("content")
                    return v if isinstance(v, str) else json.dumps(v)
    return ""


def call(url: str, key: str, body: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read())
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            print(f"    retry {attempt+1}: {e}", flush=True)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def text_of(resp: dict) -> str:
    return " ".join(b.get("text", "") for b in resp.get("content", [])
                    if isinstance(b, dict) and b.get("type") == "text")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "9500")))
    ap.add_argument("--capture", default=os.environ.get("CAPTURE", "/tmp/agent_anth.jsonl"))
    ap.add_argument("--turns", type=int, default=8)
    ap.add_argument("--arm", default="baseline")
    ap.add_argument("--out", default=None)
    # Anthropic's prompt cache has a ~5 min TTL. Idling past it makes the next
    # turn a genuine cache miss, which is what drives PrefixTracker back to 0.
    ap.add_argument("--idle-every", type=int, default=0,
                    help="insert an idle gap before every Nth probe turn")
    ap.add_argument("--idle-seconds", type=int, default=330)
    a = ap.parse_args()

    key = load_key()
    cap = Path(a.capture)
    # The recorder writes to whatever CAPTURE it was started with. Pointing the
    # bench at a different path silently yields "no capture" mid-run, so check
    # the wiring before spending any API calls.
    if not cap.exists():
        raise SystemExit(
            f"capture file {cap} does not exist -- start recording_upstream.py "
            f"with CAPTURE={cap} before running this bench")
    url = f"http://127.0.0.1:{a.port}/v1/messages"
    salt = f"A{int(time.time())%10**7:07d}"
    payload, facts = make_logs(salt)
    system = f"Session {salt}. {SYS_PAD}"

    # --- turn 1: let the model call the tool -------------------------------
    msgs = [{"role": "user",
             "content": "Search the build logs for worker task records."}]
    r1 = call(url, key, {"model": MODEL, "max_tokens": 256, "system": system,
                         "tools": TOOLS, "messages": msgs})
    tool_use = next((b for b in r1.get("content", [])
                     if isinstance(b, dict) and b.get("type") == "tool_use"), None)
    if not tool_use:
        print("model did not call the tool; aborting")
        print(json.dumps(r1)[:600])
        return 1
    msgs.append({"role": "assistant", "content": r1["content"]})
    msgs.append({"role": "user",
                 "content": [{"type": "tool_result",
                              "tool_use_id": tool_use["id"],
                              "content": payload}]})

    # what actually reached the model on turn 1
    r2 = call(url, key, {"model": MODEL, "max_tokens": 128, "system": system,
                         "tools": TOOLS, "messages": msgs})
    msgs.append({"role": "assistant", "content": text_of(r2) or "Logs retrieved."})

    fwd = forwarded_tool_result(cap, salt)
    turn1_bytes = len(fwd)
    survivors = [t for t in facts if t in fwd]
    print(f"arm={a.arm}  model={MODEL}")
    print(f"turn 1: {len(survivors)}/{len(facts)} log lines survived compression "
          f"({len(fwd)} bytes forwarded of {len(payload)})")
    if not survivors:
        print("nothing survived; cannot probe")
        return 1

    # probe the MIDDLE survivor: not head, not tail, so it is the kind of item
    # stride sampling drops first on re-compression
    probe = survivors[len(survivors) // 2]
    answer = str(facts[probe])
    print(f"probing {probe} (expected {answer}ms), asked every turn\n")

    rows = []
    for t in range(2, a.turns + 2):
        if a.idle_every and (t - 1) % a.idle_every == 0:
            print(f"  ... idling {a.idle_seconds}s to lapse the prompt cache",
                  flush=True)
            time.sleep(a.idle_seconds)
        msgs.append({"role": "user",
                     "content": f"What duration in ms is recorded for {probe}? "
                                f"Answer with the number only."})
        resp = call(url, key, {"model": MODEL, "max_tokens": 64,
                               "system": system, "messages": msgs})
        out = text_of(resp)
        msgs.append({"role": "assistant", "content": out or "..."})

        fwd = forwarded_tool_result(cap, salt)
        retained = sum(1 for x in facts if x in fwd)
        probe_present = probe in fwd
        correct = answer in out
        u = resp.get("usage", {})
        rows.append({
            "turn": t, "retained": retained, "bytes": len(fwd),
            "probe_in_context": probe_present, "correct": correct,
            "cache_read": u.get("cache_read_input_tokens", 0),
            "cache_write": u.get("cache_creation_input_tokens", 0),
            "answer": out.strip()[:60],
        })
        print(f"  turn {t:>2}  retained {retained:>3}  bytes {len(fwd):>6}  "
              f"probe={'yes' if probe_present else 'NO ':<3}  "
              f"correct={'yes' if correct else 'NO ':<3}  "
              f"cache_read={u.get('cache_read_input_tokens', 0):>6}  "
              f"| {out.strip()[:40]}", flush=True)

    out_path = Path(a.out or (REPO / "research" / "data" /
                              f"agent_anthropic_{a.arm}.json"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"arm": a.arm, "model": MODEL, "salt": salt, "probe": probe,
         "expected": answer, "turn1_survivors": len(survivors),
         "n_lines": len(facts), "turn1_bytes": turn1_bytes,
         "idle_every": a.idle_every,
         "idle_seconds": a.idle_seconds, "payload_bytes": len(payload),
         "rows": rows}, indent=2))
    ok = sum(1 for r in rows if r["correct"])
    print(f"\ncorrect {ok}/{len(rows)} turns   "
          f"retained {rows[0]['retained']} -> {rows[-1]['retained']}")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

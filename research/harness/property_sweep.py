"""Multi-turn, cross-handler differential property harness for Headroom.

Headroom's own suite (see research/result-02-existing-eval-suite.md) is
single-turn and single-provider: it measures whether one compression preserves
enough information to answer one question. It therefore cannot express -- let
alone check -- properties that only exist across turns or across providers.

This harness asserts three such properties, on both provider paths, over a
matrix of content types and prompt-cache regimes:

  P1  IDEMPOTENCE
      Re-sending an unchanged tool output must not change what is forwarded.
      compress(compress(x)) == compress(x).

  P2  CROSS-HANDLER EQUIVALENCE
      The same payload under the same cache regime must retain the same amount
      on the Anthropic and OpenAI paths.

  P3  TURN-INDEX INDEPENDENCE
      Retention of an unchanged block must not depend on how many turns have
      elapsed. (Implied by P1; reported separately because it is the property
      an agent actually feels.)

Everything runs against fake upstreams: $0, no API key, deterministic.

Usage:
    python3 research/harness/property_sweep.py                 # full matrix
    python3 research/harness/property_sweep.py --quick         # smaller matrix
    python3 research/harness/property_sweep.py --arm fixed     # with the fix on
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REPRO = REPO / "research" / "repro"
DATA = REPO / "research" / "data"
VENV_BIN = Path("/Users/fahim/Desktop/headroom/.venv-run/bin")

# Stable system-prompt bulk. PrefixTracker.min_cached_tokens defaults to 1024;
# without a realistically large stable prefix the provider-confirmed frozen
# count can never advance and every regime degenerates to "cold".
SYSPAD_BYTES = 20000
PAD = ("You are a meticulous operations assistant. Follow the operator "
       "handbook exactly and cite record identifiers verbatim. ")
PAD = (PAD * (SYSPAD_BYTES // len(PAD) + 1))[:SYSPAD_BYTES]


# --------------------------------------------------------------------------
# Content types. Each returns (payload_string, probe_tokens).
# Retention is measured as: how many probe tokens survive into the forwarded
# request. Probes are unique so substring counting is unambiguous.
# --------------------------------------------------------------------------

def c_json_string_array(n: int, salt: str):
    items = [f"INV-{salt}-{i:04d}" for i in range(n)]
    return json.dumps(items), items


def c_json_number_array(n: int, salt: str):
    base = 700000000 + (hash(salt) % 1000) * 100000
    items = [base + i for i in range(n)]
    return json.dumps(items), [str(x) for x in items]


def c_json_dict_array(n: int, salt: str):
    rows = [{"id": f"REC-{salt}-{i:04d}", "status": "open" if i % 3 else "closed",
             "amount": 100 + i} for i in range(n)]
    return json.dumps(rows), [r["id"] for r in rows]


def c_log_lines(n: int, salt: str):
    lvl = ["INFO", "WARN", "ERROR"]
    lines = [f"2026-08-25 12:{i//60:02d}:{i%60:02d} {lvl[i%3]} "
             f"worker task_{salt}_{i:04d} completed in {10+i}ms"
             for i in range(n)]
    return "\n".join(lines), [f"task_{salt}_{i:04d}" for i in range(n)]


def c_search_results(n: int, salt: str):
    lines = [f"src/mod_{salt}/file_{i:04d}.py:{10+i}: "
             f"def handler_{i:04d}(request):" for i in range(n)]
    return "\n".join(lines), [f"file_{i:04d}.py" for i in range(n)]


def c_plain_text(n: int, salt: str):
    paras = [f"Section {i}. The reconciliation token is TKN{salt}{i:04d} and it "
             f"governs the settlement window for the associated ledger entry."
             for i in range(n)]
    return "\n\n".join(paras), [f"TKN{salt}{i:04d}" for i in range(n)]


CONTENT_TYPES = {
    "json_string_array": c_json_string_array,
    "json_number_array": c_json_number_array,
    "json_dict_array": c_json_dict_array,
    "log_lines": c_log_lines,
    "search_results": c_search_results,
    "plain_text": c_plain_text,
}

# --------------------------------------------------------------------------
# Cache regimes -- how the fake upstream reports prompt-cache reads.
# --------------------------------------------------------------------------

REGIMES = {
    # never reports cache reads -> PrefixTracker stays at 0
    "cold": {"CACHE_READ_FRACTION": "0.0", "MISS_EVERY": "0"},
    # always reports a large cached prefix -> tracker advances every turn
    "warm": {"CACHE_READ_FRACTION": "0.9", "MISS_EVERY": "0"},
    # reports cache reads except every 3rd turn -> simulates TTL lapse
    "intermittent": {"CACHE_READ_FRACTION": "0.9", "MISS_EVERY": "3"},
}

ARMS = {
    "baseline": {},
    "fixed": {"HEADROOM_IDEMPOTENT_COMPRESSION": "1"},
}


# --------------------------------------------------------------------------
# Process management
# --------------------------------------------------------------------------

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port: int, timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


@dataclass
class Stack:
    provider: str
    regime: str
    arm: str
    capture: Path
    proxy_port: int = 0
    up_port: int = 0
    up: subprocess.Popen | None = None
    proxy: subprocess.Popen | None = None
    proxy_log: Path | None = None

    def start(self) -> None:
        self.up_port = free_port()
        self.proxy_port = free_port()
        self.capture.write_text("")

        up_script = ("fake_upstream_openai.py" if self.provider == "openai"
                     else "fake_upstream_cached.py")
        env = dict(os.environ)
        env.update(REGIMES[self.regime])
        env["UPSTREAM_PORT"] = str(self.up_port)
        env["CAPTURE"] = str(self.capture)
        up_log = Path(f"/tmp/ps_up_{self.provider}_{self.regime}_{self.arm}.log")
        self.up = subprocess.Popen(
            [sys.executable, str(REPRO / up_script)],
            env=env, stdout=up_log.open("w"), stderr=subprocess.STDOUT)
        if not wait_port(self.up_port, 30):
            raise RuntimeError(f"upstream failed to start ({up_log})")

        purl = ("--openai-api-url" if self.provider == "openai"
                else "--anthropic-api-url")
        penv = dict(os.environ)
        penv.update(ARMS[self.arm])
        penv["HEADROOM_RATE_LIMIT_ENABLED"] = "false"
        penv["HEADROOM_FROZEN_TRACE"] = "1"
        self.proxy_log = Path(
            f"/tmp/ps_proxy_{self.provider}_{self.regime}_{self.arm}.log")
        self.proxy = subprocess.Popen(
            [str(VENV_BIN / "python"), "-m", "headroom.cli", "proxy",
             "--mode", "token", "--port", str(self.proxy_port),
             purl, f"http://127.0.0.1:{self.up_port}"],
            env=penv, cwd=str(REPO),
            stdout=self.proxy_log.open("w"), stderr=subprocess.STDOUT)
        if not wait_port(self.proxy_port, 90):
            raise RuntimeError(f"proxy failed to start ({self.proxy_log})")
        time.sleep(2)

    def stop(self) -> None:
        for p in (self.proxy, self.up):
            if p and p.poll() is None:
                p.send_signal(signal.SIGTERM)
        time.sleep(1)
        for p in (self.proxy, self.up):
            if p and p.poll() is None:
                p.kill()


# --------------------------------------------------------------------------
# Driving a conversation
# --------------------------------------------------------------------------

def forwarded_block(capture: Path, salt: str, provider: str) -> str:
    """The tool output as actually forwarded upstream, for the given session."""
    rec = None
    for line in capture.read_text().splitlines():
        if line and salt in line:
            rec = json.loads(line)
    if not rec:
        return ""
    body = json.loads(rec["body"])
    if provider == "openai":
        for m in body.get("messages", []):
            if m.get("role") == "tool":
                c = m.get("content")
                return c if isinstance(c, str) else json.dumps(c)
        return ""
    for m in body.get("messages", []):
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    v = b.get("content")
                    return v if isinstance(v, str) else json.dumps(v)
    return ""


def run_conversation(stack: Stack, payload: str, salt: str, turns: int) -> list[dict]:
    """Send `turns` requests that add no new information after the first."""
    provider = stack.provider
    url = (f"http://127.0.0.1:{stack.proxy_port}/v1/chat/completions"
           if provider == "openai"
           else f"http://127.0.0.1:{stack.proxy_port}/v1/messages")
    headers = ({"Content-Type": "application/json",
                "Authorization": "Bearer test"} if provider == "openai"
               else {"Content-Type": "application/json", "x-api-key": "test",
                     "anthropic-version": "2023-06-01"})

    if provider == "openai":
        msgs = [
            {"role": "system", "content": f"Session {salt}. {PAD}"},
            {"role": "user", "content": "Fetch the records."},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "fetch", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": payload},
        ]
    else:
        msgs = [
            {"role": "user", "content": "Fetch the records."},
            {"role": "assistant",
             "content": [{"type": "tool_use", "id": "t1", "name": "fetch",
                          "input": {}}]},
            {"role": "user",
             "content": [{"type": "tool_result", "tool_use_id": "t1",
                          "content": payload},
                         {"type": "text", "text": "Fetch the records."}]},
        ]

    rows: list[dict] = []
    for t in range(1, turns + 1):
        if t > 1:
            msgs.append({"role": "assistant", "content": "Noted."})
            msgs.append({"role": "user",
                         "content": f"Question {t}: summarise the records."})
        if provider == "openai":
            body = {"model": "gpt-4o-mini", "messages": msgs, "max_tokens": 16}
        else:
            body = {"model": "claude-sonnet-4-5-20250929", "max_tokens": 32,
                    "system": f"Session {salt}. {PAD}", "messages": msgs}
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=headers)
        try:
            urllib.request.urlopen(req, timeout=180).read()
        except Exception as e:  # noqa: BLE001
            rows.append({"turn": t, "error": repr(e)})
            break
        out = forwarded_block(stack.capture, salt, provider)
        rows.append({"turn": t, "bytes": len(out), "_out": out})
    return rows


# --------------------------------------------------------------------------
# Property evaluation
# --------------------------------------------------------------------------

@dataclass
class Cell:
    provider: str
    regime: str
    arm: str
    content_type: str
    retention: list[int] = field(default_factory=list)
    nbytes: list[int] = field(default_factory=list)
    payload_bytes: int = 0
    error: str | None = None

    @property
    def compressed(self) -> bool:
        """Did compression fire at all? If not, properties hold vacuously."""
        return bool(self.retention) and self.retention[0] < self.n_probes

    n_probes: int = 0

    def p1_idempotent(self) -> bool | None:
        if self.error or not self.retention or not self.nbytes:
            return None
        return (all(r == self.retention[0] for r in self.retention)
                and all(b == self.nbytes[0] for b in self.nbytes))

    def p3_turn_independent(self) -> bool | None:
        if self.error or not self.nbytes:
            return None
        return all(b == self.nbytes[0] for b in self.nbytes)


def evaluate(stack: Stack, content_type: str, n_items: int, turns: int) -> Cell:
    salt = f"S{int(time.time()*1000)%10**9:09d}{os.getpid()%1000:03d}"
    payload, probes = CONTENT_TYPES[content_type](n_items, salt)
    rows = run_conversation(stack, payload, salt, turns)
    cell = Cell(stack.provider, stack.regime, stack.arm, content_type,
                n_probes=len(probes), payload_bytes=len(payload))
    for r in rows:
        if "error" in r:
            cell.error = r["error"]
            break
        out = r.pop("_out")
        cell.retention.append(sum(1 for p in probes if p in out))
        cell.nbytes.append(r["bytes"])
    return cell


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--items", type=int, default=300)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--arms", default="baseline,fixed")
    ap.add_argument("--providers", default="anthropic,openai")
    ap.add_argument("--regimes", default="cold,warm,intermittent")
    ap.add_argument("--content", default=",".join(CONTENT_TYPES))
    ap.add_argument("--out", default=str(DATA / "property_sweep.json"))
    a = ap.parse_args()

    if a.quick:
        a.turns, a.content = 6, "json_string_array,log_lines"

    providers = a.providers.split(",")
    regimes = a.regimes.split(",")
    arms = a.arms.split(",")
    contents = a.content.split(",")

    DATA.mkdir(parents=True, exist_ok=True)
    cells: list[Cell] = []
    total = len(providers) * len(regimes) * len(arms)
    done = 0

    for provider in providers:
        for regime in regimes:
            for arm in arms:
                done += 1
                print(f"\n[{done}/{total}] {provider} / {regime} / {arm}",
                      flush=True)
                stack = Stack(provider, regime, arm,
                              Path(f"/tmp/ps_cap_{provider}_{regime}_{arm}.jsonl"))
                try:
                    stack.start()
                except Exception as e:  # noqa: BLE001
                    print(f"  STACK FAILED: {e}", flush=True)
                    stack.stop()
                    continue
                try:
                    for ct in contents:
                        cell = evaluate(stack, ct, a.items, a.turns)
                        cells.append(cell)
                        p1 = cell.p1_idempotent()
                        mark = {True: "PASS", False: "FAIL", None: "----"}[p1]
                        series = "->".join(str(x) for x in cell.retention[:1]
                                           + cell.retention[-1:])
                        print(f"  {ct:<20} P1={mark:<5} "
                              f"retained {series:<12} "
                              f"bytes {cell.nbytes[0] if cell.nbytes else '-'}"
                              f"->{cell.nbytes[-1] if cell.nbytes else '-'}"
                              + (f"  ERR {cell.error}" if cell.error else ""),
                              flush=True)
                finally:
                    stack.stop()

    payload = [vars(c) for c in cells]
    Path(a.out).write_text(json.dumps(payload, indent=2))
    print(f"\nwrote {a.out}")
    report(cells)
    return 0


def report(cells: list[Cell]) -> None:
    print("\n" + "=" * 78)
    print("P1 IDEMPOTENCE -- unchanged tool output must forward unchanged bytes")
    print("=" * 78)
    fails = []
    for c in cells:
        r = c.p1_idempotent()
        if r is False:
            fails.append(c)
    if not fails:
        print("  no violations")
    for c in fails:
        print(f"  FAIL {c.provider:<10} {c.regime:<13} {c.arm:<9} "
              f"{c.content_type:<20} {c.retention[0]} -> {c.retention[-1]} "
              f"({c.nbytes[0]} -> {c.nbytes[-1]} bytes)")

    print("\n" + "=" * 78)
    print("P2 CROSS-HANDLER EQUIVALENCE -- same payload, same regime, same arm")
    print("=" * 78)
    idx = {(c.provider, c.regime, c.arm, c.content_type): c for c in cells}
    seen = False
    for (prov, reg, arm, ct), c in idx.items():
        if prov != "anthropic":
            continue
        o = idx.get(("openai", reg, arm, ct))
        if not o or c.error or o.error or not c.retention or not o.retention:
            continue
        if c.retention[-1] != o.retention[-1]:
            seen = True
            print(f"  DIVERGE {reg:<13} {arm:<9} {ct:<20} "
                  f"anthropic={c.retention[-1]:<5} openai={o.retention[-1]}")
    if not seen:
        print("  no divergences")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    checked = [c for c in cells if c.p1_idempotent() is not None]
    print(f"  cells run            : {len(cells)}")
    print(f"  P1 evaluated         : {len(checked)}")
    print(f"  P1 violations        : {len(fails)}")
    errs = [c for c in cells if c.error]
    if errs:
        print(f"  cells with errors    : {len(errs)}")


if __name__ == "__main__":
    sys.exit(main())

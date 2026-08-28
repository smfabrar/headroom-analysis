"""Three-arm study of the compression cache key.

arm content  -- upstream: hash((content, target_ratio))            [baseline]
arm query    -- + full query text
arm anchors  -- + identifier-like tokens from the query only

Multi-turn session: one large tool output, then several turns each asking about
a DIFFERENT interior item. Measures the trade-off the change actually creates:
retention of the asked-about item vs. compression cache hit rate.

Deterministic, no API key.
"""
import json, os, subprocess, sys, time, urllib.request

PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))
N = int(os.environ.get("N", "300"))
ITEMS = [f"INV-2026-{i:04d}" for i in range(1, N + 1)]
TARGET_IDX = [60, 120, 180, 240, 90, 150, 210, 30]
TARGETS = [ITEMS[i] for i in TARGET_IDX]

def tool_result_of(body):
    d = json.loads(body); out = None
    for m in d.get("messages", []):
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    v = b.get("content")
                    out = v if isinstance(v, str) else json.dumps(v)
    return out or ""

def wait(port, tries=40):
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read(); return True
        except Exception: time.sleep(0.5)
    return False

def run_arm(mode, port):
    cap = os.path.abspath(f"research/data/ck_{mode}.jsonl"); open(cap, "w").close()
    subprocess.run(["pkill","-9","-f","headroom.*proxy|fake_upstream"], capture_output=True)
    time.sleep(1.5)
    up = subprocess.Popen([PY, os.path.join(HERE, "fake_upstream.py")],
        env={**os.environ, "CAPTURE": cap}, stdout=open(f"/tmp/ck_{mode}_up.log","w"),
        stderr=subprocess.STDOUT)
    time.sleep(2)
    px = subprocess.Popen([PY,"-m","headroom.cli","proxy","--port",str(port),"--mode","token"],
        env={**os.environ, "ANTHROPIC_TARGET_API_URL":"http://127.0.0.1:8799",
             "HEADROOM_SKIP_UPSTREAM_CHECK":"1","HEADROOM_RATE_LIMIT_ENABLED":"false",
             "HEADROOM_QUERY_AWARE_SCALARS":"1","HEADROOM_CACHE_KEY_MODE":mode},
        stdout=open(f"/tmp/ck_{mode}_proxy.log","w"), stderr=subprocess.STDOUT)
    if not wait(port): print("  proxy failed"); return None

    salt = f"ck{mode}{time.time_ns():019d}"
    msgs = [
        {"role":"user","content":f"Is {TARGETS[0]} in the invoice list?"},
        {"role":"assistant","content":[{"type":"tool_use","id":"t","name":"list_invoices","input":{}}]},
        {"role":"user","content":[
            {"type":"tool_result","tool_use_id":"t","content":json.dumps(ITEMS)},
            {"type":"text","text":f"Is {TARGETS[0]} in the invoice list?"}]},
    ]
    hits = []
    for turn, tgt in enumerate(TARGETS, 1):
        if turn > 1:
            msgs.append({"role":"assistant","content":"Checked."})
            msgs.append({"role":"user","content":f"Now: is {tgt} in that same list?"})
        body = {"model":"claude-sonnet-4-5-20250929","max_tokens":64,
                "system":f"Session {salt}.","messages":msgs}
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/messages",
            data=json.dumps(body).encode(),
            headers={"Content-Type":"application/json","x-api-key":"t",
                     "anthropic-version":"2023-06-01"})
        urllib.request.urlopen(req, timeout=120).read()
        rec = None
        for line in open(cap).read().strip().split("\n"):
            if line and f"Session {salt}." in line: rec = json.loads(line)
        out = tool_result_of(rec["body"])
        kept = [x for x in ITEMS if x in out]
        hits.append(dict(turn=turn, target=tgt, kept=len(kept), target_kept=tgt in out,
                         bytes_out=len(rec["body"])))
    # cache counters from the proxy
    stats = {}
    try:
        stats = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/v1/telemetry", timeout=5).read())
    except Exception: pass
    px.kill(); up.kill()
    return hits, stats

if __name__ == "__main__":
    res = {}
    for mode, port in (("content", 8901), ("query", 8902), ("anchors", 8903)):
        print(f"\n=== HEADROOM_CACHE_KEY_MODE={mode} ===")
        r = run_arm(mode, port)
        if not r: continue
        hits, stats = r; res[mode] = hits
        for h in hits:
            print(f"  turn {h['turn']}  {h['target']}  kept={h['kept']:<4} "
                  f"target_kept={h['target_kept']}")
        got = sum(h["target_kept"] for h in hits)
        print(f"  --> retained {got}/{len(hits)} = {got/len(hits):.0%}"
              f"   mean kept {sum(h['kept'] for h in hits)/len(hits):.1f}"
              f"   mean bytes {sum(h['bytes_out'] for h in hits)/len(hits):.0f}")
    json.dump(res, open("research/data/cache_key_results.json","w"), indent=2)
    print("\n=== SUMMARY ===")
    print(f"{'mode':<9} {'target retained':>16} {'mean items kept':>16} {'mean bytes':>12}")
    for m, h in res.items():
        print(f"{m:<9} {sum(x['target_kept'] for x in h)}/{len(h):<14} "
              f"{sum(x['kept'] for x in h)/len(h):>15.1f} "
              f"{sum(x['bytes_out'] for x in h)/len(h):>12.0f}")

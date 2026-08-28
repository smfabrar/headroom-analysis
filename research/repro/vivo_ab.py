"""In-vivo A/B: does query-aware scalar retention change a real agent's answer?

Same tool-calling agent, same repo, same model, same proxy mode (token).
Only HEADROOM_QUERY_AWARE_SCALARS differs between arms.

Task shape: a membership question over a large grep result -- "does FILE appear
among the matches?". Ground truth is computed locally, so grading is exact and
needs no judge model.
"""
import json, os, subprocess, sys, time, urllib.request

REPO = os.environ["AGENT_REPO"]
PY = sys.executable
HERE = os.path.dirname(os.path.abspath(__file__))

TASK_TMPL = os.environ.get("AB_TASK_TMPL",
    "Search the repo for the pattern retry and tell me whether {t} appears "
    "among the matching files. Answer strictly Yes or No.")

def ground_truth(target, pattern="retry"):
    p = os.path.join(REPO, target)
    if os.environ.get("AB_MODE") == "listing":
        return os.path.exists(p)
    return os.path.exists(p) and pattern in open(p).read()

def wait_health(port, tries=40):
    for _ in range(tries):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2).read()
            return True
        except Exception:
            time.sleep(0.5)
    return False

def start(cmd, env, log):
    return subprocess.Popen(cmd, env={**os.environ, **env},
                            stdout=open(log, "w"), stderr=subprocess.STDOUT)

def run_arm(arm, port, gate, targets):
    cap = os.path.abspath(f"research/data/ab_{arm}.jsonl")
    open(cap, "w").close()
    reqlog = f"/tmp/ab_{arm}_req.log"; open(reqlog, "w").close()
    subprocess.run(["pkill", "-9", "-f", "recording_upstream|headroom.*proxy"],
                   capture_output=True)
    time.sleep(1.5)
    rec = start([PY, os.path.join(HERE, "recording_upstream.py")],
                {"CAPTURE": cap, "REAL_UPSTREAM": "https://api.openai.com",
                 "REC_PORT": "8798"}, f"/tmp/ab_{arm}_rec.log")
    time.sleep(2)
    penv = {"OPENAI_TARGET_API_URL": "http://127.0.0.1:8798",
            "HEADROOM_SKIP_UPSTREAM_CHECK": "1",
            "HEADROOM_RATE_LIMIT_ENABLED": "false"}
    if gate: penv["HEADROOM_QUERY_AWARE_SCALARS"] = "1"
    else: os.environ.pop("HEADROOM_QUERY_AWARE_SCALARS", None)
    prox = start([PY, "-m", "headroom.cli", "proxy", "--port", str(port),
                  "--mode", "token", "--log-file", reqlog, "--log-messages"],
                 penv, f"/tmp/ab_{arm}_proxy.log")
    if not wait_health(port):
        print(f"  !! proxy {port} unhealthy"); return []

    results = []
    for t in targets:
        gt = ground_truth(t)
        env = {"OPENAI_API_BASE": f"http://127.0.0.1:{port}/v1",
               "AGENT_REPO": REPO, "AGENT_MAX_STEPS": "3",
               "AGENT_TASKS": json.dumps([TASK_TMPL.format(t=t)])}
        out = subprocess.run([PY, os.path.join(HERE, "toolcalling_agent.py")],
                             env={**os.environ, **env}, capture_output=True,
                             text=True, timeout=300).stdout
        final = ""
        for line in out.splitlines():
            if "final:" in line: final = line.split("final:", 1)[1].strip()
        said_yes = final.lower().lstrip().startswith("yes")
        # was the target actually in what the model received?
        present = False; n_fwd = None
        for line in open(cap):
            if not line.strip(): continue
            try: body = json.loads(json.loads(line)["body"])
            except Exception: continue
            for m in body.get("messages", []):
                if m.get("role") == "tool":
                    c = m.get("content")
                    if isinstance(c, str):
                        if t in c: present = True
                        try:
                            a = json.loads(c)
                            if isinstance(a, list): n_fwd = len(a)
                        except Exception: pass
        correct = (said_yes == gt)
        results.append(dict(target=t, ground_truth=gt, answer=final[:12],
                            said_yes=said_yes, correct=correct,
                            target_in_context=present, n_forwarded=n_fwd))
        print(f"  {t:<34} gt={str(gt):<5} said={'Yes' if said_yes else 'No ':<4} "
              f"{'OK ' if correct else 'WRONG'}  in_ctx={present}")
        open(cap, "w").close()   # isolate per-task capture
    prox.kill(); rec.kill()
    return results

if __name__ == "__main__":
    targets = json.loads(os.environ["AB_TARGETS"])
    all_res = {}
    for arm, port, gate in (("off", 8891, False), ("on", 8892, True)):
        print(f"\n=== ARM {arm} (query-aware {'ON' if gate else 'OFF'}) ===")
        all_res[arm] = run_arm(arm, port, gate, targets)
    json.dump(all_res, open("research/data/vivo_ab_results.json", "w"), indent=2)
    print("\n=== SUMMARY ===")
    for arm in ("off", "on"):
        r = all_res[arm]
        if not r: continue
        acc = sum(x["correct"] for x in r) / len(r)
        inc = sum(x["target_in_context"] for x in r) / len(r)
        print(f"  {arm:<4} answer accuracy {sum(x['correct'] for x in r)}/{len(r)} = {acc:.0%}"
              f"   target present in context {inc:.0%}")

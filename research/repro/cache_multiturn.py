"""Does the content-keyed cache freeze compression across a multi-turn session?

Realistic shape: an agent pulls ONE large tool output, then the user asks
several different questions about it over successive turns. The tool output is
unchanged, so its cache key is unchanged, so every turn after the first replays
turn 1's compression -- regardless of what is being asked.

Anthropic /v1/messages path, where the scalar-array crusher genuinely runs.
Deterministic, no API key.
"""
import json, os, urllib.request, time

PORT = os.environ.get("PORT", "8900")
CAP = os.environ["CAPTURE"]
N = int(os.environ.get("N", "300"))
ITEMS = [f"INV-2026-{i:04d}" for i in range(1, N + 1)]
# targets deliberately in the interior (not head/tail guaranteed)
TARGETS = [ITEMS[i] for i in (60, 120, 180, 240, 90)]
SESSION = os.environ.get("SESSION", f"s{time.time_ns():019d}")

def tool_result_of(body):
    d = json.loads(body)
    out = None
    for m in d.get("messages", []):
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    v = b.get("content")
                    out = v if isinstance(v, str) else json.dumps(v)
    return out or ""

def send(messages, salt):
    body = {"model": "claude-sonnet-4-5-20250929", "max_tokens": 64,
            "system": f"Session {salt}.", "messages": messages}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/messages",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-api-key": "t",
                 "anthropic-version": "2023-06-01"})
    urllib.request.urlopen(req, timeout=120).read()
    hit = None
    for line in open(CAP).read().strip().split("\n"):
        if line and f"Session {salt}." in line:
            hit = json.loads(line)
    return tool_result_of(hit["body"])

# Turn 1: tool call returns the array, user asks about TARGETS[0]
msgs = [
    {"role": "user", "content": f"Is {TARGETS[0]} in the invoice list?"},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "t",
                                       "name": "list_invoices", "input": {}}]},
    {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": json.dumps(ITEMS)},
        {"type": "text", "text": f"Is {TARGETS[0]} in the invoice list?"}]},
]

print(f"N={len(ITEMS)}  session={SESSION}")
print(f"{'turn':>4} {'asked about':<16} {'kept':>5} {'target kept':>12} {'kept-set changed':>18}")
print("-" * 62)
prev = None
for turn, tgt in enumerate(TARGETS, 1):
    if turn > 1:
        msgs.append({"role": "assistant", "content": "Checked."})
        msgs.append({"role": "user", "content": f"Now: is {tgt} in that same list?"})
    out = send(msgs, SESSION)
    kept = [x for x in ITEMS if x in out]
    changed = "-" if prev is None else str(tuple(kept) != prev)
    print(f"{turn:>4} {tgt:<16} {len(kept):>5} {str(tgt in out):>12} {changed:>18}")
    prev = tuple(kept)
print("\nkept sample:", kept[:8], "...")

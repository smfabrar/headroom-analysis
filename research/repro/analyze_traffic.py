"""What shapes do real agent tool outputs actually have?

Scans captured forwarded bodies and reports where JSON arrays occur, whether
they are scalar or dict, and how large -- the gating question for
improvement-01 (see PROPOSAL.md kill criteria).
"""
import json, sys, collections

path = sys.argv[1]
rows = [json.loads(l) for l in open(path) if l.strip()]
print(f"captured requests: {len(rows)}\n")

roles = collections.Counter()
tool_msgs = 0
arrays = []          # (where, kind, n, sample)
big_text = []

def scan_json(obj, where, depth=0):
    if depth > 6: return
    if isinstance(obj, list) and obj:
        kinds = {type(x).__name__ for x in obj}
        kind = ("scalar" if kinds <= {"str", "int", "float", "bool"}
                else "dict" if kinds == {"dict"} else "mixed")
        arrays.append((where, kind, len(obj), str(obj[0])[:60]))
        for x in obj[:3]: scan_json(x, where, depth+1)
    elif isinstance(obj, dict):
        for k, v in obj.items(): scan_json(v, f"{where}.{k}", depth+1)

for r in rows:
    try: body = json.loads(r["body"])
    except Exception: continue
    for m in body.get("messages", []):
        roles[m.get("role", "?")] += 1
        if m.get("role") == "tool" or m.get("tool_call_id"):
            tool_msgs += 1
        c = m.get("content")
        texts = []
        if isinstance(c, str): texts.append(("content", c))
        elif isinstance(c, list):
            for b in c:
                if isinstance(b, dict):
                    if b.get("type") in ("tool_result", "text"):
                        v = b.get("content", b.get("text", ""))
                        texts.append((b.get("type"), v if isinstance(v, str) else json.dumps(v)))
        for label, t in texts:
            if not isinstance(t, str): continue
            if len(t) > 2000: big_text.append((label, len(t)))
            s = t.strip()
            if s.startswith(("[", "{")):
                try: scan_json(json.loads(s), label)
                except Exception: pass

print("message roles:", dict(roles))
print(f"tool-role / tool_call messages: {tool_msgs}")
print(f"text blocks > 2000 chars: {len(big_text)}"
      f"  (max {max([n for _,n in big_text], default=0)})")

print(f"\nJSON arrays found: {len(arrays)}")
if arrays:
    by = collections.Counter((k, "n>=5" if n >= 5 else "n<5") for _, k, n, _ in arrays)
    for (k, sz), c in by.most_common():
        print(f"  {k:<7} {sz:<6} x{c}")
    print("\n  largest arrays:")
    for w, k, n, s in sorted(arrays, key=lambda a: -a[2])[:8]:
        print(f"    n={n:<5} {k:<7} at {w[:40]:<40} e.g. {s[:40]}")

print("\nVERDICT for improvement-01:")
scalars_big = [a for a in arrays if a[1] == "scalar" and a[2] >= 5]
print(f"  scalar arrays with n>=5 (min_items_to_analyze): {len(scalars_big)}")
print("  -> scalar-array crush path would fire" if scalars_big
      else "  -> scalar-array crush path would NOT fire in this traffic")

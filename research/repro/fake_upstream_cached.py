"""Fake Anthropic upstream that REPORTS PROMPT-CACHE READS.

fake_upstream.py returns usage without `cache_read_input_tokens`, which leaves
the Anthropic handler's `prefix_tracker.frozen_message_count` at 0. Since that
handler clamps its freeze boundary with
    frozen_message_count = min(frozen_message_count, cache_frozen_count)
a tracker stuck at 0 keeps the whole conversation mutable. This variant reports
a realistic cached prefix so the freeze boundary can actually advance -- the
control for whether the observed decay is an artefact of the test rig.
"""
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = os.environ.get("CAPTURE", "/tmp/captured.jsonl")
# fraction of input tokens to report as cache reads
FRAC = float(os.environ.get("CACHE_READ_FRACTION", "0.9"))
# Report a cache MISS (no cache_read_input_tokens) on every Nth request, to
# simulate the prompt cache lapsing past its ~5min TTL during an idle agent.
MISS_EVERY = int(os.environ.get("MISS_EVERY", "0"))
_seen = {"n": 0}

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        with open(OUT, "a") as f:
            f.write(json.dumps({"path": self.path,
                                "body": raw.decode("utf-8", "replace")}) + "\n")
        approx_in = max(10, len(raw) // 4)
        _seen["n"] += 1
        miss = MISS_EVERY > 0 and _seen["n"] % MISS_EVERY == 0
        cached = 0 if miss else int(approx_in * FRAC)
        resp = json.dumps({
            "id": "msg_fake", "type": "message", "role": "assistant",
            "model": "claude-sonnet-4-5-20250929",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": approx_in - cached,
                "output_tokens": 2,
                "cache_read_input_tokens": cached,
                "cache_creation_input_tokens": 0,
            },
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Length","0"); self.end_headers()
    def log_message(self, *a): pass

PORT = int(os.environ.get("UPSTREAM_PORT", "8799"))
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

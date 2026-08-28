"""Fake OpenAI /v1/chat/completions upstream: records the exact forwarded body.

Mirror of fake_upstream.py for the OpenAI handler path, so the re-compression
decay protocol can be run against both providers with the same rig.
"""
import json, os, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = os.environ.get("CAPTURE", "/tmp/captured_openai.jsonl")
# Fraction of prompt tokens reported as prompt-cache reads
# (usage.prompt_tokens_details.cached_tokens -- what the OpenAI handler reads,
# see handlers/openai.py:1502). MISS_EVERY simulates the cache lapsing past its
# TTL on every Nth request.
FRAC = float(os.environ.get("CACHE_READ_FRACTION", "0.0"))
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
            "id": "chatcmpl-fake", "object": "chat.completion",
            "created": int(time.time()), "model": "gpt-4o-mini",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": approx_in, "completion_tokens": 2,
                      "total_tokens": approx_in + 2,
                      "prompt_tokens_details": {"cached_tokens": cached}},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)
    def do_HEAD(self): self.send_response(200); self.end_headers()
    def do_GET(self): self.send_response(200); self.end_headers()
    def log_message(self, *a): pass

PORT = int(os.environ.get("UPSTREAM_PORT", "8798"))
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()

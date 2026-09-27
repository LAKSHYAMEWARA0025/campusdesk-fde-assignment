"""
Mock "CampusDesk Student Portal" REST API (standard library only).

Serves ticket interactions (student follow-ups, info requests, agent replies)
with pagination and realistic flakiness, like a real SaaS API:

  GET /api/v1/health
  GET /api/v1/interactions?page=1&page_size=200
      -> {"page", "page_size", "total_records", "total_pages", "last_synced_at", "data": [...]}

Flakiness (seeded, so every run behaves the same):
  ~15% of requests -> HTTP 500
  ~7%  of requests -> HTTP 429 with a Retry-After header

Run:  python api/mock_portal_api.py [--port 8765] [--mode normal|outage]
"""
from __future__ import annotations

import argparse
import json
import math
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DATA = Path(__file__).resolve().parents[1] / "source_systems" / "portal_api_data.json"


def build_handler(store: dict, mode: str, seed: int):
    rnd = random.Random(seed)
    records = store["interactions"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def _send(self, code: int, body: dict, headers: dict | None = None):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/api/v1/health":
                return self._send(200, {"status": "ok" if mode == "normal" else "degraded"})
            if url.path != "/api/v1/interactions":
                return self._send(404, {"error": "not found"})
            if mode == "outage":
                return self._send(503, {"error": "service unavailable"})
            r = rnd.random()
            if r < 0.15:
                return self._send(500, {"error": "internal server error"})
            if r < 0.22:
                return self._send(429, {"error": "rate limited"}, {"Retry-After": "1"})
            q = parse_qs(url.query)
            try:
                page = int(q.get("page", ["1"])[0])
                size = min(int(q.get("page_size", ["200"])[0]), 500)
            except ValueError:
                return self._send(400, {"error": "page and page_size must be integers"})
            total_pages = max(1, math.ceil(len(records) / size))
            chunk = records[(page - 1) * size: page * size]
            return self._send(200, {"page": page, "page_size": size, "total_records": len(records),
                                    "total_pages": total_pages, "last_synced_at": store["last_synced_at"],
                                    "data": chunk})

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--mode", choices=["normal", "outage"], default="normal")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    store = json.loads(DATA.read_text())
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), build_handler(store, args.mode, args.seed))
    print(f"Portal API ({args.mode}) on http://127.0.0.1:{args.port}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

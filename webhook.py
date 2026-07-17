#!/usr/bin/env python3
"""A serverless-style webhook bot — the push alternative to `bot.py`'s poll loop.

The server POSTs to this handler when it is your turn, and the HTTP response body is your move.
The handler is stateless: it needs only the per-bot webhook secret (never a token), so it drops
straight into a cloud function.

Two steps to run it:

1. Deploy this handler at a public HTTPS URL, then register it once (needs a *registered* bot
   token, since webhooks are a registered-identity feature):

       DICECHESS_TOKEN=<registered-token> python register.py https://your-url/

   That prints the signing secret.

2. Run the handler with that secret:

       DICECHESS_WEBHOOK_SECRET=<secret> python webhook.py   # listens on :8080 (PORT to override)

For local testing, expose it with a tunnel (e.g. `cloudflared tunnel --url http://localhost:8080`)
and register the tunnel URL. To deploy to AWS Lambda / Cloudflare Workers / Azure Functions,
reuse `dicechess.webhook.handle_delivery` from your platform's request handler — it is pure.
"""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bot import choose_move  # reuse the exact same strategy as the poll-only bot
from dicechess.webhook import handle_delivery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("webhook")

SECRET = os.environ.get("DICECHESS_WEBHOOK_SECRET")
PORT = int(os.environ.get("PORT", "8080"))


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode()
        try:
            status, payload = handle_delivery(self.headers, raw, SECRET or "", choose_move)
        except Exception as e:  # noqa: BLE001 — never 500 the server; let the clock decide
            log.warning("delivery error: %s", e)
            status, payload = 400, {"error": "bad request"}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass  # quiet the default per-request stderr spam


def main() -> None:
    if not SECRET:
        raise SystemExit("set DICECHESS_WEBHOOK_SECRET (printed by register.py) before starting")
    log.info("webhook handler listening on :%d", PORT)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("stopped")

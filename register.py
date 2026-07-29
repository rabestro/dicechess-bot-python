#!/usr/bin/env python3
"""Register a deployed webhook URL and print its signing secret.

    DICECHESS_TOKEN=<registered-token> python register.py https://your-url/

Webhooks are a registered-identity feature, so this needs a durable token (not an anonymous
one). The URL must already be serving `webhook.py` — the server performs an ownership handshake
against it during registration. The printed secret becomes the handler's DICECHESS_WEBHOOK_SECRET.
"""

import os
import sys

from dicechess import BotClient


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: DICECHESS_TOKEN=<token> python register.py <https-url>")
    token = os.environ.get("DICECHESS_TOKEN")
    if not token:
        raise SystemExit("set DICECHESS_TOKEN to a registered bot's token (anon bots can't register webhooks)")

    client = BotClient(base_url=os.environ.get("DICECHESS_BASE_URL", BotClient().base_url), token=token)
    result = client.register_webhook(sys.argv[1])
    print(f"registered {result['url']}")
    print(f"DICECHESS_WEBHOOK_SECRET={result['secret']}")


if __name__ == "__main__":
    main()

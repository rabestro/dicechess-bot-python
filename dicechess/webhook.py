"""Webhook delivery: signature verification and the turn handler.

The push alternative to polling. Once you register an HTTPS callback (see
``BotClient.register_webhook``), the server POSTs to it when it is your turn and **your HTTP
response body is the move**. This module is transport-only and stateless — it needs just the
per-bot ``secret`` to authenticate deliveries, never a token.

The one delivery you cannot authenticate is the registration handshake
(``{"type":"verification"}``): the secret is disclosed only after it succeeds, so the handler
echoes that nonce unconditionally (leaking the nonce is harmless; no game action follows).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.request
from typing import Any, Callable, Mapping

from .client import DEFAULT_BASE_URL, USER_AGENT

SIGNATURE_HEADER = "X-DiceChess-Signature"
TIMESTAMP_HEADER = "X-DiceChess-Timestamp"
MAX_SKEW_SECONDS = 300  # ±5 minutes — the documented replay window


def verify_signature(secret: str, timestamp: str | None, raw_body: str, signature: str | None) -> bool:
    """True iff ``signature`` is ``HMAC-SHA256(secret, "<timestamp>.<raw_body>")`` and fresh."""
    if not timestamp or not signature:
        return False
    try:
        skew = abs(time.time() - int(timestamp))
    except ValueError:
        return False
    if skew > MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.{raw_body}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup (works for dicts and http.server's message object)."""
    getter = getattr(headers, "get", None)
    if getter and headers.__class__.__name__ == "HTTPMessage":
        return headers.get(name)  # already case-insensitive
    lowered = {k.lower(): v for k, v in dict(headers).items()}
    return lowered.get(name.lower())


def handle_delivery(
    headers: Mapping[str, str],
    raw_body: str,
    secret: str,
    choose_move: Callable[[dict], list[str]],
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[int, dict[str, Any]]:
    """Turn one webhook POST into ``(status_code, response_body)``.

    - ``{"type":"verification"}`` → ``(200, {"nonce": <echo>})`` (the ownership handshake).
    - ``{"type":"yourTurn", ...}`` with a valid signature → ``(200, {"moves": [...]})``.
    - a bad or stale signature → ``(401, {"error": ...})`` (submit nothing; your clock runs).
    """
    envelope = json.loads(raw_body)
    if envelope.get("type") == "verification":
        return 200, {"nonce": envelope.get("nonce")}

    if not verify_signature(secret, _header(headers, TIMESTAMP_HEADER), raw_body, _header(headers, SIGNATURE_HEADER)):
        return 401, {"error": "invalid signature"}

    state = envelope.get("state") or {}
    tree = state.get("legalMoves")
    if tree is None:  # inline cap exceeded — fetch the full (public) tree
        tree = _fetch_legal_moves(base_url, envelope["gameId"])
    return 200, {"moves": choose_move(tree or {})}


def _fetch_legal_moves(base_url: str, game_id: str) -> dict:
    req = urllib.request.Request(f"{base_url}/games/{game_id}/moves", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode()).get("legalMoves") or {}

"""Thin, dependency-free transport client for the Dice Chess Bot API.

Standard library only (``urllib``) — copy this package into any project and run.
It wraps auth, the REST endpoints, and the resilience patterns a real bot needs
(retry with backoff, ``Retry-After`` handling, and a hook to re-mint an anonymous
token on ``401``). Game logic stays out of here: your bot picks moves; this client
just moves bytes.

Full API reference: https://bots.jc.id.lv/
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("dicechess")

DEFAULT_BASE_URL = "https://play-api.jc.id.lv"

# A descriptive User-Agent. The platform sits behind a CDN whose default bot rules
# reject the stock ``Python-urllib/x.y`` signature (Cloudflare error 1010), so every
# request must identify itself — real clients (curl, browsers) already do.
USER_AGENT = "dicechess-bot-python/1.0 (+https://github.com/rabestro/dicechess-bot-python)"


class ApiError(Exception):
    """A non-retryable HTTP error (4xx other than 401/429)."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class BotClient:
    """A minimal client for one bot identity.

    :param base_url: platform base URL.
    :param token: an existing Bearer token, or ``None`` to mint an anonymous one.
    :param on_unauthorized: called with the client when a request gets ``401`` so a
        bot can refresh its token (the default re-mints an anonymous token).
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        on_unauthorized: Callable[[BotClient], None] | None = None,
        max_retries: int = 5,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.max_retries = max_retries
        self._on_unauthorized = on_unauthorized

    # ── identity ─────────────────────────────────────────────────────────────

    def mint_anon(self, name: str | None = None) -> dict:
        """Mint an anonymous token and adopt it. No auth required."""
        query = f"?name={urllib.parse.quote(name)}" if name else ""
        data = self._request("POST", f"/bot/anon{query}", auth=False)
        self.token = data["token"]
        log.info("minted anonymous identity %s", data.get("id"))
        return data

    def account(self) -> dict:
        return self._request("GET", "/bot/account")

    # ── challenges & games ────────────────────────────────────────────────────

    def challenge(self, team: str, name: str, time_control: dict | None = None) -> dict:
        """Challenge another bot. Defaults to an unlimited-time game vs the target."""
        body = {"team": team, "name": name, "timeControl": time_control or {"Unlimited": {}}}
        return self._request("POST", "/bot/challenge", body=body)

    def my_games(self) -> list[dict]:
        """Every live game this bot is seated in (the poll-only discovery + recovery path)."""
        return self._request("GET", "/bot/games").get("games", [])

    def legal_moves(self, game_id: str) -> dict:
        """The full legal-move tree for the pending roll (public; no auth needed)."""
        return self._request("GET", f"/games/{game_id}/moves", auth=False)

    def snapshot(self, game_id: str) -> dict:
        """The public single-game snapshot (also carries the dice reveal once revealed)."""
        return self._request("GET", f"/games/{game_id}", auth=False)

    def submit_seed(self, game_id: str, seed: str) -> None:
        """Contribute this seat's provably-fair dice entropy (fire-and-forget)."""
        self._request("POST", f"/bot/game/{game_id}/seed", body={"seed": seed})

    def submit_move(self, game_id: str, moves: list[str]) -> dict:
        """Submit a turn's micro-moves (one per rolled die). Returns the synchronous verdict."""
        return self._request("POST", f"/bot/game/{game_id}/move", body={"moves": moves})

    def resign(self, game_id: str) -> None:
        self._request("POST", f"/bot/game/{game_id}/resign")

    # ── webhook registration ────────────────────────────────────────────────

    def register_webhook(self, url: str) -> dict:
        """Register an HTTPS callback and return ``{"url", "secret"}``.

        The server runs an ownership handshake first (it POSTs a nonce to ``url``, which your
        deployed handler must echo — see ``dicechess.webhook``). Registered bots only; the
        ``secret`` is shown exactly once, so store it as the handler's ``DICECHESS_WEBHOOK_SECRET``.
        """
        return self._request("POST", "/bot/webhook", body={"url": url})

    # ── transport ──────────────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: Any = None, auth: bool = True) -> dict:
        url = f"{self.base_url}{path}"
        payload = json.dumps(body).encode() if body is not None else None
        attempt = 0
        while True:
            attempt += 1
            req = urllib.request.Request(url, data=payload, method=method)
            req.add_header("User-Agent", USER_AGENT)
            if payload is not None:
                req.add_header("Content-Type", "application/json")
            if auth and self.token:
                req.add_header("Authorization", f"Bearer {self.token}")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    text = resp.read().decode()
                    return json.loads(text) if text else {}
            except urllib.error.HTTPError as e:
                status = e.code
                detail = e.read().decode(errors="replace")
                if status == 401 and self._on_unauthorized and attempt <= self.max_retries:
                    log.warning("401 Unauthorized — refreshing token")
                    self._on_unauthorized(self)
                    continue
                if status == 429 and attempt <= self.max_retries:
                    delay = float(e.headers.get("Retry-After", self._backoff(attempt)))
                    log.warning("429 Too Many Requests — retrying in %.1fs", delay)
                    time.sleep(delay)
                    continue
                if 500 <= status < 600 and attempt <= self.max_retries:
                    delay = self._backoff(attempt)
                    log.warning("HTTP %d — retrying in %.1fs", status, delay)
                    time.sleep(delay)
                    continue
                raise ApiError(status, detail) from e
            except urllib.error.URLError as e:
                if attempt <= self.max_retries:
                    delay = self._backoff(attempt)
                    log.warning("network error %s — retrying in %.1fs", e.reason, delay)
                    time.sleep(delay)
                    continue
                raise

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential backoff capped at 30s: 1, 2, 4, 8, 16, 30, 30 …"""
        return min(2.0 ** (attempt - 1), 30.0)

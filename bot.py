#!/usr/bin/env python3
"""A complete, runnable Dice Chess bot — poll-only, dependency-free.

It mints an anonymous identity, challenges the house sparring bot, and plays full
games by walking the legal-move tree the server publishes each turn. **You never
implement a single rule of the variant** — the legal moves arrive on the wire.

Make it your own by editing ``choose_move`` (the only decision the bot makes).
Everything else — auth, discovery, the activity loop, resilience — is transport
you can leave alone.

Run it:

    python bot.py                      # anonymous, vs house/greedy, forever
    DICECHESS_TOKEN=... python bot.py  # as a registered identity

Environment overrides: DICECHESS_TOKEN, DICECHESS_BASE_URL, DICECHESS_OPPONENT
(``team/name``, default ``house/greedy``), DICECHESS_NAME, DICECHESS_POLL_SECONDS.
"""

from __future__ import annotations

import logging
import os
import random
import secrets
import time

from dicechess import BotClient, DEFAULT_BASE_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")


def choose_move(legal_moves: dict) -> list[str]:
    """Pick one complete legal turn from the prefix tree of UCI micro-moves.

    Each key is a micro-move; its value is the tree of legal continuations. A node
    with no children (``{}``) is a complete turn. This baseline walks a uniformly
    random root-to-leaf path — replace it with your own strategy.

    Returns the chosen path as a list of moves, or ``[]`` when the roll has no legal
    move (a forced pass; the server handles it and you submit nothing).
    """
    path: list[str] = []
    node = legal_moves
    while node:
        move = random.choice(list(node.keys()))
        path.append(move)
        node = node[move]
    return path


def play_turn(client: BotClient, game: dict, seeded: set[str]) -> None:
    game_id = game["gameId"]

    # Contribute this seat's provably-fair dice entropy, once per game.
    if game_id not in seeded:
        try:
            client.submit_seed(game_id, secrets.token_hex(16))
        except Exception as e:  # noqa: BLE001 — seeding is best-effort
            log.debug("seed submit skipped for %s: %s", game_id, e)
        seeded.add(game_id)

    tree = client.legal_moves(game_id).get("legalMoves") or {}
    moves = choose_move(tree)
    if not moves:
        return  # forced pass — the server auto-passes
    verdict = client.submit_move(game_id, moves)
    if verdict.get("applied"):
        log.info("game %s: played %s (v%s)", game_id[:8], " ".join(moves), verdict.get("version"))
    else:
        # Stale roll (someone/something moved first) — the next poll re-reads the position.
        log.info("game %s: move refused (%s)", game_id[:8], verdict.get("reason"))


def main() -> None:
    base_url = os.environ.get("DICECHESS_BASE_URL", DEFAULT_BASE_URL)
    token = os.environ.get("DICECHESS_TOKEN")
    opponent = os.environ.get("DICECHESS_OPPONENT", "house/greedy")
    name = os.environ.get("DICECHESS_NAME", "python-starter")
    poll_seconds = float(os.environ.get("DICECHESS_POLL_SECONDS", "3"))
    opp_team, opp_name = opponent.split("/", 1)

    def remint(c: BotClient) -> None:
        c.mint_anon(name)

    client = BotClient(base_url=base_url, token=token, on_unauthorized=remint)
    if not client.token:
        client.mint_anon(name)  # anonymous: perfect for trying things out

    seeded: set[str] = set()
    log.info("bot ready — challenging %s and playing forever (Ctrl-C to stop)", opponent)

    while True:
        try:
            games = client.my_games()
            if not games:
                # Activity loop: no live game → offer another challenge and wait for it.
                client.challenge(opp_team, opp_name)
                time.sleep(poll_seconds)
                continue
            for game in games:
                if game.get("dicePending") and game.get("activeSeat") == game.get("seat"):
                    play_turn(client, game, seeded)
        except Exception as e:  # noqa: BLE001 — keep the loop alive; transport already retried
            log.warning("loop error (continuing): %s", e)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("stopped")

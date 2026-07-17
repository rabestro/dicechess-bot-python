"""Hermetic tests for the webhook handler — no network, no live server.

The signature is computed exactly as the server does — HMAC-SHA256(secret, "<ts>.<body>") —
so a passing test proves the handler would accept a genuine delivery and reject a forged one.
"""

import hashlib
import hmac
import json
import time
import unittest

from bot import choose_move
from dicechess.webhook import SIGNATURE_HEADER, TIMESTAMP_HEADER, handle_delivery, verify_signature

SECRET = "test-secret"


def sign(secret: str, timestamp: str, body: str) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()


class VerifySignature(unittest.TestCase):
    def test_valid_signature_passes(self) -> None:
        ts, body = str(int(time.time())), '{"hello":true}'
        self.assertTrue(verify_signature(SECRET, ts, body, sign(SECRET, ts, body)))

    def test_tampered_body_fails(self) -> None:
        ts, body = str(int(time.time())), '{"hello":true}'
        sig = sign(SECRET, ts, body)
        self.assertFalse(verify_signature(SECRET, ts, '{"hello":false}', sig))

    def test_stale_timestamp_fails(self) -> None:
        ts, body = str(int(time.time()) - 3600), '{"hello":true}'
        self.assertFalse(verify_signature(SECRET, ts, body, sign(SECRET, ts, body)))

    def test_missing_pieces_fail(self) -> None:
        self.assertFalse(verify_signature(SECRET, None, "x", "y"))
        self.assertFalse(verify_signature(SECRET, "not-a-number", "x", "y"))


class HandleDelivery(unittest.TestCase):
    def test_verification_echoes_nonce(self) -> None:
        raw = json.dumps({"type": "verification", "nonce": "abc123"})
        status, resp = handle_delivery({}, raw, SECRET, choose_move)
        self.assertEqual(status, 200)
        self.assertEqual(resp, {"nonce": "abc123"})

    def test_signed_turn_returns_a_legal_path(self) -> None:
        tree = {"e2e4": {"g1f3": {}, "b1c3": {}}, "d2d4": {"d4d5": {}}}
        raw = json.dumps({"type": "yourTurn", "gameId": "g1", "seat": "White", "state": {"legalMoves": tree}})
        ts = str(int(time.time()))
        headers = {TIMESTAMP_HEADER: ts, SIGNATURE_HEADER: sign(SECRET, ts, raw)}
        status, resp = handle_delivery(headers, raw, SECRET, choose_move)
        self.assertEqual(status, 200)
        # The returned path must be a real root-to-leaf walk of the tree.
        node = tree
        for move in resp["moves"]:
            self.assertIn(move, node)
            node = node[move]
        self.assertEqual(node, {}, "path must end at a leaf (a complete turn)")

    def test_bad_signature_is_rejected(self) -> None:
        raw = json.dumps({"type": "yourTurn", "gameId": "g1", "seat": "White", "state": {"legalMoves": {}}})
        headers = {TIMESTAMP_HEADER: str(int(time.time())), SIGNATURE_HEADER: "deadbeef"}
        status, _ = handle_delivery(headers, raw, SECRET, choose_move)
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()

"""Dice Chess bot starter — a thin, dependency-free client and a runnable poll-only bot.

See https://rabestro.github.io/dicechess-play-api/ for the full API reference.
"""

from .client import ApiError, BotClient, DEFAULT_BASE_URL

__all__ = ["ApiError", "BotClient", "DEFAULT_BASE_URL"]

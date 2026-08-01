"""Dice Chess bot starter — a thin, dependency-free client and a runnable poll-only bot.

See https://bots.jc.id.lv/ for the full API reference.
"""

from .client import DEFAULT_BASE_URL, ApiError, BotClient

__all__ = ["DEFAULT_BASE_URL", "ApiError", "BotClient"]

"""Entrypoint — loads strategy, configures privacy-safe logging, starts the bot."""

import logging
import sys

import httpx
from signalbot import SignalBot

from bot.commands import RateLimiter, ReactCommand
from bot.config import settings
from bot.db import GristClient
from bot.loader import load_strategy


def _configure_logging() -> None:
    """
    Privacy-critical: suppress all loggers that could leak message content,
    query data, or credentials into Docker logs.
    """
    # signalbot logs raw message envelopes (phone numbers, message text)
    # at INFO level. Suppress to prevent accidental PII leaks.
    logging.getLogger("signalbot").setLevel(logging.WARNING)

    # httpx/httpcore log full HTTP requests at DEBUG level, including
    # Authorization headers (API key) and request bodies (SQL + args).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Our own logger — operational events only, never message content.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _install_exception_handler() -> None:
    """
    Privacy-critical: prevent unhandled exceptions from printing tracebacks
    that contain message text, SQL queries, API keys, or query results as
    local variables.
    """

    def _handler(exc_type, exc_value, exc_tb):
        logging.getLogger("bot").error(
            "Unhandled %s: %s (traceback suppressed for privacy)",
            exc_type.__name__,
            exc_value,
        )

    sys.excepthook = _handler


def _resolve_bot_uuid(signal_service_url: str, phone_number: str) -> str:
    """Resolve the bot's UUID by querying signal-cli-rest-api.

    Tries /v1/accounts first (may return dicts with uuid or plain strings).
    Falls back to /v1/identities/{number} which returns identity objects
    including the bot's own UUID as the first entry.
    """
    log = logging.getLogger("bot")

    # First, check if the phone number is registered
    url = f"http://{signal_service_url}/v1/accounts"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    accounts = resp.json()
    found = False
    for acct in accounts:
        if isinstance(acct, str) and acct == phone_number:
            found = True
            break
        elif isinstance(acct, dict) and acct.get("number") == phone_number:
            return acct["uuid"]
    if not found:
        raise RuntimeError(
            "Could not resolve bot UUID — phone number not found in signal-api accounts"
        )

    # /v1/accounts returned strings — fetch UUID from identities endpoint.
    # The first entry is the bot's own identity.
    try:
        resp = httpx.get(
            f"http://{signal_service_url}/v1/identities/{phone_number}",
            timeout=30,
        )
        resp.raise_for_status()
        identities = resp.json()
        if identities and isinstance(identities[0], dict):
            uuid = identities[0].get("uuid")
            if uuid:
                return uuid
    except Exception:
        log.warning("Could not fetch UUID from identities endpoint")

    # Last resort: use the phone number itself as the identifier.
    # @-mention filtering will still work if Signal uses phone numbers
    # in the mention UUID field (unlikely but harmless fallback).
    log.warning("Using phone number as bot identifier — @-mention filtering may not work")
    return phone_number


def main():
    _configure_logging()
    _install_exception_handler()

    log = logging.getLogger("bot")
    log.info("Loading strategy from %s", settings.STRATEGY_PATH)

    # Load .yaml or .py based on file extension
    strategy = load_strategy(settings.STRATEGY_PATH)

    # Resolve the bot's UUID for @-mention filtering in group chats
    bot_uuid = _resolve_bot_uuid(
        settings.SIGNAL_SERVICE_URL, settings.SIGNAL_PHONE_NUMBER
    )
    log.info("Bot UUID resolved")

    bot = SignalBot(
        {
            "signal_service": settings.SIGNAL_SERVICE_URL,
            "phone_number": settings.SIGNAL_PHONE_NUMBER,
        }
    )

    db = GristClient(
        api_url=settings.GRIST_API_URL,
        api_key=settings.GRIST_API_KEY,
        doc_id=settings.GRIST_DOC_ID,
    )

    rate_limiter = RateLimiter(
        max_messages=settings.RATE_LIMIT_MAX,
        window_seconds=settings.RATE_LIMIT_WINDOW,
    )
    log.info(
        "Rate limiting: %d messages per %d seconds",
        settings.RATE_LIMIT_MAX,
        settings.RATE_LIMIT_WINDOW,
    )

    bot.register(
        ReactCommand(
            db=db,
            strategy=strategy,
            bot_uuid=bot_uuid,
            rate_limiter=rate_limiter,
        )
    )

    log.info("Bot starting")
    bot.start()


if __name__ == "__main__":
    main()

"""Signal command handler — wires the strategy to the message loop."""

import logging
import time

from signalbot import Command, Context
from thefuzz import fuzz, process

from bot.db import GristClient

logger = logging.getLogger(__name__)


class RateLimiter:
    """In-memory per-sender sliding window rate limiter.

    Tracks message timestamps by sender UUID. A sender is rate-limited when
    they exceed ``max_messages`` within a rolling ``window_seconds`` period.

    Privacy: only UUIDs are stored in memory — never phone numbers, display
    names, or message content. Old entries are pruned on every check.
    """

    def __init__(self, max_messages: int, window_seconds: int) -> None:
        self.max_messages = max_messages
        self.window_seconds = window_seconds
        self._timestamps: dict[str, list[float]] = {}

    def is_allowed(self, sender_uuid: str) -> bool:
        """Return True if the sender is within their rate limit."""
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Get or create timestamp list, prune expired entries
        timestamps = self._timestamps.get(sender_uuid, [])
        timestamps = [t for t in timestamps if t > cutoff]

        if len(timestamps) >= self.max_messages:
            self._timestamps[sender_uuid] = timestamps
            return False

        timestamps.append(now)
        self._timestamps[sender_uuid] = timestamps
        return True


class ReactCommand(Command):
    """Process every incoming message through the strategy pipeline."""

    def __init__(
        self,
        db: GristClient,
        strategy,
        bot_uuid: str,
        rate_limiter: RateLimiter | None = None,
        identity_client=None,
    ) -> None:
        super().__init__()
        self.db = db
        self.strategy = strategy
        self.bot_uuid = bot_uuid
        self.rate_limiter = rate_limiter
        self.identity_client = identity_client

    def _is_mentioned(self, c: Context) -> bool:
        """Check if the bot is @-mentioned in the message.

        Tries structured mention data first (uuid match), then falls back to
        detecting the U+FFFC object replacement character that Signal inserts
        at mention positions — signal-cli-rest-api doesn't always include the
        mentions array in received messages.
        """
        for m in c.message.mentions:
            if isinstance(m, dict) and m.get("uuid") == self.bot_uuid:
                return True
        # Fallback: Signal inserts U+FFFC at each mention position.
        # If the message contains it, assume the bot was mentioned.
        # This works around a known signal-cli bug where mention metadata is
        # missing from received messages — fixed in signal-cli but not yet
        # ported to signal-cli-rest-api. Remove this fallback once the fix
        # lands upstream.
        # Only use fallback when no structured mentions exist at all;
        # if mentions are present but none match the bot, the bot was
        # genuinely not mentioned.
        if not c.message.mentions and c.message.text and "\uFFFC" in c.message.text:
            return True
        return False

    async def handle(self, c: Context) -> None:
        text = c.message.text
        if not text:
            return

        # In group chats, only respond when the bot is @-mentioned
        if c.message.group and not self._is_mentioned(c):
            return

        # Per-sender rate limiting (by UUID — never logs who was limited)
        if self.rate_limiter and not self.rate_limiter.is_allowed(
            c.message.source_uuid
        ):
            return

        # Strip the Unicode Object Replacement Character (U+FFFC) that
        # Signal inserts at each mention position, then clean up whitespace.
        text = text.replace("\uFFFC", "").strip()
        if not text:
            return

        # 1. Ask the strategy what to query
        sql, args = self.strategy.query(text)

        # 2. Execute the query against Grist (if any)
        rows = []
        if sql:
            try:
                rows = await self.db.execute(sql, args)
            except Exception:
                logger.warning("Grist query failed (details suppressed)")
                return

        # 3. If primary returned no rows, run the fuzzy fallback (if any)
        fuzzy_rows: list[dict] = []
        if not rows and hasattr(self.strategy, "fuzzy_query"):
            fuzzy_info = self.strategy.fuzzy_query(text)
            if fuzzy_info is not None:
                fz_sql, fz_args, fz_cfg = fuzzy_info
                try:
                    all_rows = await self.db.execute(fz_sql, fz_args)
                except Exception:
                    logger.warning(
                        "Fuzzy fetch failed (details suppressed)"
                    )
                    all_rows = []
                fuzzy_rows = self._rank_fuzzy(text, all_rows, fz_cfg)

        # 4. Pick the react/respond branch
        if fuzzy_rows:
            emoji = self.strategy.react_fuzzy(text, fuzzy_rows)
            response = self.strategy.respond_fuzzy(text, fuzzy_rows)
        else:
            emoji = self.strategy.react(text, rows)
            response = getattr(self.strategy, "respond", lambda *_: None)(
                text, rows
            )

        # 5. React on the original message (auto-trust retry handles
        #    "Untrusted Identity" failures from safety-number changes)
        if emoji is not None:
            await self._with_trust_retry(c, lambda: c.react(emoji))

        # 6. Optional text response (quoted reply or fresh message)
        if response is not None:
            reply_text, quote = response
            action = (
                (lambda: c.reply(reply_text))
                if quote
                else (lambda: c.send(reply_text))
            )
            await self._with_trust_retry(c, action)

    async def _with_trust_retry(self, c: Context, action) -> None:
        """Run ``action()`` once; on untrusted-identity failure, trust the
        sender's UUID and retry exactly once. Unrelated failures propagate.

        ``action`` is a zero-arg callable returning a coroutine — fresh each
        call so the retry runs a new coroutine, not an already-awaited one.
        """
        try:
            await action()
        except Exception as exc:
            if self.identity_client and self.identity_client.is_untrusted_error(exc):
                try:
                    await self.identity_client.trust(c.message.source_uuid)
                    await action()
                except Exception:
                    logger.warning(
                        "Auto-trust retry failed (details suppressed)"
                    )
                else:
                    logger.info("Auto-trusted sender after react failure")
                return
            raise

    @staticmethod
    def _rank_fuzzy(
        query_text: str, rows: list[dict], cfg: dict
    ) -> list[dict]:
        """Rank rows by fuzzy similarity against cfg['column'].

        Returns rows with a synthetic 'score' key added, in descending score
        order, filtered to those at or above cfg['threshold'], capped at
        cfg['limit']. Rows whose column value is None/empty are skipped.
        """
        column = cfg["column"]
        threshold = cfg.get("threshold", 80)
        limit = cfg.get("limit", 3)
        choices = {i: r[column] for i, r in enumerate(rows) if r.get(column)}
        matches = process.extract(
            query_text, choices, scorer=fuzz.WRatio, limit=limit
        )
        return [
            {**rows[idx], "score": score}
            for _value, score, idx in matches
            if score >= threshold
        ]
